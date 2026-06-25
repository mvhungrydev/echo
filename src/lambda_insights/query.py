import os

import boto3
from boto3.dynamodb.conditions import Attr
from retry_config import GENERAL_CONFIG

dynamodb = boto3.resource("dynamodb", config=GENERAL_CONFIG)
table = dynamodb.Table(os.environ["DYNAMODB_TABLE_NAME"])


def get_auto_processed_records() -> list[dict]:
    # scan EmailTriageResults for auto_processed records only,
    # projecting 5 fields for data-minimization (doc03 §2.2 step 24)
    records = []
    scan_kwargs = {
        # server-side filter — only return items where review_status=auto_processed
        "FilterExpression": Attr("review_status").eq("auto_processed"),
        # return only these 5 fields — excludes from_address/suggested_reply/raw_s3_key
        "ProjectionExpression": "category, urgency, sentiment, feature_tags, received_at",
    }

    # pagination loop — DynamoDB returns max 1MB per scan call
    while True:
        response = table.scan(**scan_kwargs)
        print(f"[insights.query] scanned page: {len(response['Items'])} items")
        records.extend(response["Items"])
        # no LastEvaluatedKey means this was the last page
        if "LastEvaluatedKey" not in response:
            break
        # cursor — tell next scan() to resume after this key
        scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
    print(f"[insights.query] total records returned: {len(records)}")
    return records


def query_triage_data(
    *,
    category: str | None = None,
    sentiment: str | None = None,
    urgency: str | None = None,
    from_address: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict]:
    # parameterized scan used by Bedrock tool use (doc06 §5.2)
    # base filter always applies — only auto_processed records are queryable
    filter_expression = Attr("review_status").eq("auto_processed")
    # layer optional filters via Attr AND chaining (&)
    if category is not None:
        filter_expression = filter_expression & Attr("category").eq(category)
    if sentiment is not None:
        filter_expression = filter_expression & Attr("sentiment").eq(sentiment)
    if urgency is not None:
        filter_expression = filter_expression & Attr("urgency").eq(urgency)
    if from_address is not None:
        filter_expression = filter_expression & Attr("from_address").eq(from_address)
    # date filtering works because ISO 8601 strings are lexicographically ordered
    if date_from is not None:
        filter_expression = filter_expression & Attr("received_at").gte(date_from)
    if date_to is not None:
        filter_expression = filter_expression & Attr("received_at").lte(date_to)

    print(f"[insights.query_triage_data] filters: category={category}, sentiment={sentiment}, "
          f"urgency={urgency}, from_address={from_address}, date_from={date_from}, date_to={date_to}")

    records = []
    scan_kwargs = {
        "FilterExpression": filter_expression,
        # 9-field projection — existing 5 + email_id, from_address, subject, redacted_body
        # so Bedrock can identify, attribute, and summarize specific emails
        "ProjectionExpression": "email_id, from_address, subject, redacted_body, "
                                "category, urgency, sentiment, feature_tags, received_at",
    }

    # pagination loop — DynamoDB returns max 1MB per scan call
    while True:
        response = table.scan(**scan_kwargs)
        print(f"[insights.query_triage_data] scanned page: {len(response['Items'])} items")
        records.extend(response["Items"])
        # no LastEvaluatedKey means this was the last page
        if "LastEvaluatedKey" not in response:
            break
        # cursor — tell next scan() to resume after this key
        scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
    print(f"[insights.query_triage_data] total records returned: {len(records)}")
    return records