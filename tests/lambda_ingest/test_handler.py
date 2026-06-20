# %%
import json
import os
import sys
import boto3
from email.message import EmailMessage
from moto import mock_aws
from urllib.parse import unquote_plus
from unittest.mock import patch, MagicMock

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
    body="This is a test email % @.(printable ASCII chars) \n",
    html_body=None,
):
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["Subject"] = subject
    msg.set_content(body)
    if html_body:
        msg.add_alternative(html_body, subtype="html")
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
    from aws_xray_sdk.core import xray_recorder

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

    POISON_PILL_MARKER = "ECHO-POISON-PILL"
    # must delete before send_message — the missing key is what triggers KeyError in Lambda #2
    if POISON_PILL_MARKER in parsed_email["subject"]:
        del payload[
            "body"
        ]  # omit body from payload if poison pill — signals triage to skip NLP processing
    print("sending payload to SQS, with body omitted:", payload)
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
    assert payload["body"] == "This is a test email % @.(printable ASCII chars) \n"
    assert payload["raw_s3_key"] == key
    # can't assert exact timestamp — just verify the field was populated
    assert payload["received_at"] != ""
    mock.stop()


# %%
# ── test 2 ────────────────────────────────────────────────────────────────────
def test_email_id_derived_from_s3_key():
    print("Running test_email_id_derived_from_s3_key...")
    mock = mock_aws()
    mock.start()
    print("test setup starting")
    s3, sqs, queue_url, handler = _setup()
    # S3 key can have multiple path segments, but email_id is always the final segment after the last "/"
    key = "raw-emails/2024/06/test-msg-002"
    s3.put_object(
        Bucket=BUCKET,
        Key=key,
        Body=build_eml().as_bytes(),
    )
    event = {"Records": [{"s3": {"bucket": {"name": BUCKET}, "object": {"key": key}}}]}

    print("S3 object uploaded with key:", key)
    # The email_id should be derived from the final segment of the S3 key
    print("test setup complete, invoking handler...")

    # Test local handler in isolation first — avoids Lambda-specific layers of complexity while verifying core logic
    local_handler(event, None, s3, sqs, queue_url)
    # End of local handler test — now replicate the full Lambda invocation to verify the final SQS payload

    # Real Lambda invocation would have the handler read from SQS after processing the S3 event;
    # replicate that here to verify the final SQS payload
    handler.handler(event, None)

    response = sqs.receive_message(QueueUrl=queue_url)
    print("Received SQS message:", response)
    # SQS returns Body as a raw JSON string, not a dict — must deserialize
    payload = json.loads(response["Messages"][0]["Body"])
    assert payload["email_id"] == "test-msg-002"
    mock.stop()


# %%
# ── test 3 ────────────────────────────────────────────────────────────────────
def test_url_encoded_s3_key_resolved():
    print("Running test_url_encoded_s3_key_resolved...")
    mock = mock_aws()
    mock.start()
    print("test setup starting")
    s3, sqs, queue_url, handler = _setup()
    s3.put_object(
        Bucket=BUCKET,
        Key="raw-emails/test msg 003",  # S3 key
        Body=build_eml().as_bytes(),
    )
    event = {
        "Records": [
            {
                "s3": {
                    "bucket": {"name": BUCKET},
                    "object": {"key": "raw-emails/test%20msg%20003"},
                }
            }
        ]
    }

    # S3 key contains URL-encoded chars (e.g. %20 / +)
    # handler must still fetch the object and derive the correct email_id
    print("test setup complete, invoking handler...")

    # Test local handler in isolation first — avoids Lambda-specific layers of complexity while verifying core logic
    local_handler(event, None, s3, sqs, queue_url)
    # End of local handler test — now replicate the full Lambda invocation to verify the final S

    # Real Lambda invocation would have the handler read from SQS after processing the S3 event;
    # replicate that here to verify the final SQS payload
    handler.handler(event, None)

    response = sqs.receive_message(QueueUrl=queue_url)
    print("Received SQS message:", response)
    # SQS returns Body as a raw JSON string, not a dict — must deserialize
    payload = json.loads(response["Messages"][0]["Body"])
    assert payload["email_id"] == "test msg 003"
    mock.stop()


# %%
# ── test 4 ────────────────────────────────────────────────────────────────────
def test_received_at_from_last_modified():
    mock = mock_aws()
    mock.start()
    s3, sqs, queue_url, handler = _setup()
    s3.put_object(
        Bucket=BUCKET,
        Key="raw-emails/test-msg-004",
        Body=build_eml().as_bytes(),
    )
    event = {
        "Records": [
            {
                "s3": {
                    "bucket": {"name": BUCKET},
                    "object": {"key": "raw-emails/test-msg-004"},
                }
            }
        ]
    }
    # handler should populate payload["received_at"] with the S3 object's LastModified timestamp in ISO 8601 format
    local_handler(event, None, s3, sqs, queue_url)
    # Real Lambda invocation would have the handler read from SQS after processing the S3 event;
    # The handler should populate payload["received_at"] with the S3 object's LastModified timestamp in ISO 8601 format
    handler.handler(event, None)
    response = sqs.receive_message(QueueUrl=queue_url)
    payload = json.loads(response["Messages"][0]["Body"])
    print("Received SQS message with payload:", payload)
    assert (
        payload["received_at"]
        == s3.get_object(Bucket=BUCKET, Key="raw-emails/test-msg-004")[
            "LastModified"
        ].isoformat()
    )
    mock.stop()


