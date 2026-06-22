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
    # simulates Bedrock's StreamingBody envelope
    envelope = json.dumps({"content": [{"type": "text", "text": text}]}).encode()
    return {"body": io.BytesIO(envelope)}


def _valid_classification(**overrides) -> dict:
    # a valid Bedrock classification response (before envelope wrapping)
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
    # create DynamoDB table under moto, reload all triage modules so
    # module-level clients bind to mocked AWS
    os.environ["DYNAMODB_TABLE_NAME"] = TABLE_NAME
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    dynamodb.create_table(
        TableName=TABLE_NAME,
        KeySchema=[{"AttributeName": "email_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "email_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    # reload chain: persist first (DynamoDB), then handler (imports persist/pii/classify)
    import persist, pii, classify, handler

    importlib.reload(persist)
    importlib.reload(handler)
    return handler, persist, pii, classify


event = {
    "Records": [
        {
            "body": '{"email_id":"msg-001","from_address":"jane@example.com","subject":"Help with billing","body":"Hi, my name is John Doe. I was charged twice.","received_at":"2026-06-21T10:00:00+00:00","raw_s3_key":"raw-emails/msg-001"}'
        }
    ]
}
# %%
# ── test 1 ────────────────────────────────────────────────────────────────────


@mock_aws
def test_happy_path_all_fields_persisted():
    handler, persist, pii, classify = _setup()
    fake_pii = {"Entities": []}
    fake_bedrock = _mock_bedrock_response(json.dumps(_valid_classification()))
    with patch.object(
        pii.comprehend, "detect_pii_entities", return_value=fake_pii
    ), patch.object(classify.bedrock, "invoke_model", return_value=fake_bedrock):
        handler.handler(event, None)


# ── test 2 ────────────────────────────────────────────────────────────────────


@mock_aws
def test_idempotency_short_circuits():
    # existing record for email_id -> handler returns early, no Comprehend/Bedrock/put calls
    pass


# ── test 3 ────────────────────────────────────────────────────────────────────


@mock_aws
def test_low_confidence_needs_review():
    # confidence=low -> review_status=needs_review
    pass


# ── test 4 ────────────────────────────────────────────────────────────────────


@mock_aws
def test_classification_failed_needs_review():
    # classification_failed=True -> review_status=needs_review regardless of confidence
    pass


# ── test 5 ────────────────────────────────────────────────────────────────────


@mock_aws
def test_keyword_override_wins():
    # keyword match + Bedrock urgency=medium -> persisted urgency=high, override_applied=True
    pass


# ── test 6 ────────────────────────────────────────────────────────────────────


@mock_aws
def test_feature_tags_roundtrip():
    # category=feature_request with feature_tags -> persisted as-is
    pass


# ── test 7 ────────────────────────────────────────────────────────────────────


@mock_aws
def test_poison_pill_raises_key_error():
    # SQS message missing body key -> KeyError raised, not caught
    pass


# ── test 8 ────────────────────────────────────────────────────────────────────


@mock_aws
def test_zero_pii_entities_field_present():
    # Comprehend returns zero entities -> pii_entities_detected=0 in persisted record
    pass


# ── test 9 ────────────────────────────────────────────────────────────────────


@mock_aws
def test_xray_annotation_called():
    # xray_recorder.put_annotation called with ("email_id", ...)
    pass


# %%
