import json
import os
import time
import boto3
import pii
import classify
import keyword_rules
import persist
from retry_config import GENERAL_CONFIG
from aws_xray_sdk.core import xray_recorder

# context_missing="LOG_ERROR" — outside Lambda (pytest), X-Ray calls
# log a warning instead of raising, so put_annotation() becomes a no-op
xray_recorder.configure(context_missing="LOG_ERROR")

sns = boto3.client("sns", config=GENERAL_CONFIG)


def _alert_type(record: dict) -> str:
    # precedence: urgent > needs_review > informational (doc03 §7.1)
    # an email can be both urgent AND needs_review — urgent wins
    if record["urgency"] == "high":
        print(f"[triage._alert_type] urgency=high -> urgent")
        return "urgent"
    if record["review_status"] == "needs_review":
        print(f"[triage._alert_type] review_status=needs_review -> needs_review")
        return "needs_review"
    print(f"[triage._alert_type] no escalation -> informational")
    return "informational"


def _build_alert_body(record: dict, alert_type: str) -> dict:
    # common fields shared by all 3 shapes
    body = {
        "email_id": record["email_id"],
        "alert_type": alert_type,
        "received_at": record["received_at"],
        "category": record["category"],
        "urgency": record["urgency"],
        "confidence": record["confidence"],
        "sentiment": record["sentiment"],
        "from_address": record["from_address"],
        "subject": record["subject"],
        "suggested_reply": record["suggested_reply"],
    }
    if alert_type == "urgent":
        # full context for immediate action — includes urgency_override_applied
        body.update(
            {
                "urgency_override_applied": record["urgency_override_applied"],
            }
        )
    elif alert_type == "needs_review":
        # "unclassified" only comes from DEGRADED_RESULT — model never returns it
        review_reason = (
            "classification_failed"
            if record["category"] == "unclassified"
            else "low_confidence"
        )
        body.update(
            {
                "review_reason": review_reason,
            }
        )
    print(f"[triage._build_alert_body] alert_type={alert_type}, keys={list(body.keys())}")
    return body


def _emit_emf(
    record: dict, classification_failed: bool, alert_publish_failed: bool
) -> None:
    # prints one JSON line to stdout — CloudWatch EMF processor parses it into custom metrics
    # no PutMetricData IAM needed — CloudWatch Logs parses the EMF doc automatically
    metrics = [
        {"Name": "SentimentCount", "Unit": "Count"},
        {"Name": "PiiEntitiesDetected", "Unit": "Count"},
    ]
    # top-level keys must match Metrics names — EMF maps them by name
    values = {
        "sentiment": record["sentiment"],
        "SentimentCount": 1,
        "PiiEntitiesDetected": record["pii_entities_detected"],
    }
    if classification_failed:
        metrics.append({"Name": "ClassificationFailure", "Unit": "Count"})
        values["ClassificationFailure"] = 1
    if alert_publish_failed:
        metrics.append({"Name": "AlertPublishFailure", "Unit": "Count"})
        values["AlertPublishFailure"] = 1

    emf_doc = {
        "_aws": {
            # EMF requires epoch milliseconds, not seconds
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [{
                "Namespace": "ECHO",
                # metrics grouped by sentiment value (positive/negative/constructive)
                "Dimensions": [["sentiment"]],
                "Metrics": metrics,
            }],
        },
        **values,
    }
    print(f"[triage._emit_emf] metrics={[m['Name'] for m in metrics]}, sentiment={record['sentiment']}")
    # this print IS the metric — CloudWatch Logs EMF processor reads it from stdout
    print(json.dumps(emf_doc))


def handler(event, context):
    # step 1: parse SQS message (batch_size=1, so always one record)
    # body is a JSON string from Lambda #1's sqs.send_message(MessageBody=json.dumps(...))
    message = json.loads(event["Records"][0]["body"])
    print(
        f"[triage.handler] received email_id={message['email_id']}, subject={message['subject'][:50]}"
    )

    # FR13 — X-Ray annotation for end-to-end trace correlation
    xray_recorder.put_annotation("email_id", message["email_id"])

    # step 2: idempotency check (§4.6) — skip all paid AI work if already processed
    existing = persist.get_existing_record(message["email_id"])
    if existing is not None:
        print(
            f"[triage.handler] email_id={message['email_id']} already processed — skipping"
        )
        return
    print(f"[triage.handler] email_id={message['email_id']} is new — processing")

    # step 3: PII redaction — security gate, Bedrock never sees raw PII
    pii_result = pii.redact_pii(message["body"])
    print(
        f"[triage.handler] PII redaction done: {pii_result['pii_entities_detected']} entities redacted"
    )

    # step 4: classification via Bedrock — uses redacted text, not raw body
    classification = classify.classify(pii_result["redacted_text"])
    print(
        f"[triage.handler] classification: category={classification['category']}, urgency={classification['urgency']}, confidence={classification['confidence']}, failed={classification['classification_failed']}"
    )

    # step 5: keyword override — checks subject + redacted body for escalation phrases
    keyword_input = message["subject"] + " " + pii_result["redacted_text"]
    override = keyword_rules.apply_keyword_override(
        keyword_input, classification["urgency"]
    )
    print(
        f"[triage.handler] keyword override: urgency={override['urgency']}, applied={override['urgency_override_applied']}"
    )

    # step 6: determine review_status — "needs_review" if low confidence or classification failed
    if (
        classification["confidence"] != "high"
        or classification["classification_failed"]
    ):
        review_status = "needs_review"
    else:
        review_status = "auto_processed"
    print(f"[triage.handler] review_status={review_status}")

    # step 7: build the 15-field triage record
    # 5 from message, 5 from classification, 2 from override, 1 computed, 2 from pii_result
    record = {
        "email_id": message["email_id"],
        "received_at": message["received_at"],
        "from_address": message["from_address"],
        "subject": message["subject"],
        "raw_s3_key": message["raw_s3_key"],
        "category": classification["category"],
        "sentiment": classification["sentiment"],
        "confidence": classification["confidence"],
        "suggested_reply": classification["suggested_reply"],
        "feature_tags": classification["feature_tags"],
        "urgency": override["urgency"],
        "urgency_override_applied": override["urgency_override_applied"],
        "review_status": review_status,
        "pii_entities_detected": pii_result["pii_entities_detected"],
        "redacted_body": pii_result["redacted_text"],
    }

    # step 8: persist to DynamoDB — put_triage_record adds processed_at + ttl internally
    print(f"[triage.handler] persisting record for email_id={message['email_id']}")
    persist.put_triage_record(record)

    # step 9: determine alert type
    alert_type = _alert_type(record)

    # step 10: build alert body
    alert_body = _build_alert_body(record, alert_type)

    # step 11: publish to SNS — DEGRADE on failure (don't re-raise, persist already succeeded)
    # re-raising would cause SQS redelivery, re-running Comprehend + Bedrock just to retry a notification
    alert_publish_failed = False
    try:
        sns.publish(
            TopicArn=os.environ["ALERT_TOPIC_ARN"],
            Message=json.dumps(alert_body),
            # subscribers use filter policies on this attribute to split urgent vs needs_review
            MessageAttributes={
                "alert_type": {"DataType": "String", "StringValue": alert_type}
            },
        )
        print(f"[triage.handler] SNS published: alert_type={alert_type}")
    except Exception:
        alert_publish_failed = True
        print(f"[triage.handler] SNS publish FAILED — degrading, not re-raising")

    # step 12: emit EMF metrics — always runs, includes conditional failure metrics
    _emit_emf(record, classification["classification_failed"], alert_publish_failed)
