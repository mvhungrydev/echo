# FR7 / DR4 — defense-in-depth: force-escalate to "high" if the email contains
# known crisis phrases, regardless of what the model assigned
ESCALATION_KEYWORDS = [
    "down",
    "outage",
    "can't access",
    "locked out",
    "charged twice",
    "double charged",
    "unauthorized charge",
    "cancel my account",
    "legal action",
    "data breach",
]


def apply_keyword_override(text: str, urgency: str) -> dict:
    # case-insensitive substring match — "shutdown" matches "down" by design (doc03 §3)
    text_lower = text.lower()
    override_applied = any(keyword in text_lower for keyword in ESCALATION_KEYWORDS)
    if override_applied:
        print(f"[keyword_rules] escalation keyword found — overriding urgency to 'high'")
        return {"urgency": "high", "urgency_override_applied": True}
    print(f"[keyword_rules] no escalation keyword — keeping urgency='{urgency}'")
    return {"urgency": urgency, "urgency_override_applied": False}
