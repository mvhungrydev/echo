# 01 - Business Requirements

> **ECHO** (Email Classification & Handling Orchestrator) — an automated email triage, classification, and insights pipeline.

## 1. Problem Statement

Customer support teams receive a continuous stream of inbound emails that are triaged manually — a slow, inconsistent process where urgent issues (outages, billing disputes, angry escalations) can sit unread alongside routine inquiries, and where trends (e.g., recurring feature requests) are invisible without manually reading hundreds of messages. Manual handling also creates compliance risk: support staff routinely see PII (names, emails, phone numbers, account numbers) with no consistent redaction before that data is copied into other tools (e.g., an AI assistant).

## 2. Goals

- Every inbound email is automatically classified (category, urgency, sentiment, confidence) within seconds of receipt
- Emails classified `urgent` trigger a near-real-time alert to the support team
- PII is detected and redacted _before_ email content is sent to any AI service
- Classifications the model is unsure about are routed for human review rather than silently auto-processed
- Support leads can ask natural-language questions over historical triage data (e.g., "what are the top 3 most-requested features this month?")
- Access to aggregate insights is restricted to authorized (IAM-authenticated) callers
- The entire pipeline is observable end-to-end (traces, logs, metrics) via a single correlation ID per email
- The AWS account's security posture is continuously monitored

## 3. Functional Requirements

| ID   | Requirement                                                                                                                                                   |
| ---- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| FR1  | System shall accept inbound email via SES at a designated address and store the raw message in S3                                                             |
| FR2  | System shall parse the raw email (from, subject, body) and assign each email a unique `email_id` (SES `messageId`)                                            |
| FR3  | System shall detect and redact PII in the email body before further processing (Amazon Comprehend `DetectPiiEntities`)                                        |
| FR4  | System shall classify each email's `category`, `urgency`, `sentiment`, and `confidence` using an LLM (Amazon Bedrock)                                         |
| FR5  | System shall generate a suggested reply draft for each email                                                                                                  |
| FR6  | System shall extract feature-request tags for emails where `category = feature_request`                                                                       |
| FR7  | System shall apply a keyword-based rules override that can force-escalate `urgency` to `high` regardless of model output                                      |
| FR8  | System shall persist each email's classification result, including `review_status`, to DynamoDB                                                               |
| FR9  | System shall route low-confidence classifications (`review_status = needs_review`) to a separate notification path instead of auto-processing                 |
| FR10 | System shall send a near-real-time alert when an email is classified `urgent`                                                                                 |
| FR11 | System shall emit metrics for email volume by sentiment category and count of PII entities detected                                                           |
| FR12 | System shall provide a `POST /insights` API that answers natural-language aggregate questions over `auto_processed` emails (e.g., "top 3 requested features") |
| FR13 | System shall trace each email's processing end-to-end via X-Ray, correlated by `email_id`                                                                     |
| FR14 | System shall provide a CloudWatch dashboard summarizing pipeline health and triage metrics                                                                    |
| FR15 | System shall alert on anomalous spikes in negative-sentiment email volume (CloudWatch Anomaly Detection)                                                      |
| FR16 | The `/insights` API shall require AWS IAM authorization (SigV4-signed requests); unauthenticated requests shall be rejected (HTTP 403)                        |
| FR17 | If classification fails after retries, the system shall persist a degraded placeholder record (`category=unclassified`, `review_status=needs_review`) rather than dropping the email, and emit a failure metric |

### FR4 Classification Taxonomy

| Field | Values | Notes |
| --- | --- | --- |
| `category` | `bug_report` \| `feature_request` \| `general_inquiry` \| `billing` \| `complaint` \| `praise` \| `unclassified` | `unclassified` is reserved for FR17's degraded record — never an LLM output |
| `sentiment` | `positive` \| `negative` \| `constructive` \| `unknown` | `constructive` = critical tone paired with an actionable suggestion (e.g., a feature request or bug report raised diplomatically); `unknown` is reserved for FR17's degraded record |
| `confidence` | `high` \| `medium` \| `low` | LLM self-reported; drives `review_status` routing (FR9, doc03 §3.1 DR5) |

## 4. Non-Functional Requirements

| ID   | Category      | Requirement                                                                                                                                                                                                                      |
| ---- | ------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| NFR1 | Cost          | Monthly AWS spend stays near $0 for demo-scale usage, comfortably within the $200 free-tier credit. AWS Config and post-trial GuardDuty/Security Hub are the only non-negligible line items.                                     |
| NFR2 | Latency       | End-to-end triage (ingest → classification → alert) completes within a few seconds per email; dominated by Bedrock `InvokeModel` latency (~1-2s)                                                                                 |
| NFR3 | Reliability   | Failed messages land in a DLQ rather than being silently dropped; transient failures are retried with exponential backoff before landing in the DLQ; SQS at-least-once delivery is handled idempotently to avoid duplicate side effects (alerts, paid AI calls); demo-grade, not a production SLA |
| NFR4 | Security      | Least-privilege IAM per Lambda; PII redacted before leaving the account boundary to the LLM; `/insights` API access requires AWS IAM authorization (SigV4); account security posture monitored via GuardDuty/Security Hub/Config |
| NFR5 | Observability | Every component instrumented with X-Ray + CloudWatch (structured logs + EMF metrics), correlated by `email_id`                                                                                                                   |
| NFR6 | Region        | `us-east-1` — required for SES inbound receiving and full Bedrock/Claude model availability                                                                                                                                      |

## 5. Severity Definitions

**Email urgency (triage output, FR4/FR7):**

| Level  | Criteria                                                                          | Action                                    |
| ------ | --------------------------------------------------------------------------------- | ----------------------------------------- |
| High   | Outage/access blocked, billing disputes, escalation language, or keyword override | Immediate SNS alert (`alert_type=urgent`) |
| Medium | Bug reports (non-blocking), unresolved complaints                                 | Logged, no immediate alert                |
| Low    | Feature requests, general inquiries, praise                                       | Surfaced via `/insights` only             |

**Security findings (GuardDuty / Security Hub, AWS standard scale):**

| Severity | Criteria                                                                                                           | Remediation                                                 |
| -------- | ------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------- |
| Critical | Active compromise indicators (e.g., compromised credentials in use)                                                | Immediate investigation, rotate/revoke affected credentials |
| High     | Significant misconfiguration or suspicious activity (e.g., overly permissive IAM policy, unusual API call pattern) | Review and remediate within the demo session; document fix  |
| Medium   | Deviation from best practice (e.g., missing encryption, logging gap)                                               | Note for remediation; fix if time permits                   |
| Low      | Informational / hardening suggestions (e.g., unused IAM credentials)                                               | Track, no immediate action required for demo                |

## 6. Out of Scope

- Multi-language support (Amazon Translate)
- Automated sending of AI-suggested replies — drafts only, human-in-the-loop
- A "mark as reviewed" workflow for `needs_review` items
- Customer-care-rep frontend dashboard (deferred to v2)
- Production-grade SLAs, multi-region failover, WAF
- Real customer/production data — synthetic/test emails only
- DynamoDB GSI optimization for `/insights` (Scan + filter is sufficient at demo scale)
- API key/usage-plan-based rate limiting on `/insights` — IAM auth only for v1; revisit if needed
- Automated DLQ reprocessing / dedicated DLQ-handler Lambda — DLQ messages are inspected and redriven manually for v1
