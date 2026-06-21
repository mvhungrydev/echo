import boto3
import json
import os
from urllib.parse import unquote_plus
from mime_parser import parse_email
from retry_config import GENERAL_CONFIG
from aws_xray_sdk.core import xray_recorder

# xray_recorder must be configured after importing retry_config
# (which imports botocore) but before any boto3 clients are created,
# to ensure the X-Ray patching is applied correctly
# If the patching isn't applied, boto3 calls will fail with
# "AttributeError: 'UnpatchedBotocoreClient' object has no attribute 'meta'",
# because the X-Ray SDK replaces the standard botocore client
# with its own instrumented version that includes additional attributes for tracing.
# context_missing="LOG_ERROR" — outside Lambda (e.g. pytest), X-Ray calls
# log a warning instead of raising, so put_annotation() becomes a no-op
xray_recorder.configure(context_missing="LOG_ERROR")

s3 = boto3.client("s3", config=GENERAL_CONFIG)
sqs = boto3.client("sqs", config=GENERAL_CONFIG)
POISON_PILL_MARKER = "ECHO-POISON-PILL"


def handler(event, context):
    print(f"[ingest.handler] received event: {json.dumps(event)[:200]}")
    record = event["Records"][0]["s3"]
    bucket = record["bucket"]["name"]
    # S3 URL-encodes object keys in event payloads — decode before using as a boto3 key
    key = unquote_plus(record["object"]["key"])
    print(f"[ingest.handler] bucket={bucket}, key={key}")

    response = s3.get_object(Bucket=bucket, Key=key)
    # Body is a StreamingBody — .read() consumes it once to get raw bytes
    raw_bytes = response["Body"].read()
    # isoformat() converts datetime to ISO 8601 string so it's JSON-serializable
    received_at = response["LastModified"].isoformat()
    print(f"[ingest.handler] raw_bytes={len(raw_bytes)}B, received_at={received_at}")

    # rsplit on the last "/" only — handles keys with multiple path segments safely
    email_id = key.rsplit("/", 1)[-1]
    print(f"[ingest.handler] email_id={email_id}")

    # FR13 — X-Ray annotation for end-to-end trace correlation
    xray_recorder.put_annotation("email_id", email_id)

    parsed_email = parse_email(raw_bytes)
    print(f"[ingest.handler] parsed: from={parsed_email['from_address']}, subject={parsed_email['subject'][:50]}")

    payload = {
        "email_id": email_id,
        "from_address": parsed_email["from_address"],
        "subject": parsed_email["subject"],
        "body": parsed_email["body"],
        "raw_s3_key": key,
        "received_at": received_at,
    }

    # poison-pill demo (doc03 §4.5): omit body so Lambda #2 throws KeyError on every
    # redelivery, demonstrating the DLQ path — must delete before send_message
    if POISON_PILL_MARKER in parsed_email["subject"]:
        print(f"[ingest.handler] poison pill detected — omitting body from payload")
        del payload["body"]

    print(f"[ingest.handler] sending to SQS: email_id={email_id}, keys={list(payload.keys())}")
    sqs.send_message(
        QueueUrl=os.environ["TRIAGE_QUEUE_URL"], MessageBody=json.dumps(payload)
    )
