import json
import boto3
from retry_config import BEDROCK_CONFIG

# uses BEDROCK_CONFIG (read_timeout=10s) from the shared-utils layer (doc03 §4.2)
bedrock = boto3.client("bedrock-runtime", config=BEDROCK_CONFIG)

# pinned model ARN — never float to "latest" so a model swap can't silently change output schema
MODEL_ID = "anthropic.claude-3-haiku-20240307-v1:0"

# enum sets used by _validate — any value outside these triggers a retry
VALID_CATEGORIES = {
    "bug_report",
    "feature_request",
    "general_inquiry",
    "billing",
    "complaint",
    "praise",
}
VALID_URGENCY = {"high", "medium", "low"}
VALID_SENTIMENT = {"positive", "negative", "constructive"}
VALID_CONFIDENCE = {"high", "medium", "low"}

# feature_tags is excluded — it's defaulted to [] in _try_parse, not validated here
REQUIRED_FIELDS = {"category", "urgency", "sentiment", "confidence", "suggested_reply"}

SYSTEM_PROMPT = (
    "You are an email classifier. Given the body of an email, return ONLY a JSON object "
    "with exactly these fields:\n"
    '- "category": one of "bug_report", "feature_request", "general_inquiry", "billing", "complaint", "praise"\n'
    '- "urgency": one of "high", "medium", "low"\n'
    '- "sentiment": one of "positive", "negative", "constructive"\n'
    '- "confidence": one of "high", "medium", "low"\n'
    '- "suggested_reply": a short suggested reply string\n'
    '- "feature_tags": a list of short tags (only relevant for feature_request, otherwise [])\n'
    "Return ONLY the JSON object. No markdown, no explanation, no extra text."
)

# appended to SYSTEM_PROMPT on retry — tells the model its previous response was invalid
# so it self-corrects rather than repeating the same mistake
RETRY_SYSTEM_PROMPT = (
    SYSTEM_PROMPT
    + "\n\nYour previous response was not valid JSON matching this schema. "
    "Return ONLY the JSON object."
)

# FR17 fallback — returned when both invoke attempts fail to produce valid JSON
DEGRADED_RESULT = {
    "category": "unclassified",
    "urgency": "medium",
    "sentiment": "unknown",
    "confidence": "low",
    "suggested_reply": None,
    "feature_tags": [],
}


def _invoke(body_text: str, system_prompt: str, max_tokens: int) -> str:
    # Bedrock uses the Anthropic Messages format — body is a JSON string, not a dict
    response = bedrock.invoke_model(
        modelId=MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=json.dumps(
            {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": max_tokens,
                # temperature=0.0 — deterministic output for consistent classification
                "temperature": 0.0,
                "system": system_prompt,
                "messages": [{"role": "user", "content": body_text}],
            }
        ),
    )
    # first JSON decode: response["body"] is a StreamingBody (.read() consumes it once)
    # unwraps the Bedrock envelope to get the model's raw text output
    result = json.loads(response["body"].read())["content"][0]["text"]
    print(f"[classify._invoke] raw model response: {result}")
    return result


def _validate(parsed: dict) -> bool:
    # issubset allows extra keys (e.g. feature_tags) while ensuring all 5 required fields exist
    # short-circuits: if a key is missing, the enum checks below never run (avoids KeyError)
    return (
        REQUIRED_FIELDS.issubset(parsed.keys())
        and parsed["category"] in VALID_CATEGORIES
        and parsed["urgency"] in VALID_URGENCY
        and parsed["sentiment"] in VALID_SENTIMENT
        and parsed["confidence"] in VALID_CONFIDENCE
    )


def _try_parse(raw_text: str) -> dict | None:
    # second JSON decode — the model's text is itself a JSON string
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        print(f"[classify._try_parse] JSONDecodeError — raw text: {raw_text[:200]}")
        return None
    if not _validate(parsed):
        print(f"[classify._try_parse] validation failed — parsed: {parsed}")
        return None
    # feature_tags only matters for feature_request, but persist.py expects it to always exist
    parsed.setdefault("feature_tags", [])
    return parsed


def classify(body_text: str) -> dict:
    # Layer 2 retry (doc03 §4.3): attempt 1 → attempt 2 (corrective prompt) → degraded fallback
    print("[classify] attempt 1 — SYSTEM_PROMPT, max_tokens=512")
    parse_result = _try_parse(_invoke(body_text, SYSTEM_PROMPT, max_tokens=512))
    if parse_result is not None:
        print(f"[classify] attempt 1 succeeded: {parse_result}")
        return {**parse_result, "classification_failed": False}
    # retry with corrective prompt + larger max_tokens to guard against truncation (doc03 §8.7)
    print("[classify] attempt 1 failed — retrying with RETRY_SYSTEM_PROMPT, max_tokens=768")
    parse_result = _try_parse(_invoke(body_text, RETRY_SYSTEM_PROMPT, max_tokens=768))
    if parse_result is not None:
        print(f"[classify] attempt 2 succeeded: {parse_result}")
        return {**parse_result, "classification_failed": False}
    # FR17 degraded fallback — handler uses classification_failed to emit ClassificationFailure metric (DR7)
    print("[classify] both attempts failed — returning DEGRADED_RESULT")
    return {**DEGRADED_RESULT, "classification_failed": True}
