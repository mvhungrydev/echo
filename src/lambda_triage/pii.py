import boto3
from retry_config import GENERAL_CONFIG

# uses GENERAL_CONFIG (read_timeout=5s) from the shared-utils layer (doc03 §4.2)
comprehend = boto3.client("comprehend", config=GENERAL_CONFIG)

# entities below this confidence score are likely false positives — not worth redacting
PII_SCORE_THRESHOLD = 0.5
# NAME/EMAIL/PHONE are preserved: names and emails aid human review;
# phone numbers are contact details the support agent needs to follow up
PII_TYPES_TO_SKIP = {"NAME", "EMAIL", "PHONE"}


def redact_pii(text: str) -> dict:
    response = comprehend.detect_pii_entities(Text=text, LanguageCode="en")
    print(f"[pii.redact_pii] Comprehend returned {len(response['Entities'])} raw entities")
    # two gates: drop low-confidence detections AND skip types we intentionally preserve
    entities = [
        e
        for e in response["Entities"]
        if e["Score"] >= PII_SCORE_THRESHOLD and e["Type"] not in PII_TYPES_TO_SKIP
    ]
    # Comprehend doesn't guarantee BeginOffset order — sort ascending so the
    # single left-to-right pass never needs to backtrack
    entities.sort(key=lambda e: e["BeginOffset"])
    print(f"[pii.redact_pii] {len(entities)} entities after filtering (threshold={PII_SCORE_THRESHOLD}, skipping {PII_TYPES_TO_SKIP})")

    parts = []
    cursor = 0  # tracks how far into the original string we've consumed
    for entity in entities:
        # copy the literal text between the previous entity (or string start) and this one
        parts.append(text[cursor : entity["BeginOffset"]])
        # substitute the entity's text span with its type label (e.g. "123-45-6789" → "[SSN]")
        parts.append(f"[{entity['Type']}]")
        # jump past the entity span; offsets reference the original string so no shifting needed
        cursor = entity["EndOffset"]
    parts.append(text[cursor:])  # append everything after the last entity

    redacted_text = "".join(parts)
    print(f"[pii.redact_pii] redacted {len(entities)} entities, output_len={len(redacted_text)}")
    return {
        "redacted_text": redacted_text,
        "pii_entities_detected": len(entities),
    }