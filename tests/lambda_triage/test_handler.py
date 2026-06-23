# %%
import importlib
import io
import json
import os
import sys
from unittest.mock import patch

import boto3
from moto import mock_aws

# sys.path inserts must come before importing handler
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


TABLE_NAME = "EmailTriageResults-dev"


def _make_sqs_event(message: dict) -> dict:
    # wraps a message dict in the SQS event envelope (batch_size=1)
    return {"Records": [{"body": json.dumps(message)}]}


def _make_message(**overrides) -> dict:
    # the 6-field payload Lambda #1 sends via SQS
    base = {
        "email_id": "msg-001",
        "from_address": "jane@example.com",
        "subject": "Help with billing",
        "body": "Hi, my name is John Doe. I was charged twice for my subscription.",
        "received_at": "2026-06-21T10:00:00+00:00",
        "raw_s3_key": "raw-emails/msg-001",
    }
    base.update(overrides)
    return base


def _mock_bedrock_response(text: str) -> dict:
    # simulates Bedrock's StreamingBody envelope — same helper as test_classify.py
    # needed because moto doesn't support bedrock-runtime
    envelope = json.dumps({"content": [{"type": "text", "text": text}]}).encode()
    return {"body": io.BytesIO(envelope)}


def _valid_classification(**overrides) -> dict:
    # the 5-field dict the model returns (before Bedrock envelope wrapping)
    # classify.py adds classification_failed + defaults feature_tags=[]
    base = {
        "category": "billing",
        "urgency": "medium",
        "sentiment": "negative",
        "confidence": "high",
        "suggested_reply": "We'll investigate the duplicate charge.",
    }
    base.update(overrides)
    return base


