import os
from datetime import datetime, timezone
import boto3
from retry_config import GENERAL_CONFIG

# resource API (not client) — accepts/returns native Python types (None, bool, list)
# without needing DynamoDB's {"S": "..."} / {"BOOL": true} type wrappers
dynamodb = boto3.resource("dynamodb", config=GENERAL_CONFIG)
# table name comes from Lambda env var wired by Terraform (doc04 §1.3)
# evaluated at import time — tests must set the env var before importlib.reload()
table = dynamodb.Table(os.environ["DYNAMODB_TABLE_NAME"])
TTL_SECONDS = 90 * 24 * 60 * 60  # 7_776_000 (90 days, doc03 §8.5)


def get_existing_record(email_id: str) -> dict | None:
    # §4.6 idempotency check — handler calls this before any paid AI work
    # response has no "Item" key at all when not found — .get() returns None safely
    response = table.get_item(Key={"email_id": email_id})
    result = response.get("Item")
    print(f"[persist.get_existing_record] email_id={email_id}, found={result is not None}")
    return result


def put_triage_record(record: dict) -> None:
    # parse received_at to compute TTL — fromisoformat handles the timezone offset
    received_at = datetime.fromisoformat(record["received_at"])
    # DynamoDB TTL expects epoch seconds (int) — auto-deletes records after 90 days
    ttl = int(received_at.timestamp()) + TTL_SECONDS
    item = {
        **record,
        # processed_at is computed at write time, not passed in by the caller
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "ttl": ttl,
    }
    print(f"[persist.put_triage_record] writing email_id={record['email_id']}, ttl={ttl}, fields={len(item)}")
    table.put_item(Item=item)
