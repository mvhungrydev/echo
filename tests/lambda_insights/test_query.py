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


# ══════════════════════════════════════════════════════════════════════════════
# Tests 6–15: query_triage_data (parameterized, 9-field projection)
# ══════════════════════════════════════════════════════════════════════════════

# ── test 6 ────────────────────────────────────────────────────────────────────


@mock_aws
def test_query_triage_data_no_filters_returns_all_auto_processed():
    # no filters → returns every auto_processed record, excludes needs_review
    query, table = _setup()
    table.put_item(Item=_make_record())
    table.put_item(Item=_make_record(email_id="msg-002"))
    table.put_item(Item=_make_record(email_id="msg-003", review_status="needs_review"))
    result = query.query_triage_data()
    assert len(result) == 2


# ── test 7 ────────────────────────────────────────────────────────────────────


@mock_aws
def test_query_triage_data_category_filter():
    # category="billing" → only billing records returned
    query, table = _setup()
    table.put_item(Item=_make_record())
    table.put_item(Item=_make_record(email_id="msg-002", category="praise"))
    result = query.query_triage_data(category="billing")
    assert len(result) == 1
    assert result[0]["category"] == "billing"


# ── test 8 ────────────────────────────────────────────────────────────────────


@mock_aws
def test_query_triage_data_multiple_filters_and():
    # sentiment="negative" + category="billing" → intersection only
    query, table = _setup()
    table.put_item(Item=_make_record())  # billing + negative
    table.put_item(Item=_make_record(email_id="msg-002", category="billing", sentiment="positive"))
    table.put_item(Item=_make_record(email_id="msg-003", category="praise", sentiment="negative"))
    result = query.query_triage_data(sentiment="negative", category="billing")
    assert len(result) == 1
    assert result[0]["category"] == "billing"
    assert result[0]["sentiment"] == "negative"


# ── test 9 ────────────────────────────────────────────────────────────────────


@mock_aws
def test_query_triage_data_from_address_filter():
    # from_address="jane@example.com" → only that sender
    query, table = _setup()
    table.put_item(Item=_make_record())  # jane@example.com
    table.put_item(Item=_make_record(email_id="msg-002", from_address="bob@acme.com"))
    result = query.query_triage_data(from_address="jane@example.com")
    assert len(result) == 1
    assert result[0]["from_address"] == "jane@example.com"


# ── test 10 ───────────────────────────────────────────────────────────────────


@mock_aws
def test_query_triage_data_date_from_filter():
    # date_from → records on/after that date
    query, table = _setup()
    table.put_item(Item=_make_record(received_at="2026-06-20T09:00:00+00:00"))
    table.put_item(Item=_make_record(email_id="msg-002", received_at="2026-06-22T09:00:00+00:00"))
    result = query.query_triage_data(date_from="2026-06-21T00:00:00+00:00")
    assert len(result) == 1
    assert result[0]["received_at"] == "2026-06-22T09:00:00+00:00"


# ── test 11 ───────────────────────────────────────────────────────────────────


@mock_aws
def test_query_triage_data_date_range_filter():
    # date_from + date_to → records within window only
    query, table = _setup()
    table.put_item(Item=_make_record(received_at="2026-06-19T09:00:00+00:00"))
    table.put_item(Item=_make_record(email_id="msg-002", received_at="2026-06-21T10:00:00+00:00"))
    table.put_item(Item=_make_record(email_id="msg-003", received_at="2026-06-23T09:00:00+00:00"))
    result = query.query_triage_data(
        date_from="2026-06-20T00:00:00+00:00",
        date_to="2026-06-22T00:00:00+00:00",
    )
    assert len(result) == 1
    assert result[0]["received_at"] == "2026-06-21T10:00:00+00:00"


# ── test 12 ───────────────────────────────────────────────────────────────────


@mock_aws
def test_query_triage_data_returns_nine_projected_fields():
    # returned records have exactly 9 fields, not 5 or 17
    query, table = _setup()
    table.put_item(Item=_make_record())
    result = query.query_triage_data()
    expected_keys = {
        "email_id", "from_address", "subject", "redacted_body",
        "category", "urgency", "sentiment", "feature_tags", "received_at",
    }
    assert set(result[0].keys()) == expected_keys


# ── test 13 ───────────────────────────────────────────────────────────────────


@mock_aws
def test_query_triage_data_excludes_needs_review_even_with_matching_filters():
    # needs_review excluded even when category/sentiment filters match
    query, table = _setup()
    table.put_item(Item=_make_record(review_status="needs_review"))
    table.put_item(Item=_make_record(email_id="msg-002"))  # auto_processed
    result = query.query_triage_data(category="billing")
    assert len(result) == 1
    assert result[0]["email_id"] == "msg-002"


# ── test 14 ───────────────────────────────────────────────────────────────────


@mock_aws
def test_query_triage_data_no_matches_returns_empty():
    # filters that match nothing → []
    query, table = _setup()
    table.put_item(Item=_make_record())  # billing, not praise
    result = query.query_triage_data(category="praise")
    assert result == []


# ── test 15 ───────────────────────────────────────────────────────────────────


@mock_aws
def test_query_triage_data_pagination():
    # mocked pagination — 2 pages concatenated
    query, table = _setup()
    from unittest.mock import patch
    page1 = {
        "Items": [{"email_id": "msg-001", "from_address": "a@b.com", "subject": "S1",
                   "redacted_body": "body1", "category": "billing", "urgency": "high",
                   "sentiment": "negative", "feature_tags": [],
                   "received_at": "2026-06-21T10:00:00+00:00"}],
        "LastEvaluatedKey": {"email_id": "msg-001"},
    }
    page2 = {
        "Items": [{"email_id": "msg-002", "from_address": "c@d.com", "subject": "S2",
                   "redacted_body": "body2", "category": "praise", "urgency": "low",
                   "sentiment": "positive", "feature_tags": [],
                   "received_at": "2026-06-20T09:00:00+00:00"}],
    }
    with patch.object(query.table, "scan", side_effect=[page1, page2]):
        result = query.query_triage_data()
    assert len(result) == 2
    assert result[0]["email_id"] == "msg-001"
    assert result[1]["email_id"] == "msg-002"
# %%
