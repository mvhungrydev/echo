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