# %%
import importlib
import json
import os
import sys

import boto3
from moto import mock_aws

# sys.path inserts must come before importing persist
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


def _setup():
    # create the DynamoDB table under moto, set env var, reload persist so
    # its module-level `table` binds to the mocked DynamoDB
    os.environ["DYNAMODB_TABLE_NAME"] = TABLE_NAME
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    dynamodb.create_table(
        TableName=TABLE_NAME,
        KeySchema=[{"AttributeName": "email_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "email_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    import persist
    importlib.reload(persist)
    return persist


def _make_record(**overrides):
    # builds a minimal valid record dict — tests override specific fields as needed
    base = {
        "email_id": "msg-001",
        "received_at": "2026-06-21T14:30:00+00:00",
        "from_address": "jane@example.com",
        "subject": "Charged twice",
        "raw_s3_key": "raw-emails/msg-001",
        "category": "billing",
        "urgency": "high",
        "sentiment": "negative",
        "confidence": "high",
        "suggested_reply": "We'll investigate the duplicate charge.",
        "feature_tags": [],
        "urgency_override_applied": True,
        "review_status": "auto_processed",
        "pii_entities_detected": 2,
        "redacted_body": "Hi, my name is [NAME]. I was charged twice...",
    }
    base.update(overrides)
    return base


# %%
# ── test 1 ────────────────────────────────────────────────────────────────────


@mock_aws
def test_get_nonexistent_record_returns_none():
    # get_existing_record with no item written -> returns None
    persist = _setup()
    result = persist.get_existing_record("nonexistent-id")
    assert result is None


# ── test 2 ────────────────────────────────────────────────────────────────────


@mock_aws
def test_put_then_get_roundtrip():
    # put_triage_record then get_existing_record -> returns same data
    persist = _setup()
    pass


# ── test 3 ────────────────────────────────────────────────────────────────────


@mock_aws
def test_ttl_is_received_at_plus_90_days():
    # ttl stored is int(received_at.timestamp()) + 7_776_000
    persist = _setup()
    pass


# ── test 4 ────────────────────────────────────────────────────────────────────


@mock_aws
def test_processed_at_computed_at_write_time():
    # processed_at is an ISO8601 string not present in input record
    persist = _setup()
    pass


# ── test 5 ────────────────────────────────────────────────────────────────────


@mock_aws
def test_none_and_empty_list_roundtrip():
    # suggested_reply=None and feature_tags=[] round-trip correctly
    persist = _setup()
    pass


# ── test 6 ────────────────────────────────────────────────────────────────────


@mock_aws
def test_bool_roundtrip():
    # urgency_override_applied=True/False round-trips as Python bool
    persist = _setup()
    pass


# ── test 7 ────────────────────────────────────────────────────────────────────


@mock_aws
def test_get_after_put_returns_non_none():
    # boundary: after put, get for same email_id returns non-None (idempotency short-circuit)
    persist = _setup()
    pass


# %%