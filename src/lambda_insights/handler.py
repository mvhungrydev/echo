# %% ── mock setup — run this cell first ─────────────────────────────────────
import io
import os
import sys
from unittest.mock import MagicMock

import boto3
from moto import mock_aws

os.environ["AWS_ACCESS_KEY_ID"] = "testing"
os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
os.environ["DYNAMODB_TABLE_NAME"] = "EmailTriageResults-dev"

# shared_utils must be on sys.path before retry_config is imported below
sys.path.insert(0, os.path.join(os.getcwd(), "src", "layers", "shared_utils"))

# start moto before any boto3 clients are created — order matters
_mock = mock_aws()
_mock.start()
print("moto started")

# %% ── imports + module-level AWS clients ────────────────────────────────────
import json

from boto3.dynamodb.conditions import Attr
from botocore.config import Config
from retry_config import GENERAL_CONFIG

dynamodb = boto3.resource("dynamodb", config=GENERAL_CONFIG)
table = dynamodb.Table(os.environ["DYNAMODB_TABLE_NAME"])

INSIGHTS_BEDROCK_CONFIG = Config(
    retries={"max_attempts": 2, "mode": "adaptive"},
    connect_timeout=3,
    read_timeout=5,
)
bedrock = boto3.client("bedrock-runtime", config=INSIGHTS_BEDROCK_CONFIG)
MODEL_ID = "anthropic.claude-3-haiku-20240307-v1:0"

# %% ── constants ──────────────────────────────────────────────────────────────
QUERY_TOOL = {
    "name": "query_triage_data",
    "description": (
        "Query the email triage database. Returns records matching the given filters. "
        "All filters are optional; omit a filter to match all values for that field. "
        "You may call this tool multiple times with different filters to compare subsets."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "enum": [
                    "bug_report",
                    "feature_request",
                    "general_inquiry",
                    "billing",
                    "complaint",
                    "praise",
                ],
                "description": "Filter by email category",
            },
            "sentiment": {
                "type": "string",
                "enum": ["positive", "negative", "constructive"],
                "description": "Filter by sentiment",
            },
            "urgency": {
                "type": "string",
                "enum": ["high", "medium", "low"],
                "description": "Filter by urgency level",
            },
            "from_address": {
                "type": "string",
                "description": "Filter by sender email address (exact match)",
            },
            "date_from": {
                "type": "string",
                "description": "ISO 8601 date — return records received on or after this date",
            },
            "date_to": {
                "type": "string",
                "description": "ISO 8601 date — return records received on or before this date",
            },
        },
        "required": [],
    },
}

MAX_TOOL_TURNS = 3

SYSTEM_PROMPT = (
    "You are a data analyst with access to an email triage database. "
    "Use the query_triage_data tool to fetch the records you need to answer the user's question. "
    "You may call the tool multiple times with different filters. "
    'After gathering data, return ONLY a JSON object: {"answer": "<your concise response>"}. '
    "No markdown, no extra keys."
)

RETRY_SYSTEM_PROMPT = (
    "You are a data analyst with access to an email triage database. "
    "Use the query_triage_data tool to fetch the records you need to answer the user's question. "
    "Your previous response was not valid JSON. "
    'After gathering data, return ONLY a JSON object: {"answer": "<your response>"}. '
    "No explanation, no markdown, no extra text."
)

# %% ── fake DynamoDB table + seed data + bedrock mock ────────────────────────
dynamodb.create_table(
    TableName="EmailTriageResults-dev",
    KeySchema=[{"AttributeName": "email_id", "KeyType": "HASH"}],
    AttributeDefinitions=[{"AttributeName": "email_id", "AttributeType": "S"}],
    BillingMode="PAY_PER_REQUEST",
)
table.put_item(
    Item={
        "email_id": "msg-001",
        "category": "billing",
        "sentiment": "negative",
        "urgency": "high",
        "from_address": "jane@example.com",
        "subject": "Overcharged",
        "redacted_body": "I was charged twice.",
        "feature_tags": [],
        "received_at": "2026-06-21T10:00:00+00:00",
        "review_status": "auto_processed",
        "raw_s3_key": "raw-emails/msg-001",
        "confidence": "high",
        "suggested_reply": "We'll look into it.",
        "pii_entities_detected": 0,
        "processed_at": "2026-06-21T10:00:05+00:00",
        "ttl": 1758466200,
        "urgency_override_applied": False,
    }
)

