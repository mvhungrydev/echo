# %%
import io
import json
import os
import sys
from unittest.mock import patch

# sys.path inserts must come before importing classify — same rule as test_pii.py
sys.path.insert(
    0,
    os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "src", "lambda_triage")
    ),
)
sys.path.insert(
    0,
    os.path.abspath(
        os.path.join(
            os.path.dirname(__file__), "..", "..", "src", "layers", "shared_utils"
        )
    ),
)

# import as module so classify.bedrock is accessible for patch.object
import classify


def mock_bedrock_response(text: str) -> dict:
    envelope = json.dumps({"content": [{"type": "text", "text": text}]}).encode()
    return {"body": io.BytesIO(envelope)}


# %%
# ── test 1 ────────────────────────────────────────────────────────────────────


def test_valid_response_on_first_attempt():
    # valid JSON on attempt 1 -> returns parsed dict, classification_failed=False, 1 invoke call
    valid = {
        "category": "bug_report",
        "urgency": "high",
        "sentiment": "negative",
        "confidence": "medium",
        "suggested_reply": "We're looking into this bug.",
    }
    mock_response = mock_bedrock_response(json.dumps(valid))
    with patch.object(
        classify.bedrock, "invoke_model", return_value=mock_response
    ) as mock_invoke:
        result = classify.classify("My app keeps crashing on login.")
    assert result["classification_failed"] is False
    assert result["category"] == "bug_report"
    assert result["urgency"] == "high"
    assert result["sentiment"] == "negative"
    assert result["confidence"] == "medium"
    assert result["suggested_reply"] == "We're looking into this bug."
    assert result["feature_tags"] == []
    assert mock_invoke.call_count == 1


# %%
# ── test 2 ────────────────────────────────────────────────────────────────────


def test_invalid_then_valid_triggers_retry():
    # invalid JSON on attempt 1, valid on attempt 2 -> attempt 2 used corrective prompt + max_tokens=768
    valid = {
        "category": "feature_request",
        "urgency": "low",
        "sentiment": "constructive",
        "confidence": "high",
        "suggested_reply": "Thanks for the suggestion!",
    }
    bad_response = mock_bedrock_response("not valid json at all")
    good_response = mock_bedrock_response(json.dumps(valid))
    with patch.object(
        classify.bedrock, "invoke_model", side_effect=[bad_response, good_response]
    ) as mock_invoke:
        result = classify.classify("It would be great if you added dark mode.")
    assert result["classification_failed"] is False
    assert result["category"] == "feature_request"
    assert mock_invoke.call_count == 2
    # verify attempt 1 used SYSTEM_PROMPT + max_tokens=512
    attempt1_body = json.loads(mock_invoke.call_args_list[0].kwargs["body"])
    assert attempt1_body["system"] == classify.SYSTEM_PROMPT
    assert attempt1_body["max_tokens"] == 512
    # verify attempt 2 used RETRY_SYSTEM_PROMPT + max_tokens=768
    attempt2_body = json.loads(mock_invoke.call_args_list[1].kwargs["body"])
    assert attempt2_body["system"] == classify.RETRY_SYSTEM_PROMPT
    assert attempt2_body["max_tokens"] == 768


# %%
# ── test 3 ────────────────────────────────────────────────────────────────────


def test_both_attempts_fail_returns_degraded():
    # invalid JSON on both attempts -> FR17 degraded dict returned, classification_failed=True
    bad_response_1 = mock_bedrock_response("not json")
    bad_response_2 = mock_bedrock_response("also not json")
    with patch.object(
        classify.bedrock, "invoke_model", side_effect=[bad_response_1, bad_response_2]
    ) as mock_invoke:
        result = classify.classify("Some email body.")
    assert result["classification_failed"] is True
    assert result["category"] == "unclassified"
    assert result["urgency"] == "medium"
    assert result["sentiment"] == "unknown"
    assert result["confidence"] == "low"
    assert result["suggested_reply"] is None
    assert result["feature_tags"] == []
    assert mock_invoke.call_count == 2


