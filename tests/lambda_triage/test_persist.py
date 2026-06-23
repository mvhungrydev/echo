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
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
    # env var must be set before reload — persist.py reads it at import time
    os.environ["DYNAMODB_TABLE_NAME"] = TABLE_NAME
    # create the table under moto before reload so persist's module-level
    # `table = dynamodb.Table(...)` binds to the mocked resource
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    dynamodb.create_table(
        TableName=TABLE_NAME,
        # PK-only schema matches doc04 §3 — no sort key
        KeySchema=[{"AttributeName": "email_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "email_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    import persist
    importlib.reload(persist)
    print(f"[test_persist._setup] table={TABLE_NAME} created, persist reloaded")
    return persist


def _make_record(**overrides):
    # mirrors the 15-field record that handler.py step 7 builds before calling put_triage_record
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
    print(f"[test 1] get nonexistent -> {result}")
    assert result is None


# ── test 2 ────────────────────────────────────────────────────────────────────


@mock_aws
def test_put_then_get_roundtrip():
    # put_triage_record then get_existing_record -> returns same data
    persist = _setup()
    record = _make_record()
    persist.put_triage_record(record)
    result = persist.get_existing_record("msg-001")
    print(f"[test 2] roundtrip result keys: {list(result.keys())}")
    assert result is not None
    assert result["email_id"] == "msg-001"
    assert result["category"] == "billing"
    assert result["urgency"] == "high"
    assert result["sentiment"] == "negative"
    assert result["from_address"] == "jane@example.com"
    assert result["subject"] == "Charged twice"
    assert result["raw_s3_key"] == "raw-emails/msg-001"
    assert result["review_status"] == "auto_processed"
    assert result["pii_entities_detected"] == 2
    assert result["redacted_body"] == "Hi, my name is [NAME]. I was charged twice..."


# ── test 3 ────────────────────────────────────────────────────────────────────


@mock_aws
def test_ttl_is_received_at_plus_90_days():
    # ttl stored is int(received_at.timestamp()) + 7_776_000
    persist = _setup()
    from datetime import datetime
    record = _make_record(received_at="2026-06-21T14:30:00+00:00")
    persist.put_triage_record(record)
    result = persist.get_existing_record("msg-001")
    # TTL = epoch seconds of received_at + 90 days (7,776,000 seconds)
    expected_ttl = int(datetime.fromisoformat("2026-06-21T14:30:00+00:00").timestamp()) + 7_776_000
    print(f"[test 3] stored ttl={result['ttl']}, expected={expected_ttl}")
    assert result["ttl"] == expected_ttl


# ── test 4 ────────────────────────────────────────────────────────────────────


@mock_aws
def test_processed_at_computed_at_write_time():
    # processed_at is an ISO8601 string not present in input record
    persist = _setup()
    record = _make_record()
    # confirm the caller doesn't pass processed_at — persist computes it
    assert "processed_at" not in record
    persist.put_triage_record(record)
    result = persist.get_existing_record("msg-001")
    assert "processed_at" in result
    # fromisoformat will raise if it's not valid ISO 8601
    from datetime import datetime
    datetime.fromisoformat(result["processed_at"])
    print(f"[test 4] processed_at={result['processed_at']}")


# ── test 5 ────────────────────────────────────────────────────────────────────


@mock_aws
def test_none_and_empty_list_roundtrip():
    # resource API stores None as DynamoDB NULL and [] as empty list — not stringified or dropped
    persist = _setup()
    record = _make_record(suggested_reply=None, feature_tags=[])
    persist.put_triage_record(record)
    result = persist.get_existing_record("msg-001")
    print(f"[test 5] suggested_reply={result['suggested_reply']}, feature_tags={result['feature_tags']}")
    assert result["suggested_reply"] is None
    assert result["feature_tags"] == []


# ── test 6 ────────────────────────────────────────────────────────────────────


@mock_aws
def test_bool_roundtrip():
    # resource API stores True/False as DynamoDB BOOL — not "True"/1
    persist = _setup()
    record_true = _make_record(email_id="msg-true", urgency_override_applied=True)
    record_false = _make_record(email_id="msg-false", urgency_override_applied=False)
    persist.put_triage_record(record_true)
    persist.put_triage_record(record_false)
    result_true = persist.get_existing_record("msg-true")
    result_false = persist.get_existing_record("msg-false")
    print(f"[test 6] True={result_true['urgency_override_applied']}, False={result_false['urgency_override_applied']}")
    assert result_true["urgency_override_applied"] is True
    assert result_false["urgency_override_applied"] is False


# ── test 7 ────────────────────────────────────────────────────────────────────


@mock_aws
def test_get_after_put_returns_non_none():
    # boundary: simulates the §4.6 idempotency guard — before processing, get returns None;
    # after processing, get returns non-None so a redelivered message would short-circuit
    persist = _setup()
    assert persist.get_existing_record("msg-001") is None
    persist.put_triage_record(_make_record())
    result = persist.get_existing_record("msg-001")
    print(f"[test 7] before=None, after={result is not None}")
    assert result is not None


# %%