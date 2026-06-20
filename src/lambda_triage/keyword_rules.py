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
    text_lower = text.lower()
    override_applied = any(keyword in text_lower for keyword in ESCALATION_KEYWORDS)
    if override_applied:
        return {"urgency": "high", "urgency_override_applied": True}
    return {"urgency": urgency, "urgency_override_applied": False}
