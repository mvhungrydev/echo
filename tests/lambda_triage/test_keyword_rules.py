# %%
import os
import sys

sys.path.insert(
    0,
    os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "src", "lambda_triage")
    ),
)

from keyword_rules import apply_keyword_override

# %%
# ── test 1 ────────────────────────────────────────────────────────────────────


def test_keyword_match_overrides_urgency_to_high():
    # text contains "outage" + urgency="medium" -> urgency="high", override_applied=True
    urgency = apply_keyword_override("outage", "medium")
    assert urgency["urgency"] == "high" and urgency["urgency_override_applied"] == True


# %%
# ── test 2 ────────────────────────────────────────────────────────────────────


def test_multi_word_phrase_matches():
    # text contains "charged twice" -> override applied
    pass


# %%
# ── test 3 ────────────────────────────────────────────────────────────────────


def test_escalation_churn_keyword_matches():
    # text contains "cancel my account" -> override applied
    pass


# %%
# ── test 4 ────────────────────────────────────────────────────────────────────


def test_keyword_match_is_case_insensitive():
    # text contains "DATA BREACH" (mixed case) -> override applied
    pass


# %%
# ── test 5 ────────────────────────────────────────────────────────────────────


def test_no_keyword_match_returns_original_urgency():
    # text contains none of the keywords, urgency="low" -> urgency="low", override_applied=False
    pass


# %%
# ── test 6 ────────────────────────────────────────────────────────────────────


def test_already_high_urgency_without_keyword_not_flagged():
    # urgency="high" already (no keyword match) -> stays "high", override_applied=False
    pass


# %%
# ── test 7 ────────────────────────────────────────────────────────────────────


def test_keyword_matches_as_substring():
    # text contains "shutdown" -> still matches "down", override applied
    pass
