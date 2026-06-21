# %%
import os
import sys
from unittest.mock import patch

# sys.path inserts must come before importing pii — Python resolves module paths
# at import time, so the lambda_triage and shared_utils directories must already
# be on sys.path when `import pii` runs
sys.path.insert(
    0,
    os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "src", "lambda_triage")
    ),
)
sys.path.insert(
    0,
    os.path.abspath(
        os.path.join(
            os.path.dirname(__file__), "..", "..", "src", "layers", "shared_utils"
        )
    ),
)

# import as a module (not `from pii import redact_pii`) so that pii.comprehend
# is accessible for patch.object — the patch target must be the object the
# production code actually calls through
import pii


def local_redact_pii(text: str) -> dict:
    response = pii.comprehend.detect_pii_entities(Text=text, LanguageCode="en")
    print(response)
    entities = [
        e
        for e in response["Entities"]
        if e["Score"] >= pii.PII_SCORE_THRESHOLD
        and e["Type"] not in pii.PII_TYPES_TO_SKIP
    ]
    entities.sort(key=lambda e: e["BeginOffset"])
    print(entities)
    parts = []
    cursor = 0
    for entity in entities:
        parts.append(text[cursor : entity["BeginOffset"]])
        parts.append(f"[{entity['Type']}]")
        cursor = entity["EndOffset"]
    parts.append(text[cursor:])
    print(parts)
    return {
        "redacted_text": "".join(parts),
        "pii_entities_detected": len(entities),
    }


# %%
# ── test 1 ────────────────────────────────────────────────────────────────────


def test_single_entity_redacted():
    # one entity (SSN, Score=0.9) -> [SSN] substituted, surrounding text intact
    text = "My SSN is 123-45-6789, please help."
    fake_entities = {
        "Entities": [{"Score": 0.9, "Type": "SSN", "BeginOffset": 10, "EndOffset": 21}]
    }
    # patch.object intercepts calls on the already-imported client object —
    # moto doesn't support Comprehend so we can't use @mock_aws here
    with patch.object(
        pii.comprehend, "detect_pii_entities", return_value=fake_entities
    ):
        result = pii.redact_pii(text)
        print(result)
    assert result["redacted_text"] == "My SSN is [SSN], please help."
    assert result["pii_entities_detected"] == 1


# %%
# ── test 2 ────────────────────────────────────────────────────────────────────


def test_two_entities_both_redacted():
    # two non-overlapping entities -> both redacted, text between/around preserved
    text = "I live at 123 Main St and my SSN is 123-45-6789."
    fake_entities = {
        "Entities": [
            {"Score": 0.9, "Type": "ADDRESS", "BeginOffset": 10, "EndOffset": 21},
            {"Score": 0.9, "Type": "SSN", "BeginOffset": 36, "EndOffset": 47},
        ]
    }
    with patch.object(
        pii.comprehend, "detect_pii_entities", return_value=fake_entities
    ):
        result = pii.redact_pii(text)
    assert result["redacted_text"] == "I live at [ADDRESS] and my SSN is [SSN]."
    assert result["pii_entities_detected"] == 2


# %%
# ── test 3 ────────────────────────────────────────────────────────────────────


def test_low_score_entity_not_redacted():
    # entity with Score=0.3 (below 0.5 threshold) -> left unredacted, not counted
    text = "My SSN is 123-45-6789, please help."
    fake_entities = {
        "Entities": [{"Score": 0.3, "Type": "SSN", "BeginOffset": 10, "EndOffset": 21}]
    }
    with patch.object(
        pii.comprehend, "detect_pii_entities", return_value=fake_entities
    ):
        result = pii.redact_pii(text)
    # redacted_text must equal the original — the entity was filtered out before reconstruction
    assert result["redacted_text"] == text
    assert result["pii_entities_detected"] == 0


# ── test 4 ────────────────────────────────────────────────────────────────────


def test_no_entities_returns_original_text():
    # no entities returned -> redacted_text == text, pii_entities_detected == 0
    text = "Everything looks fine, no sensitive data here."
    fake_entities = {"Entities": []}
    with patch.object(pii.comprehend, "detect_pii_entities", return_value=fake_entities):
        result = pii.redact_pii(text)
    assert result["redacted_text"] == text
    assert result["pii_entities_detected"] == 0


# ── test 5 ────────────────────────────────────────────────────────────────────


def test_pii_entities_detected_counts_only_above_threshold():
    # mix of above/below threshold entities -> count reflects only those >= 0.5
    text = "SSN 123-45-6789 and card 4111-1111-1111-1111."
    fake_entities = {
        "Entities": [
            {"Score": 0.9, "Type": "SSN", "BeginOffset": 4, "EndOffset": 15},
            # Score=0.3 — below threshold, must NOT be redacted or counted
            {"Score": 0.3, "Type": "CREDIT_DEBIT_NUMBER", "BeginOffset": 25, "EndOffset": 44},
        ]
    }
    with patch.object(pii.comprehend, "detect_pii_entities", return_value=fake_entities):
        result = pii.redact_pii(text)
    assert result["pii_entities_detected"] == 1
    assert "[SSN]" in result["redacted_text"]
    # low-score card number must pass through untouched
    assert "4111-1111-1111-1111" in result["redacted_text"]


# ── test 6 ────────────────────────────────────────────────────────────────────


def test_out_of_order_entities_redacted_correctly():
    # entities returned out of BeginOffset order -> redaction still correct
    text = "My SSN is 123-45-6789 and card 4111-1111-1111-1111."
    fake_entities = {
        "Entities": [
            # deliberately listed in reverse order to confirm the sort in redact_pii
            {"Score": 0.9, "Type": "CREDIT_DEBIT_NUMBER", "BeginOffset": 31, "EndOffset": 50},
            {"Score": 0.9, "Type": "SSN", "BeginOffset": 10, "EndOffset": 21},
        ]
    }
    with patch.object(pii.comprehend, "detect_pii_entities", return_value=fake_entities):
        result = pii.redact_pii(text)
    assert result["redacted_text"] == "My SSN is [SSN] and card [CREDIT_DEBIT_NUMBER]."
    assert result["pii_entities_detected"] == 2


# ── test 7 ────────────────────────────────────────────────────────────────────


def test_entity_at_string_boundaries():
    # entity at BeginOffset=0 and another at EndOffset=len(text) -> no IndexError
    text = "123-45-6789 is my SSN"
    fake_entities = {
        "Entities": [
            # BeginOffset=0: entity at the very start — text[cursor:0] produces "" not an error
            {"Score": 0.9, "Type": "SSN", "BeginOffset": 0, "EndOffset": 11},
            # EndOffset=21=len(text): entity at the very end — text[21:] produces "" not an error
            {"Score": 0.9, "Type": "ADDRESS", "BeginOffset": 18, "EndOffset": 21},
        ]
    }
    with patch.object(pii.comprehend, "detect_pii_entities", return_value=fake_entities):
        result = pii.redact_pii(text)
    assert result["redacted_text"] == "[SSN] is my [ADDRESS]"
    assert result["pii_entities_detected"] == 2


# %%