import os
import sys
import pytest
import boto3
from moto import mock_aws


@pytest.fixture
def aws_credentials(monkeypatch):
    """Mocked AWS Credentials for moto."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


@pytest.fixture
def ingest_handler(aws_credentials, monkeypatch):
    with mock_aws():
        # Set up any necessary AWS resources here, e.g., S3 buckets, DynamoDB tables, etc.
        # For example, if you need to create an S3 bucket:
        s3 = boto3.client("s3")
        s3.create_bucket(
            Bucket="echo-raw-emails",
        )
        sqs = boto3.client("sqs")
        sqs_queue_url = sqs.create_queue(QueueName="echo-triage-queue")["QueueUrl"]
        monkeypatch.setenv("TRIAGE_QUEUE_URL", sqs_queue_url)
        sys.modules.pop(
            "handler", None
        )  # Ensure the handler module is reloaded with the mocked AWS environment
        # Import the handler after setting up the mock environment
        monkeypatch.syspath_prepend(
            os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "src", "lambda_ingest")
            )
        )
        import handler

        yield handler
