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
xray_recorder.configure(context_missing="LOG_ERROR")

s3 = boto3.client("s3", config=GENERAL_CONFIG)
sqs = boto3.client("sqs", config=GENERAL_CONFIG)
POISON_PILL_MARKER = "ECHO-POISON-PILL"


def handler(event, context):
    """
    Lambda handler for processing S3 events and sending messages to SQS.
    """
    print("recieved event:", event)
    # lamanda code starts here
    record = event["Records"][0]["s3"]

    bucket = record["bucket"]["name"]
    # S3 URL-encodes object keys in event payloads — decode before using as a boto3 key
    key = unquote_plus(record["object"]["key"])
    print(bucket, key)

    respone = s3.get_object(Bucket=bucket, Key=key)
    # Body is a streaming object, not raw bytes — .read() materializes it
    raw_bytes = respone["Body"].read()
    # isoformat() converts datetime to an ISO 8601 string so it's JSON-serializable
    received_at = respone["LastModified"].isoformat()
    print(raw_bytes[:80] + b"...", received_at)

    # rsplit on the last "/" only — handles keys with multiple path segments safely
    email_id = key.rsplit("/", 1)[-1]
    print(email_id)

    xray_recorder.put_annotation("email_id", email_id)

    parsed_email = parse_email(raw_bytes)
    print(parsed_email)

    payload = {
        "email_id": email_id,
        "from_address": parsed_email["from_address"],
        "subject": parsed_email["subject"],
        "body": parsed_email["body"],
        "raw_s3_key": key,
        "received_at": received_at,
    }
    print(payload)
    # must delete before send_message — the missing key is what triggers KeyError in Lambda #2
    if POISON_PILL_MARKER in parsed_email["subject"]:
        print(f"Poison pill found {POISON_PILL_MARKER}")
        del payload[
            "body"
        ]  # omit body from payload if poison pill — signals triage to skip NLP processing
    print("sending payload to SQS, with body omitted:", payload)
    sqs.send_message(
        QueueUrl=os.environ["TRIAGE_QUEUE_URL"], MessageBody=json.dumps(payload)
    )
