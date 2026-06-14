# 07 - Future Enhancements

> Status: Draft.

ECHO's v1 scope is intentionally tight (see doc01 §6 "Out of Scope"). The items below are a short v2 backlog — not committed work, just enough to answer "what would you build next?"

| # | Idea | Description |
|---|------|-------------|
| 1 | Customer-care dashboard + review workflow | Minimal S3-hosted single-page dashboard listing triage results, with a `PATCH /emails/{id}` "mark as reviewed" action for `needs_review` items. |
| 2 | Automated DLQ reprocessing | A dedicated Lambda inspects DLQ messages, auto-redrives transient failures back to the main queue, and quarantines poison-pills with an alert. |
| 3 | Multi-language support | Detect non-English emails with Comprehend and translate via Amazon Translate before PII redaction/classification. |
| 4 | Automated reply sending | Opt-in "send" action for the AI-suggested reply via SES, gated behind explicit human review (preserves doc01's human-in-the-loop requirement). |
| 5 | DynamoDB GSI + trend insights | Add a GSI on `review_status`/`received_at` to replace `/insights`' full table scan and enable time-bounded trend queries (e.g., week-over-week sentiment). |
| 6 | Rate limiting on `/insights` | Usage-plan + API key layered on top of existing IAM auth (FR16), since each call triggers a paid Bedrock invocation. |
| 7 | Multi-region / WAF / production SLAs | If this became a real product: WAF on API Gateway, multi-region failover with DynamoDB Global Tables, and per-region duplication of account-level singletons (`security-baseline`, API Gateway account settings). |
