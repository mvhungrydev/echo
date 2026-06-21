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
# import classify

# %%

import boto3
from retry_config import BEDROCK_CONFIG

bedrock = boto3.client("bedrock-runtime", config=BEDROCK_CONFIG)

# pinned model ARN — never float to "latest" so a model swap can't silently change output schema
MODEL_ID = "anthropic.claude-3-haiku-20240307-v1:0"

# enum sets used by _validate — any value outside these triggers a retry
VALID_CATEGORIES = {
    "bug_report",
    "feature_request",
    "general_inquiry",
    "billing",
    "complaint",
    "praise",
}
VALID_URGENCY = {"high", "medium", "low"}
VALID_SENTIMENT = {"positive", "negative", "constructive"}
VALID_CONFIDENCE = {"high", "medium", "low"}

# feature_tags is excluded — it's defaulted to [] in _try_parse, not validated here
REQUIRED_FIELDS = {"category", "urgency", "sentiment", "confidence", "suggested_reply"}

# instructs the model to return ONLY a JSON object with the 6 fields and their valid values
SYSTEM_PROMPT = ""  # TODO: pmc

# appended to SYSTEM_PROMPT on retry — tells the model its previous response was invalid
RETRY_SYSTEM_PROMPT = ""  # TODO: pmc

# FR17 fallback — returned when both invoke attempts fail to produce valid JSON
DEGRADED_RESULT = {
    "category": "unclassified",
    "urgency": "medium",
    "sentiment": "unknown",
    "confidence": "low",
    "suggested_reply": None,
    "feature_tags": [],
}


# %%
def _invoke(body_text: str, system_prompt: str, max_tokens: int) -> str:
    # call Bedrock with the Anthropic Messages format; return the raw text string
    # from the model's response (first JSON decode happens here — unwraps Bedrock envelope)
    response = bedrock.invoke_model(
        modelId=MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=json.dumps(
            {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": max_tokens,
                "temperature": 0.0,
                "system": system_prompt,
                "messages": [{"role": "user", "content": body_text}],
            }
        ),
    )
    result = json.loads(response["body"].read())["content"][0]["text"]
    print(result)
    return result


def _validate(parsed: dict) -> bool:
    # check all REQUIRED_FIELDS are present AND each enum field is within its VALID_* set
    return (
        REQUIRED_FIELDS.issubset(parsed.keys())
        and parsed["category"] in VALID_CATEGORIES
        and parsed["urgency"] in VALID_URGENCY
        and parsed["sentiment"] in VALID_SENTIMENT
        and parsed["confidence"] in VALID_CONFIDENCE
    )


def _try_parse(raw_text: str) -> dict | None:
    # second JSON decode — if it fails or _validate fails, return None
    # on success: setdefault feature_tags=[] so the field always exists for persist.py
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        return None

    if not _validate(parsed):
        return None
    parsed.setdefault("feature_tags", [])
    return parsed


def local_classify(body_text: str) -> dict:
    # attempt 1 -> attempt 2 (corrective prompt + larger max_tokens) -> DEGRADED_RESULT
    # always returns classification_failed bool so handler can emit ClassificationFailure metric
    parse_result = _try_parse(_invoke(body_text, SYSTEM_PROMPT, max_tokens=512))
    if parse_result is not None:
        return {**parse_result, "classification_failed": False}
    parse_result = _try_parse(_invoke(body_text, RETRY_SYSTEM_PROMPT, max_tokens=768))
    if parse_result is not None:
        return {**parse_result, "classification_failed": False}
    return {**DEGRADED_RESULT, "classification_failed": True}


def mock_bedrock_response(text: str) -> dict:
    # simulates Bedrock's StreamingBody — io.BytesIO has .read(), no botocore needed
    # wraps text in the Bedrock envelope: {"content": [{"type": "text", "text": "..."}]}
    envelope = json.dumps({"content": [{"type": "text", "text": text}]}).encode()
    print({"body": io.BytesIO(envelope)})
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
        bedrock, "invoke_model", return_value=mock_response
    ) as mock_invoke:
        result = local_classify("My app keeps crashing on login.")
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
        bedrock, "invoke_model", side_effect=[bad_response, good_response]
    ) as mock_invoke:
        result = local_classify("It would be great if you added dark mode.")
    assert result["classification_failed"] is False
    assert result["category"] == "feature_request"
    assert mock_invoke.call_count == 2
    # verify attempt 1 used SYSTEM_PROMPT + max_tokens=512
    attempt1_body = json.loads(mock_invoke.call_args_list[0].kwargs["body"])
    assert attempt1_body["system"] == SYSTEM_PROMPT
    assert attempt1_body["max_tokens"] == 512
    # verify attempt 2 used RETRY_SYSTEM_PROMPT + max_tokens=768
    attempt2_body = json.loads(mock_invoke.call_args_list[1].kwargs["body"])
    assert attempt2_body["system"] == RETRY_SYSTEM_PROMPT
    assert attempt2_body["max_tokens"] == 768


# %%
# ── test 3 ────────────────────────────────────────────────────────────────────


def test_both_attempts_fail_returns_degraded():
    # invalid JSON on both attempts -> FR17 degraded dict returned, classification_failed=True
    bad_response_1 = mock_bedrock_response("not json")
    bad_response_2 = mock_bedrock_response("also not json")
    with patch.object(
        bedrock, "invoke_model", side_effect=[bad_response_1, bad_response_2]
    ) as mock_invoke:
        result = local_classify("Some email body.")
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
        bedrock, "invoke_model", side_effect=[bad_response, good_response]
    ) as mock_invoke:
        result = local_classify("App crashes every time.")
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
        bedrock, "invoke_model", side_effect=[bad_response, good_response]
    ) as mock_invoke:
        result = local_classify("This is really urgent!")
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
    with patch.object(bedrock, "invoke_model", return_value=mock_response):
        result = local_classify("Just a quick question about your hours.")
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
        bedrock, "invoke_model", side_effect=[bad_response, good_response]
    ):
        result = local_classify("I was charged twice this month.")
    assert result["classification_failed"] is False
    assert result["category"] == "billing"


# %%