# %%
# ── test 5 ────────────────────────────────────────────────────────────────────
def test_poison_pill_omits_body_key():
    mock = mock_aws()
    mock.start()
    s3, sqs, queue_url, handler = _setup()
    s3.put_object(
        Bucket=BUCKET,
        Key="raw-emails/test-msg-005",
        Body=build_eml(subject="This email contains ECHO-POISON-PILL").as_bytes(),
    )
    event = {
        "Records": [
            {
                "s3": {
                    "bucket": {"name": BUCKET},
                    "object": {"key": "raw-emails/test-msg-005"},
                }
            }
        ]
    }
    # local test
    local_handler(event, None, s3, sqs, queue_url)

    # Real Lambda invocation would have the handler read from SQS after processing the S3 event;
    handler.handler(event, None)
    response = sqs.receive_message(QueueUrl=queue_url)
    payload = json.loads(response["Messages"][0]["Body"])
    print("Received SQS message with payload:", payload)

    assert payload["email_id"] == "test-msg-005"
    assert payload["subject"] == "This email contains ECHO-POISON-PILL"
    assert (
        "body" not in payload
    )  # poison pill marker in subject should trigger body omission
    # Subject contains POISON_PILL_MARKER -> "body" key is absent from SQS payload
    mock.stop()


# %%

# ── test 6 ────────────────────────────────────────────────────────────────────


def test_multipart_email_body_extracted():
    mock = mock_aws()
    mock.start()
    s3, sqs, queue_url, handler = _setup()
    s3.put_object(
        Bucket=BUCKET,
        Key="raw-emails/test-msg-006",
        Body=build_eml(
            html_body="<p>This is the HTML part of the email.</p>"
        ).as_bytes(),
    )
    event = {
        "Records": [
            {
                "s3": {
                    "bucket": {"name": BUCKET},
                    "object": {"key": "raw-emails/test-msg-006"},
                }
            }
        ]
    }
    # Test local handler in isolation first — avoids Lambda-specific layers of complexity while verifying core logic
    local_handler(event, None, s3, sqs, queue_url)
    # End of local handler test — now replicate the full Lambda invocation to verify the final SQS payload
    handler.handler(event, None)
    response = sqs.receive_message(QueueUrl=queue_url)
    payload = json.loads(response["Messages"][0]["Body"])
    mock.stop()

    # multipart email with both text/plain and text/html parts
    # handler should extract the text/plain part as the "body" in the SQS payload
    assert payload["body"] == "This is a test email % @.(printable ASCII chars) \n"


# ── test 7 ────────────────────────────────────────────────────────────────────


# %%
def test_sqs_message_json_serializable():
    mock = mock_aws()
    mock.start()
    s3, sqs, queue_url, handler = _setup()
    s3.put_object(
        Bucket=BUCKET,
        Key="raw-emails/test-msg-007",
        Body=build_eml().as_bytes(),
    )
    event = {
        "Records": [
            {
                "s3": {
                    "bucket": {"name": BUCKET},
                    "object": {"key": "raw-emails/test-msg-007"},
                }
            }
        ]
    }

    # Test local handler in isolation first — avoids Lambda-specific layers of complexity while verifying core logic
    local_handler(event, None, s3, sqs, queue_url)

    # End of local handler test — now replicate the full Lambda invocation to verify the final SQS payload
    handler.handler(event, None)

    response = sqs.receive_message(QueueUrl=queue_url)
    print("Received SQS message:", response)
    payload = json.loads(response["Messages"][0]["Body"])
    assert isinstance(payload, dict)
    mock.stop()


# %%
# ── test 8 ────────────────────────────────────────────────────────────────────
def test_xray_annotation_called_with_email_id():
    mock = mock_aws()
    mock.start()
    s3, sqs, queue_url, handler = _setup()

    s3.put_object(
        Bucket=BUCKET,
        Key="raw-emails/test-msg-008",
        Body=build_eml(
            html_body="<p>This is the HTML part of the email.</p>"
        ).as_bytes(),
    )

    # patch the method on the singleton object — affects all references including local_handler's
    # import; patching "handler.xray_recorder" would only intercept handler.py's namespace
    # put_annotation() requires an active X-Ray segment — the Lambda runtime
    # provides one in production but not in tests. Patching replaces it with a
    # MagicMock that accepts calls without a segment and records them for assertion.
    with patch(
        "aws_xray_sdk.core.xray_recorder.put_annotation", new_callable=MagicMock
    ) as mock_put_annotation:
        event = {
            "Records": [
                {
                    "s3": {
                        "bucket": {"name": BUCKET},
                        "object": {"key": "raw-emails/test-msg-008"},
                    }
                }
            ]
        }
        local_handler(event, None, s3, sqs, queue_url)

        handler.handler(event, None)
        # assert_called_with checks the LAST call — sufficient here since only one annotation is made
        mock_put_annotation.assert_called_with("email_id", "test-msg-008")

    mock.stop()


# %%