# moto does not support bedrock-runtime — patch invoke_model directly
# side_effect: first call → tool_use, second call → end_turn
_fake_tool_response = {
    "body": io.BytesIO(
        json.dumps(
            {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_001",
                        "name": "query_triage_data",
                        "input": {"category": "billing"},
                    }
                ],
                "stop_reason": "tool_use",
            }
        ).encode()
    )
}
_fake_end_response = {
    "body": io.BytesIO(
        json.dumps(
            {
                "content": [
                    {"type": "text", "text": '{"answer": "There was 1 billing email."}'}
                ],
                "stop_reason": "end_turn",
            }
        ).encode()
    )
}
bedrock.invoke_model = MagicMock(side_effect=[_fake_tool_response, _fake_end_response])
print("fake table seeded, bedrock patched")

# %% ── fake inputs ────────────────────────────────────────────────────────────
event = {
    "body": '{"question": "How many high urgency billing emails did we receive this week?"}'
}


# %% ── handler ────────────────────────────────────────────────────────────────
def lambda_handler(event: dict) -> dict:
    # step 1 — parse event: json.loads(event["body"]) → extract "question"
    question = (json.loads(event["body"]))["question"]
    print(f"[step 1] question: {question}")
    # step 2 — outer retry loop over (SYSTEM_PROMPT, RETRY_SYSTEM_PROMPT) — 2 attempts

    for attempt, prompt in enumerate((SYSTEM_PROMPT, RETRY_SYSTEM_PROMPT)):
        print(
            f"[step 2] attempt {attempt + 1}, prompt: {'SYSTEM_PROMPT' if attempt == 0 else 'RETRY_SYSTEM_PROMPT'}"
        )
        messages = [{"role": "user", "content": question}]
        records_considered = 0
        print(
            f"[step 3] messages: {messages} | records_considered: {records_considered}"
        )
        for turn in range(MAX_TOOL_TURNS):
            print(f"[step 4] tool turn {turn + 1}")
            bedrock_response = bedrock.invoke_model(
                modelId=MODEL_ID,
                body=json.dumps(
                    {
                        "anthropic_version": "bedrock-2023-05-31",
                        "system": prompt,
                        "messages": messages,
                        "tools": [QUERY_TOOL],
                        "temperature": 0.3,
                        "max_tokens": 1024,
                    }
                ),
            )
            response_body = json.loads(bedrock_response["body"].read())
            stop_reason = response_body["stop_reason"]
            content = response_body["content"]
            print(
                f"[step 5] stop_reason: {stop_reason} | content blocks: {len(content)}"
            )
            if stop_reason == "end_turn":
                raw_txt = next(
                    (b["text"] for b in content if b["type"] == "text"), None
                )
                print(f"[step 6] raw_txt: {raw_txt}")
                if raw_txt is not None:
                    try:
                        parsed_raw_txt = json.loads(raw_txt)
                        if "answer" in parsed_raw_txt and isinstance(
                            parsed_raw_txt["answer"], str
                        ):
                            print(f"[step 6] valid answer: {parsed_raw_txt['answer']}")
                            return {
                                "statusCode": 200,
                                "body": json.dumps(parsed_raw_txt),
                            }
                    except json.JSONDecodeError:
                        print(
                            "[step 6] json.JSONDecodeError — invalid answer, breaking to retry"
                        )
                        pass
                print("[step 6] breaking to retry")
                break
            # step 7 — if stop_reason == "tool_use":
            #           find all blocks where type == "tool_use"
            #           for each block:
            #             a. pull tool_input = block["input"]
            #             b. build base filter: Attr("review_status").eq("auto_processed")
            #             c. layer optional filters via & for each key in tool_input:
            #                category, sentiment, urgency, from_address, date_from, date_to
            #             d. build scan_kwargs with FilterExpression + 9-field ProjectionExpression
            #             e. pagination loop: table.scan(), extend records, check LastEvaluatedKey
            #             f. accumulate records_considered += len(records)
            #             f. accumulate records_considered += len(records)
            #           append assistant message + tool_result user message → continue inner loop

            # step 8 — inner loop exhausted without end_turn → fall to retry

        # step 9 — both attempts failed:
        #           return {"statusCode": 500,
        #                   "body": json.dumps({"answer": None, "synthesis_failed": True})}
    pass


# %%