# ── test 4 ────────────────────────────────────────────────────────────────────


def test_missing_required_key_triggers_retry():
    # valid JSON but missing a required key (e.g. no "confidence") -> treated as invalid, triggers retry
    missing_key = {
        "category": "bug_report",
        "urgency": "high",
        "sentiment": "negative",
        "suggested_reply": "We'll fix it.",
        # "confidence" deliberately omitted
    }
    valid = {
        "category": "bug_report",
        "urgency": "high",
        "sentiment": "negative",
        "confidence": "medium",
        "suggested_reply": "We'll fix it.",
    }
    bad_response = mock_bedrock_response(json.dumps(missing_key))
    good_response = mock_bedrock_response(json.dumps(valid))
    with patch.object(
        classify.bedrock, "invoke_model", side_effect=[bad_response, good_response]
    ) as mock_invoke:
        result = classify.classify("App crashes every time.")
    assert result["classification_failed"] is False
    assert result["confidence"] == "medium"
    assert mock_invoke.call_count == 2


# ── test 5 ────────────────────────────────────────────────────────────────────


def test_invalid_enum_value_triggers_retry():
    # valid JSON but urgency="critical" (not in VALID_URGENCY) -> treated as invalid, triggers retry
    bad_enum = {
        "category": "bug_report",
        "urgency": "critical",
        "sentiment": "negative",
        "confidence": "high",
        "suggested_reply": "We'll look into it.",
    }
    valid = {
        "category": "bug_report",
        "urgency": "high",
        "sentiment": "negative",
        "confidence": "high",
        "suggested_reply": "We'll look into it.",
    }
    bad_response = mock_bedrock_response(json.dumps(bad_enum))
    good_response = mock_bedrock_response(json.dumps(valid))
    with patch.object(
        classify.bedrock, "invoke_model", side_effect=[bad_response, good_response]
    ) as mock_invoke:
        result = classify.classify("This is really urgent!")
    assert result["classification_failed"] is False
    assert result["urgency"] == "high"
    assert mock_invoke.call_count == 2


# ── test 6 ────────────────────────────────────────────────────────────────────


def test_missing_feature_tags_defaults_to_empty_list():
    # category="general_inquiry", response omits feature_tags -> result has feature_tags=[]
    no_tags = {
        "category": "general_inquiry",
        "urgency": "low",
        "sentiment": "positive",
        "confidence": "high",
        "suggested_reply": "Happy to help!",
    }
    mock_response = mock_bedrock_response(json.dumps(no_tags))
    with patch.object(classify.bedrock, "invoke_model", return_value=mock_response):
        result = classify.classify("Just a quick question about your hours.")
    assert result["feature_tags"] == []
    assert result["classification_failed"] is False


# ── test 7 ────────────────────────────────────────────────────────────────────


def test_response_body_read_only_once_per_invoke():
    # StreamingBody mock raises on second .read() -> confirms no accidental double-read on retry path
    valid = {
        "category": "billing",
        "urgency": "medium",
        "sentiment": "negative",
        "confidence": "medium",
        "suggested_reply": "Let me check your account.",
    }

    class ReadOnceBody:
        def __init__(self, data: bytes):
            self._data = data
            self._read = False

        def read(self):
            if self._read:
                raise IOError("StreamingBody read twice")
            self._read = True
            return self._data

    def make_read_once_response():
        envelope = json.dumps({"content": [{"type": "text", "text": json.dumps(valid)}]}).encode()
        return {"body": ReadOnceBody(envelope)}

    bad_response = mock_bedrock_response("not json")
    good_response = make_read_once_response()
    with patch.object(
        classify.bedrock, "invoke_model", side_effect=[bad_response, good_response]
    ):
        result = classify.classify("I was charged twice this month.")
    assert result["classification_failed"] is False
    assert result["category"] == "billing"


# %%
