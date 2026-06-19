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
