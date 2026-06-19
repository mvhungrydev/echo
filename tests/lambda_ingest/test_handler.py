# %%
import json
import os
import sys
from unittest.mock import patch
import boto3
from email.message import EmailMessage
from moto import mock_aws
from urllib.parse import unquote_plus

BUCKET = "echo-raw-emails"
# absolute path so the insert works regardless of where pytest is invoked from
LAMBDA_SRC = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "src", "lambda_ingest")
)
# retry_config lives in the Lambda layer, not alongside handler.py — needs its own path entry
SHARED_UTILS = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "src", "layers", "shared_utils")
)

# moto requires fake credentials before any boto3 client is created;
# these values are arbitrary — moto never validates them against real AWS
os.environ["AWS_ACCESS_KEY_ID"] = "testing"
os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"


def build_eml(
    from_addr="Jane Doe <jane@example.com>",
    subject="Test Email",
    body="This is a test email.",
):
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["Subject"] = subject
    msg.set_content(body)
    return msg


def _setup():
    """Create mock S3/SQS resources and import handler against the mock backend."""
    s3 = boto3.client("s3")
    s3.create_bucket(Bucket=BUCKET)

    sqs = boto3.client("sqs")
    queue_url = sqs.create_queue(QueueName="echo-triage-queue")["QueueUrl"]
    os.environ["TRIAGE_QUEUE_URL"] = queue_url

    # evict cached module so the re-import binds to the current mock backend,
    # not a stale client from a previous test's mock context
    sys.modules.pop("handler", None)
    if LAMBDA_SRC not in sys.path:
        sys.path.insert(0, LAMBDA_SRC)
    # shared_utils is a Lambda layer — not co-located with handler.py,
    # so it must be added separately for local test resolution
    if SHARED_UTILS not in sys.path:
        sys.path.insert(0, SHARED_UTILS)

    import handler

    return s3, sqs, queue_url, handler


# %%


def local_handler(event, context, s3, sqs, queue_url):
    from mime_parser import parse_email

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

    POISON_PILL_MARKER = "ECHO-POISON-PILL"
    # must delete before send_message — the missing key is what triggers KeyError in Lambda #2
    if POISON_PILL_MARKER in parsed_email["subject"]:
        del payload[
            "body"
        ]  # omit body from payload if poison pill — signals triage to skip NLP processing

    sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps(payload))


# %%
# ── test 1 ────────────────────────────────────────────────────────────────────


def test_happy_path_plain_text_email():
    # mock_aws must wrap _setup() so handler.py's module-level boto3 clients
    # bind to the mock backend, not real AWS
    mock = mock_aws()
    mock.start()
    s3, sqs, queue_url, handler = _setup()

    key = "raw-emails/test-msg-001"
    # as_bytes() serializes the EmailMessage to raw MIME bytes —
    # matches exactly what SES stores in S3 after receiving a real email
    s3.put_object(Bucket=BUCKET, Key=key, Body=build_eml().as_bytes())

    # S3 always wraps its trigger payload in a Records list, even for single objects
    event = {"Records": [{"s3": {"bucket": {"name": BUCKET}, "object": {"key": key}}}]}
    # Setup ends here
    #

    # Test local handler in isolation first — avoids Lambda-specific layers of complexity while verifying core logic
    local_handler(event, None, s3, sqs, queue_url)
    # End of local handler test — now replicate the full Lambda invocation to verify the final SQS payload

    # Real Lambda invocation would have the handler read from SQS after processing the S3 event;
    # replicate that here to verify the final SQS payload
    handler.handler(event, None)

    response = sqs.receive_message(QueueUrl=queue_url)
    # SQS returns Body as a raw JSON string, not a dict — must deserialize
    payload = json.loads(response["Messages"][0]["Body"])

    assert payload["email_id"] == "test-msg-001"
    assert payload["from_address"] == "jane@example.com"
    assert payload["subject"] == "Test Email"
    assert payload["body"] == "This is a test email.\n"
    assert payload["raw_s3_key"] == key
    # can't assert exact timestamp — just verify the field was populated
    assert payload["received_at"] != ""
    mock.stop()


# %% develop test 1 interactively
# with mock_aws():
#     s3, sqs, queue_url, handler = _setup()
#     key = "raw-emails/test-msg-001"
#     s3.put_object(Bucket=BUCKET, Key=key, Body=build_eml().as_bytes())
#     event = {"Records": [{"s3": {"bucket": {"name": BUCKET}, "object": {"key": key}}}]}
#     handler.handler(event, None)
#     response = sqs.receive_message(QueueUrl=queue_url)
#     payload = json.loads(response["Messages"][0]["Body"])
#     print(payload)


# ── test 2 ────────────────────────────────────────────────────────────────────


def test_email_id_derived_from_s3_key():
    with mock_aws():
        s3, sqs, queue_url, handler = _setup()
        # S3 key = "raw-emails/<msgid>" -> payload["email_id"] == "<msgid>"
        pass


# ── test 3 ────────────────────────────────────────────────────────────────────


def test_url_encoded_s3_key_resolved():
    with mock_aws():
        s3, sqs, queue_url, handler = _setup()
        # S3 key contains URL-encoded chars (e.g. %20 / +)
        # handler must still fetch the object and derive the correct email_id
        pass


# ── test 4 ────────────────────────────────────────────────────────────────────


def test_received_at_from_last_modified():
    with mock_aws():
        s3, sqs, queue_url, handler = _setup()
        # payload["received_at"] == s3.get_object()["LastModified"].isoformat()
        pass


# ── test 5 ────────────────────────────────────────────────────────────────────


def test_poison_pill_omits_body_key():
    with mock_aws():
        s3, sqs, queue_url, handler = _setup()
        # Subject contains POISON_PILL_MARKER -> "body" key is absent from SQS payload
        pass


# ── test 6 ────────────────────────────────────────────────────────────────────


def test_multipart_email_body_extracted():
    with mock_aws():
        s3, sqs, queue_url, handler = _setup()
        # Upload a multipart/alternative .eml -> payload["body"] matches parse_email output
        pass


# ── test 7 ────────────────────────────────────────────────────────────────────


def test_sqs_message_json_serializable():
    with mock_aws():
        s3, sqs, queue_url, handler = _setup()
        # SQS MessageBody round-trips through json.loads() without error
        pass


# ── test 8 ────────────────────────────────────────────────────────────────────


def test_xray_annotation_called_with_email_id():
    with mock_aws():
        s3, sqs, queue_url, handler = _setup()
        # patch xray_recorder.put_annotation, invoke handler
        # assert it was called with ("email_id", "<msgid>")
        pass
