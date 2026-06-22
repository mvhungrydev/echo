import json
import pii
import classify
import keyword_rules
import persist
from aws_xray_sdk.core import xray_recorder

# context_missing="LOG_ERROR" — outside Lambda (pytest), X-Ray calls
# log a warning instead of raising, so put_annotation() becomes a no-op
xray_recorder.configure(context_missing="LOG_ERROR")


def handler(event, context):
    # step 1: parse SQS message (batch_size=1, so always one record)
    # body is a JSON string from Lambda #1's sqs.send_message(MessageBody=json.dumps(...))
    message = json.loads(event["Records"][0]["body"])
    print(f"[triage.handler] received email_id={message['email_id']}, subject={message['subject'][:50]}")

    # FR13 — X-Ray annotation for end-to-end trace correlation
    xray_recorder.put_annotation("email_id", message["email_id"])

    # step 2: idempotency check (§4.6) — skip all paid AI work if already processed
    existing = persist.get_existing_record(message["email_id"])
    if existing is not None:
        print(f"[triage.handler] email_id={message['email_id']} already processed — skipping")
        return
    print(f"[triage.handler] email_id={message['email_id']} is new — processing")

    # step 3: PII redaction — security gate, Bedrock never sees raw PII
    pii_result = pii.redact_pii(message["body"])
    print(f"[triage.handler] PII redaction done: {pii_result['pii_entities_detected']} entities redacted")

    # step 4: classification via Bedrock — uses redacted text, not raw body
    classification = classify.classify(pii_result["redacted_text"])
    print(f"[triage.handler] classification: category={classification['category']}, urgency={classification['urgency']}, confidence={classification['confidence']}, failed={classification['classification_failed']}")

    # step 5: keyword override — checks subject + redacted body for escalation phrases
    keyword_input = message["subject"] + " " + pii_result["redacted_text"]
    override = keyword_rules.apply_keyword_override(keyword_input, classification["urgency"])
    print(f"[triage.handler] keyword override: urgency={override['urgency']}, applied={override['urgency_override_applied']}")

    # step 6: determine review_status — "needs_review" if low confidence or classification failed
    if classification["confidence"] != "high" or classification["classification_failed"]:
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