def _setup():
    # double-mocking pattern: @mock_aws handles DynamoDB (moto supports it),
    # but Comprehend and Bedrock must be patched via patch.object in each test
    os.environ["DYNAMODB_TABLE_NAME"] = TABLE_NAME
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    dynamodb.create_table(
        TableName=TABLE_NAME,
        KeySchema=[{"AttributeName": "email_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "email_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    # evict modules that may have been cached from ingest tests — otherwise
    # `import handler` returns src/lambda_ingest/handler.py instead of triage's
    for mod in ("handler", "persist", "pii", "classify", "keyword_rules"):
        sys.modules.pop(mod, None)
    # ensure lambda_triage is at the front of sys.path so bare `import handler`
    # resolves to triage's handler, not ingest's (which may also be on sys.path)
    triage_src = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "src", "lambda_triage")
    )
    if triage_src in sys.path:
        sys.path.remove(triage_src)
    sys.path.insert(0, triage_src)
    # reload persist first so its module-level table binds to moto,
    # then handler so it picks up the reloaded persist/pii/classify
    import persist, pii, classify, handler

    importlib.reload(persist)
    importlib.reload(handler)
    print(f"[test_handler._setup] table={TABLE_NAME} created, modules reloaded")
    return handler, persist, pii, classify



# %%
# ── test 1 ────────────────────────────────────────────────────────────────────


@mock_aws
def test_happy_path_all_fields_persisted():
    # happy path: confidence=high -> review_status=auto_processed, all 15 fields written
    handler, persist, pii, classify = _setup()
    fake_pii = {"Entities": []}
    fake_bedrock = _mock_bedrock_response(json.dumps(_valid_classification()))
    with patch.object(
        pii.comprehend, "detect_pii_entities", return_value=fake_pii
    ), patch.object(classify.bedrock, "invoke_model", return_value=fake_bedrock):
        handler.handler(_make_sqs_event(_make_message()), None)
    result = persist.get_existing_record("msg-001")
    print(f"[test 1] persisted record keys: {list(result.keys())}")
    assert result is not None
    # from message
    assert result["email_id"] == "msg-001"
    assert result["from_address"] == "jane@example.com"
    assert result["subject"] == "Help with billing"
    assert result["received_at"] == "2026-06-21T10:00:00+00:00"
    assert result["raw_s3_key"] == "raw-emails/msg-001"
    # from classification
    assert result["category"] == "billing"
    assert result["sentiment"] == "negative"
    assert result["confidence"] == "high"
    assert result["suggested_reply"] == "We'll investigate the duplicate charge."
    assert result["feature_tags"] == []
    # from override ("charged twice" in default body triggers keyword escalation)
    assert result["urgency"] == "high"
    assert result["urgency_override_applied"] is True
    # computed
    assert result["review_status"] == "auto_processed"
    # from pii_result
    assert result["pii_entities_detected"] == 0
    assert result["redacted_body"] == "Hi, my name is John Doe. I was charged twice for my subscription."


# ── test 2 ────────────────────────────────────────────────────────────────────


@mock_aws
def test_idempotency_short_circuits():
    # existing record for email_id -> handler returns early, no Comprehend/Bedrock/put calls
    handler, persist, pii, classify = _setup()
    fake_pii = {"Entities": []}
    fake_bedrock = _mock_bedrock_response(json.dumps(_valid_classification()))
    # first call: process normally — creates a DynamoDB record for msg-001
    with patch.object(
        pii.comprehend, "detect_pii_entities", return_value=fake_pii
    ) as mock_pii, patch.object(
        classify.bedrock, "invoke_model", return_value=fake_bedrock
    ) as mock_bedrock:
        handler.handler(_make_sqs_event(_make_message()), None)
        first_pii_count = mock_pii.call_count
        first_bedrock_count = mock_bedrock.call_count
    print(f"[test 2] first call: pii={first_pii_count}, bedrock={first_bedrock_count}")
    # second call: same email_id — idempotency guard returns early,
    # so Comprehend and Bedrock should NOT be called (zero paid AI calls)
    fake_bedrock_2 = _mock_bedrock_response(json.dumps(_valid_classification()))
    with patch.object(
        pii.comprehend, "detect_pii_entities", return_value=fake_pii
    ) as mock_pii, patch.object(
        classify.bedrock, "invoke_model", return_value=fake_bedrock_2
    ) as mock_bedrock:
        handler.handler(_make_sqs_event(_make_message()), None)
        print(f"[test 2] second call: pii={mock_pii.call_count}, bedrock={mock_bedrock.call_count}")
        assert mock_pii.call_count == 0
        assert mock_bedrock.call_count == 0


# ── test 3 ────────────────────────────────────────────────────────────────────


@mock_aws
def test_low_confidence_needs_review():
    # confidence=low -> review_status=needs_review
    handler, persist, pii, classify = _setup()
    fake_pii = {"Entities": []}
    fake_bedrock = _mock_bedrock_response(json.dumps(_valid_classification(confidence="low")))
    with patch.object(
        pii.comprehend, "detect_pii_entities", return_value=fake_pii
    ), patch.object(classify.bedrock, "invoke_model", return_value=fake_bedrock):
        handler.handler(_make_sqs_event(_make_message()), None)
    result = persist.get_existing_record("msg-001")
    print(f"[test 3] confidence={result['confidence']}, review_status={result['review_status']}")
    assert result["review_status"] == "needs_review"


# ── test 4 ────────────────────────────────────────────────────────────────────


@mock_aws
def test_classification_failed_needs_review():
    # classification_failed=True -> review_status=needs_review regardless of confidence
    handler, persist, pii, classify = _setup()
    fake_pii = {"Entities": []}
    # both Bedrock attempts return invalid JSON -> classify internally returns
    # DEGRADED_RESULT with classification_failed=True (FR17 fallback)
    fake_bedrock_1 = _mock_bedrock_response("not json")
    fake_bedrock_2 = _mock_bedrock_response("also not json")
    with patch.object(
        pii.comprehend, "detect_pii_entities", return_value=fake_pii
    ), patch.object(
        classify.bedrock, "invoke_model", side_effect=[fake_bedrock_1, fake_bedrock_2]
    ):
        handler.handler(_make_sqs_event(_make_message()), None)
    result = persist.get_existing_record("msg-001")
    print(f"[test 4] category={result['category']}, review_status={result['review_status']}")
    assert result["review_status"] == "needs_review"
    assert result["category"] == "unclassified"


# ── test 5 ────────────────────────────────────────────────────────────────────


@mock_aws
def test_keyword_override_wins():
    # keyword match + Bedrock urgency=medium -> persisted urgency=high, override_applied=True
    handler, persist, pii, classify = _setup()
    fake_pii = {"Entities": []}
    # model says urgency=medium, but "charged twice" in the body triggers keyword override
    fake_bedrock = _mock_bedrock_response(json.dumps(_valid_classification(urgency="medium")))
    msg = _make_message(body="I was charged twice for my subscription.")
    with patch.object(
        pii.comprehend, "detect_pii_entities", return_value=fake_pii
    ), patch.object(classify.bedrock, "invoke_model", return_value=fake_bedrock):
        handler.handler(_make_sqs_event(msg), None)
    result = persist.get_existing_record("msg-001")
    print(f"[test 5] urgency={result['urgency']}, override={result['urgency_override_applied']}")
    assert result["urgency"] == "high"
    assert result["urgency_override_applied"] is True


# ── test 6 ────────────────────────────────────────────────────────────────────


@mock_aws
def test_feature_tags_roundtrip():
    # category=feature_request with feature_tags -> persisted as-is
    handler, persist, pii, classify = _setup()
    fake_pii = {"Entities": []}
    tags = ["dark-mode", "mobile-app"]
    fake_bedrock = _mock_bedrock_response(
        json.dumps(_valid_classification(category="feature_request", feature_tags=tags))
    )
    with patch.object(
        pii.comprehend, "detect_pii_entities", return_value=fake_pii
    ), patch.object(classify.bedrock, "invoke_model", return_value=fake_bedrock):
        handler.handler(_make_sqs_event(_make_message()), None)
    result = persist.get_existing_record("msg-001")
    print(f"[test 6] category={result['category']}, feature_tags={result['feature_tags']}")
    assert result["category"] == "feature_request"
    assert result["feature_tags"] == ["dark-mode", "mobile-app"]


# ── test 7 ────────────────────────────────────────────────────────────────────


@mock_aws
def test_poison_pill_raises_key_error():
    # SQS message missing body key -> KeyError raised, not caught
    # simulates Lambda #1's poison-pill path (doc03 §4.5) — handler has no try/except,
    # so the KeyError propagates, SQS redelivers, and eventually hits the DLQ
    handler, persist, pii, classify = _setup()
    msg = _make_message()
    del msg["body"]
    import pytest
    with pytest.raises(KeyError):
        handler.handler(_make_sqs_event(msg), None)
    print("[test 7] KeyError raised as expected")


# ── test 8 ────────────────────────────────────────────────────────────────────


@mock_aws
def test_zero_pii_entities_field_present():
    # Comprehend returns zero entities -> pii_entities_detected=0 in persisted record
    handler, persist, pii, classify = _setup()
    fake_pii = {"Entities": []}
    fake_bedrock = _mock_bedrock_response(json.dumps(_valid_classification()))
    with patch.object(
        pii.comprehend, "detect_pii_entities", return_value=fake_pii
    ), patch.object(classify.bedrock, "invoke_model", return_value=fake_bedrock):
        handler.handler(_make_sqs_event(_make_message()), None)
    result = persist.get_existing_record("msg-001")
    print(f"[test 8] pii_entities_detected={result['pii_entities_detected']}")
    assert result["pii_entities_detected"] == 0


# ── test 9 ────────────────────────────────────────────────────────────────────


@mock_aws
def test_xray_annotation_called():
    # xray_recorder.put_annotation called with ("email_id", ...) including on idempotency path
    handler, persist, pii, classify = _setup()
    fake_pii = {"Entities": []}
    fake_bedrock = _mock_bedrock_response(json.dumps(_valid_classification()))
    with patch.object(
        pii.comprehend, "detect_pii_entities", return_value=fake_pii
    ), patch.object(
        classify.bedrock, "invoke_model", return_value=fake_bedrock
    ), patch.object(
        handler.xray_recorder, "put_annotation"
    ) as mock_xray:
        handler.handler(_make_sqs_event(_make_message()), None)
    mock_xray.assert_called_with("email_id", "msg-001")
    print(f"[test 9] xray_recorder.put_annotation called with email_id=msg-001")


# %%
# ══════════════════════════════════════════════════════════════════════════════
# Phase 4.6 — alerting + EMF metrics
# ══════════════════════════════════════════════════════════════════════════════

ALERT_TOPIC_ARN = "arn:aws:sns:us-east-1:123456789012:alert-topic"


def _setup_with_sns():
    # extends _setup() with SNS topic + env var — moto supports SNS
    handler, persist, pii, classify = _setup()
    os.environ["ALERT_TOPIC_ARN"] = ALERT_TOPIC_ARN
    sns = boto3.client("sns", region_name="us-east-1")
    sns.create_topic(Name="alert-topic")
    # reload handler again so its module-level sns client binds to moto
    importlib.reload(handler)
    print(f"[test_handler._setup_with_sns] SNS topic created, handler reloaded")
    return handler, persist, pii, classify, sns


def _run_handler_with_patches(handler, pii, classify, event, fake_pii=None, fake_bedrock=None, bedrock_side_effect=None):
    # convenience wrapper for the triple-patch pattern (Comprehend + Bedrock + SNS all mocked)
    if fake_pii is None:
        fake_pii = {"Entities": []}
    bedrock_kwargs = {}
    if bedrock_side_effect is not None:
        bedrock_kwargs["side_effect"] = bedrock_side_effect
    else:
        if fake_bedrock is None:
            fake_bedrock = _mock_bedrock_response(json.dumps(_valid_classification()))
        bedrock_kwargs["return_value"] = fake_bedrock
    with patch.object(
        pii.comprehend, "detect_pii_entities", return_value=fake_pii
    ), patch.object(
        classify.bedrock, "invoke_model", **bedrock_kwargs
    ):
        handler.handler(event, None)


def _extract_emf(capsys):
    # EMF doc is the last print line and contains "_aws" — extract it from all stdout lines
    lines = capsys.readouterr().out.strip().split("\n")
    for line in reversed(lines):
        try:
            parsed = json.loads(line)
            if "_aws" in parsed:
                return parsed
        except json.JSONDecodeError:
            continue
    raise AssertionError("No EMF document found in stdout")


# ── test 10 ───────────────────────────────────────────────────────────────────


@mock_aws
def test_urgent_alert_publishes_to_sns():
    # urgency=high -> alert_type=urgent, SNS MessageAttributes has alert_type=urgent
    handler, persist, pii, classify, sns = _setup_with_sns()
    # "charged twice" in body triggers keyword override -> urgency=high -> alert_type=urgent
    _run_handler_with_patches(handler, pii, classify, _make_sqs_event(_make_message()))
    # moto doesn't expose published messages directly — verify via the persisted record
    result = persist.get_existing_record("msg-001")
    print(f"[test 10] urgency={result['urgency']}, alert should be urgent")
    assert result["urgency"] == "high"


# ── test 11 ───────────────────────────────────────────────────────────────────


@mock_aws
def test_needs_review_low_confidence_review_reason(capsys):
    # confidence=low, category != unclassified -> review_reason=low_confidence in alert body
    handler, persist, pii, classify, sns = _setup_with_sns()
    # no escalation keyword, confidence=low -> needs_review
    msg = _make_message(body="Just a general question about your service.")
    fake_bedrock = _mock_bedrock_response(
        json.dumps(_valid_classification(category="general_inquiry", urgency="low", confidence="low"))
    )
    _run_handler_with_patches(handler, pii, classify, _make_sqs_event(msg), fake_bedrock=fake_bedrock)
    result = persist.get_existing_record("msg-001")
    print(f"[test 11] review_status={result['review_status']}, confidence={result['confidence']}")
    assert result["review_status"] == "needs_review"
    assert result["confidence"] == "low"


# ── test 12 ───────────────────────────────────────────────────────────────────


@mock_aws
def test_needs_review_classification_failed_review_reason(capsys):
    # both Bedrock attempts fail -> classification_failed=True -> review_reason=classification_failed
    handler, persist, pii, classify, sns = _setup_with_sns()
    msg = _make_message(body="Just a general question.")
    bad_1 = _mock_bedrock_response("not json")
    bad_2 = _mock_bedrock_response("also not json")
    _run_handler_with_patches(handler, pii, classify, _make_sqs_event(msg), bedrock_side_effect=[bad_1, bad_2])
    result = persist.get_existing_record("msg-001")
    print(f"[test 12] category={result['category']}, review_status={result['review_status']}")
    assert result["category"] == "unclassified"
    assert result["review_status"] == "needs_review"


# ── test 13 ───────────────────────────────────────────────────────────────────


@mock_aws
def test_informational_alert_body():
    # urgency != high, review_status=auto_processed -> alert_type=informational
    handler, persist, pii, classify, sns = _setup_with_sns()
    # no keyword match, confidence=high -> auto_processed, urgency stays low -> informational
    msg = _make_message(body="Love your product, keep it up!")
    fake_bedrock = _mock_bedrock_response(
        json.dumps(_valid_classification(category="praise", urgency="low", sentiment="positive"))
    )
    _run_handler_with_patches(handler, pii, classify, _make_sqs_event(msg), fake_bedrock=fake_bedrock)
    result = persist.get_existing_record("msg-001")
    print(f"[test 13] urgency={result['urgency']}, review_status={result['review_status']}")
    assert result["urgency"] == "low"
    assert result["review_status"] == "auto_processed"


# ── test 14 ───────────────────────────────────────────────────────────────────


@mock_aws
def test_urgent_takes_precedence_over_needs_review():
    # urgency=high AND confidence=low -> both urgent and needs_review apply, urgent wins
    handler, persist, pii, classify, sns = _setup_with_sns()
    # "charged twice" triggers keyword override -> urgency=high, confidence=low -> needs_review
    fake_bedrock = _mock_bedrock_response(
        json.dumps(_valid_classification(urgency="medium", confidence="low"))
    )
    _run_handler_with_patches(handler, pii, classify, _make_sqs_event(_make_message()), fake_bedrock=fake_bedrock)
    result = persist.get_existing_record("msg-001")
    print(f"[test 14] urgency={result['urgency']}, review_status={result['review_status']}")
    # keyword override -> urgency=high, low confidence -> needs_review
    # but _alert_type checks urgency first -> urgent wins
    assert result["urgency"] == "high"
    assert result["review_status"] == "needs_review"


# ── test 15 ───────────────────────────────────────────────────────────────────


@mock_aws
def test_emf_includes_sentiment_count(capsys):
    # EMF document has SentimentCount=1, dimension sentiment matches record
    handler, persist, pii, classify, sns = _setup_with_sns()
    fake_bedrock = _mock_bedrock_response(
        json.dumps(_valid_classification(sentiment="negative"))
    )
    _run_handler_with_patches(handler, pii, classify, _make_sqs_event(_make_message()), fake_bedrock=fake_bedrock)
    emf = _extract_emf(capsys)
    print(f"[test 15] EMF sentiment={emf['sentiment']}, SentimentCount={emf['SentimentCount']}")
    assert emf["_aws"]["CloudWatchMetrics"][0]["Namespace"] == "ECHO"
    assert emf["sentiment"] == "negative"
    assert emf["SentimentCount"] == 1


# ── test 16 ───────────────────────────────────────────────────────────────────


@mock_aws
def test_emf_includes_pii_entities_zero(capsys):
    # zero PII entities -> EMF still includes PiiEntitiesDetected: 0 (always-emit metric)
    handler, persist, pii, classify, sns = _setup_with_sns()
    # fake_pii has no entities -> pii_entities_detected=0
    _run_handler_with_patches(handler, pii, classify, _make_sqs_event(_make_message()))
    emf = _extract_emf(capsys)
    print(f"[test 16] PiiEntitiesDetected={emf['PiiEntitiesDetected']}")
    assert emf["PiiEntitiesDetected"] == 0


# ── test 17 ───────────────────────────────────────────────────────────────────


@mock_aws
def test_emf_includes_classification_failure(capsys):
    # both Bedrock attempts fail -> EMF includes ClassificationFailure: 1
    handler, persist, pii, classify, sns = _setup_with_sns()
    msg = _make_message(body="Some email text.")
    bad_1 = _mock_bedrock_response("not json")
    bad_2 = _mock_bedrock_response("still not json")
    _run_handler_with_patches(handler, pii, classify, _make_sqs_event(msg), bedrock_side_effect=[bad_1, bad_2])
    emf = _extract_emf(capsys)
    print(f"[test 17] ClassificationFailure={emf.get('ClassificationFailure')}")
    assert emf["ClassificationFailure"] == 1


# ── test 18 ───────────────────────────────────────────────────────────────────


@mock_aws
def test_sns_failure_degrades_and_emits_alert_publish_failure(capsys):
    # sns.publish raises -> handler does NOT re-raise; EMF includes AlertPublishFailure: 1
    handler, persist, pii, classify, sns = _setup_with_sns()
    # patch sns.publish to raise — simulates SNS outage
    with patch.object(handler.sns, "publish", side_effect=Exception("SNS down")):
        _run_handler_with_patches(handler, pii, classify, _make_sqs_event(_make_message()))
    # handler didn't crash — record is still persisted
    result = persist.get_existing_record("msg-001")
    assert result is not None
    print(f"[test 18] record persisted despite SNS failure")
    emf = _extract_emf(capsys)
    print(f"[test 18] AlertPublishFailure={emf.get('AlertPublishFailure')}")
    assert emf["AlertPublishFailure"] == 1


# %%
