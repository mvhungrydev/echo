#%%
import importlib
import os
import sys

import boto3
from moto import mock_aws

sys.path.insert(
    0,
    os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "src", "lambda_insights")
    ),
)
sys.path.insert(
    0,
    os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "src", "layers", "shared_utils")
    ),
)

TABLE_NAME = "EmailTriageResults-dev"


def _make_record(**overrides):
    base = {
        "email_id": "msg-001",
        "received_at": "2026-06-21T10:00:00+00:00",
        "from_address": "jane@example.com",
        "subject": "Test subject",
        "raw_s3_key": "raw-emails/msg-001",
        "category": "billing",
        "urgency": "medium",
        "urgency_override_applied": False,
        "sentiment": "negative",
        "confidence": "high",
        "review_status": "auto_processed",
        "suggested_reply": "We'll look into it.",
        "feature_tags": [],
        "redacted_body": "Some redacted text.",
        "pii_entities_detected": 0,
        "processed_at": "2026-06-21T10:00:05+00:00",
        "ttl": 1758466200,
    }
    base.update(overrides)
    return base


def _setup():
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
    os.environ["DYNAMODB_TABLE_NAME"] = TABLE_NAME
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    dynamodb.create_table(
        TableName=TABLE_NAME,
        KeySchema=[{"AttributeName": "email_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "email_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    table = dynamodb.Table(TABLE_NAME)
    sys.modules.pop("query", None)
    import query
    importlib.reload(query)
    return query, table

#%%

# ── test 1 ────────────────────────────────────────────────────────────────────


@mock_aws
def test_filter_returns_only_auto_processed():
    query, table = _setup()
    # insert one auto_processed and one needs_review record
    table.put_item(Item=_make_record())
    table.put_item(Item=_make_record(email_id="msg-002", review_status="needs_review"))
    # call query — should only return the auto_processed one
    result = query.get_auto_processed_records()
    # assert only 1 returned and it's the auto_processed record
    assert len(result) == 1
    assert result[0]["category"] == "billing"


# ── test 2 ────────────────────────────────────────────────────────────────────


@mock_aws
def test_only_five_projected_fields_returned():
    query, table = _setup()
    # insert a full record (all 17 fields)
    table.put_item(Item=_make_record())
    # call query — should return only 5 projected fields
    result = query.get_auto_processed_records()
    # assert exactly these 5 keys and no others
    assert set(result[0].keys()) == {"category", "urgency", "sentiment", "feature_tags", "received_at"}


# ── test 3 ────────────────────────────────────────────────────────────────────


@mock_aws
def test_empty_table_returns_empty_list():
    query, table = _setup()
    # no records inserted — should return []
    result = query.get_auto_processed_records()
    assert result == []


# ── test 4 ────────────────────────────────────────────────────────────────────


@mock_aws
def test_feature_tags_list_roundtrips():
    query, table = _setup()
    # insert a feature_request with tags
    table.put_item(Item=_make_record(category="feature_request", feature_tags=["dark-mode", "mobile-app"]))
    result = query.get_auto_processed_records()
    # assert feature_tags survives the projection
    assert result[0]["feature_tags"] == ["dark-mode", "mobile-app"]


# ── test 5 ────────────────────────────────────────────────────────────────────


@mock_aws
def test_pagination_concatenates_pages():
    query, table = _setup()
    # mock table.scan to return 2 pages via side_effect
    from unittest.mock import patch
    page1 = {
        "Items": [{"category": "billing", "urgency": "high", "sentiment": "negative", "feature_tags": [], "received_at": "2026-06-21T10:00:00+00:00"}],
        "LastEvaluatedKey": {"email_id": "msg-001"},
    }
    page2 = {
        "Items": [{"category": "praise", "urgency": "low", "sentiment": "positive", "feature_tags": [], "received_at": "2026-06-20T09:00:00+00:00"}],
    }
    with patch.object(query.table, "scan", side_effect=[page1, page2]):
        result = query.get_auto_processed_records()
    # assert both pages concatenated
    assert len(result) == 2
    assert result[0]["category"] == "billing"
    assert result[1]["category"] == "praise"
# %%
