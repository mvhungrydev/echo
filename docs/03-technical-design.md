# 03 - Technical Design

> **ECHO** (Email Classification & Handling Orchestrator) — an automated email triage, classification, and insights pipeline.

> Status: Sections 1-9 confirmed/locked. `docs/03-technical-design.md` complete.

## 1. Architecture

### 1.1 Email Ingest & Triage Pipeline

```
Customer
   │ sends email
   ▼
┌───────────────────────┐
│ SES Receipt Rule Set   │  (spam/virus scan → S3 action)
└──────────┬─────────────┘
           │ store raw .eml
           ▼
┌───────────────────────┐
│ S3: raw-emails/         │
│ (SSE-S3, lifecycle TTL) │
└──────────┬─────────────┘
           │ s3:ObjectCreated event
           ▼
┌───────────────────────┐
│ Lambda #1 (ingest)      │
│ - parse MIME            │
│ - email_id = SES        │
│   messageId             │
└──────────┬─────────────┘
           │ SendMessage
           ▼
┌─────────────────────────────────┐
│ SQS: email-triage-queue           │
│  visibility_timeout=100s          │
│  maxReceiveCount=2                │
└──────────┬─────────────┬─────────┘
           │ poll          │ after 2 failed receives
           ▼               ▼
┌────────────────────┐   ┌─────────────────────┐
│ Lambda #2 (triage)   │   │ SQS DLQ (14d ret.)   │
│ 1. idempotency check │   └──────────┬──────────┘
│    (DynamoDB GetItem)│              │ ApproxNumMessages>0
│ 2. Comprehend         │              ▼
│    DetectPiiEntities  │   ┌─────────────────────┐
│ 3. Bedrock classify    │   │ CloudWatch Alarm     │
│ 4. keyword override    │   └──────────┬──────────┘
│ 5. DynamoDB PutItem     │              │
│ 6. SNS publish          │              ▼
│ 7. EMF metrics          │   ┌─────────────────────┐
└──┬──────┬───────┬───────┘   │ SNS: ops-alarms       │
   │      │       │            └─────────────────────┘
   ▼      ▼       │
Comprehend Bedrock │
(PII)    (Claude   │
          Haiku)   ▼
          ┌─────────────────────────┐
          │ DynamoDB:                 │
          │ EmailTriageResults        │
          │ PK=email_id, TTL enabled  │
          └────────────┬──────────────┘
                        │
                        ▼
              ┌─────────────────────┐
              │ SNS: alert-topic      │
              │ (filter: alert_type)  │
              └──────┬────────┬───────┘
                     ▼        ▼
              urgent     needs_review
            subscribers   subscribers
```

### 1.2 Insights API

```
Support Lead
   │ sts:AssumeRole
   ▼
┌──────────────────────────┐
│ IAM Role:                  │
│ ECHOInsightsCaller   │
│ (execute-api:Invoke only)  │
└──────────┬─────────────────┘
           │ SigV4-signed POST /insights
           │ {"question": "..."}
           ▼
┌──────────────────────────┐
│ API Gateway                │
│ AWS_IAM authorizer         │──── reject (403) if unauthenticated/unauthorized (FR16)
└──────────┬─────────────────┘
           │ invoke
           ▼
┌──────────────────────────┐
│ Lambda #3 (insights)       │
│ 1. Scan EmailTriageResults │──────► DynamoDB: EmailTriageResults
│    (review_status=         │         (review_status=auto_processed,
│    auto_processed),         │          projected fields only)
│    project minimal fields   │
│ 2. Bedrock synthesize       │──────► Bedrock (Claude Haiku)
│    answer from records       │
│    + question                │
└──────────┬─────────────────┘
           │ {"answer": "...", "records_considered": N}
           ▼
       Support Lead
```

### 1.3 Observability & Security (cross-cutting)

```
┌──────────────────────────────────────────────────────────────────┐
│ X-Ray        — traces every Lambda invocation, annotated by        │
│                email_id (FR13)                                       │
│ CloudWatch   — EMF custom metrics, namespace `ECHO` (sentiment        │
│                counts, PII count, ClassificationFailure,               │
│                AlertPublishFailure, SynthesisFailure); dashboard       │
│                (FR14); anomaly detection on sentiment (FR15);          │
│                DLQ-depth alarm                                          │
│ CloudTrail   — account-wide API audit trail                            │
│ GuardDuty    — S3 Protection on raw-emails bucket                       │
│ Security Hub — CIS benchmark checks                                      │
│ AWS Config   — configuration compliance rules                            │
└──────────────────────────────────────────────────────────────────┘
```

### 1.4 Network Boundaries

Fully serverless, no VPC. Every component is either an AWS-managed service endpoint (SES, S3, SQS, SNS, DynamoDB, Comprehend, Bedrock, API Gateway) or a Lambda running without VPC attachment — no ENIs, private subnets, or NAT Gateway. The only boundaries crossing the public internet are: (1) inbound — a customer's email arriving at SES, and (2) the support lead's SigV4-signed request to API Gateway's public endpoint.

## 2. Data Flow

### 2.1 Email Ingest & Triage

1. Customer sends an email to an address on Mike's domain.
2. SES's active receipt rule set matches the recipient, runs its built-in spam/virus scan, and (assuming a pass) runs an S3 action storing the raw MIME at `s3://<raw-emails-bucket>/raw-emails/<ses-message-id>`.
3. The S3 `PutObject` fires an `s3:ObjectCreated:*` event, invoking Lambda #1 (ingest).
4. Lambda #1 reads the object, parses the raw MIME with stdlib `email.parser` (handles multipart/base64/quoted-printable), and extracts `from_address`, `subject`, `body`.
5. Lambda #1 sets `email_id` = the SES `messageId` — guarantees the same email always maps to the same `email_id`, which is what makes step 9's idempotency guard effective.
6. Lambda #1 sends `{email_id, from_address, subject, body, received_at, raw_s3_key}` to the `email-triage-queue` via `SendMessage`.
7. SQS triggers Lambda #2 (triage), batch size 1.
8. *(Layer 3 retry)* If Lambda #2 throws/times out, SQS redelivers after the 100s visibility timeout, up to `maxReceiveCount=2` total receives before the DLQ. Full detail in §4.
9. *(Idempotency guard)* Lambda #2 first `GetItem`s `EmailTriageResults` by `email_id`. If a record already exists, return success immediately — skip steps 10-17 entirely.
10. Lambda #2 calls Comprehend `DetectPiiEntities` on the body; detected entities are redacted (e.g., `[NAME]`, `[PHONE]`) before further processing. Entity count is recorded for step 16's metric.
11. Lambda #2 sends the redacted body to Bedrock (Claude Haiku) with a prompt requesting the structured classification JSON (category, urgency, sentiment, confidence, suggested_reply, feature_tags).
12. *(Layer 2 retry)* If the response isn't valid JSON matching the schema, retry once with a corrective prompt. If both attempts fail, fall back to the FR17 degraded record (`category=unclassified`, `urgency=medium`, `sentiment=unknown`, `confidence=low`, `suggested_reply=null`) and emit `ClassificationFailure`.
13. Lambda #2 applies the FR7 keyword override: if the redacted body/subject contains any urgency-escalation keyword (§3.2), force `urgency=high` and set `urgency_override_applied=true`.
14. Lambda #2 sets `review_status` = `needs_review` if `confidence != high` (or step 12 degraded), else `auto_processed`. Routing is binary on `confidence` (`high` vs. not-`high`) — `medium` and `low` both route to `needs_review`; the 3-value scale (doc01 FR4 taxonomy, §8.5) is preserved in the persisted record for `/insights` diagnostics, not for routing.
15. Lambda #2 `PutItem`s the full record into `EmailTriageResults` (PK=`email_id`, plus `processed_at`, `ttl`).
16. Lambda #2 emits EMF metrics: sentiment counts, PII-entity count, and `ClassificationFailure` if applicable.
17. Lambda #2 publishes to `alert-topic` SNS with message attribute `alert_type` = `urgent` | `needs_review` | `none`. Subscribers use filter policies to receive only relevant alert types.
18. *(Layer 2 DEGRADE)* If the SNS publish itself fails after Layer 1 retries, log + emit `AlertPublishFailure`, but still treat the message as successfully processed — avoids re-running paid Comprehend/Bedrock calls just to retry a notification.
19. X-Ray captures a trace segment for the invocation, annotated with `email_id`.

### 2.2 Insights API

20. A support lead obtains temporary credentials via `sts:AssumeRole` on `ECHOInsightsCaller`.
21. The support lead sends a SigV4-signed `POST /insights` (`{"question": "..."}`) to API Gateway.
22. API Gateway's `AWS_IAM` authorizer validates the signature; unauthenticated/unauthorized requests get HTTP 403 (FR16).
23. API Gateway invokes Lambda #3 (insights) with the request body.
24. Lambda #3 `Scan`s `EmailTriageResults` filtered to `review_status=auto_processed`, projecting only `category`, `urgency`, `sentiment`, `feature_tags`, `received_at` (data minimization).
25. Lambda #3 sends the projected records + question to Bedrock (Claude Haiku) for synthesis.
26. *(Layer 2 retry)* Same Bedrock response-validation retry as step 12 (2 attempts), using Lambda #3's tightened Bedrock client config (§7.3) so worst-case retry time fits its 28s budget. On exhaustion, Lambda #3 returns the `/insights` failure response instead (§7.3, DR8).
27. Lambda #3 returns `{"answer": "...", "records_considered": N}` via API Gateway to the support lead.
28. X-Ray captures a trace segment (not `email_id`-correlated — `/insights` is an aggregate query, but still part of the service map).

## 3. Detection Rules & Severity Rationale

### 3.1 Detection Rules Table

Scope note: this table covers detection rules specific to this system's email-triage logic. AWS-managed security findings (GuardDuty/Security Hub/Config) already have their severity scale defined in doc01 §5 and aren't re-enumerated here.

| Rule ID | Data Source | Description | Severity | Remediation / Action |
| --- | --- | --- | --- | --- |
| DR1 | Bedrock (Claude Haiku) classification | LLM assigns `urgency=high` — outage/access blocked, billing dispute, or escalation language | High | SNS alert (`alert_type=urgent`) → urgent subscribers |
| DR2 | Bedrock (Claude Haiku) classification | LLM assigns `urgency=medium` — non-blocking bug reports, unresolved complaints | Medium | Persisted to DynamoDB; visible via `/insights`; no immediate alert |
| DR3 | Bedrock (Claude Haiku) classification | LLM assigns `urgency=low` — feature requests, general inquiries, praise | Low | Persisted; `feature_tags` extracted if `category=feature_request` (FR6); `/insights` only |
| DR4 | Deterministic keyword match (post-Bedrock, FR7) | Redacted body/subject contains an escalation keyword (§3.2) | High (forced) | Forces `urgency=high` regardless of DR1-DR3; sets `urgency_override_applied=true`; same SNS path as DR1 |
| DR5 | Bedrock `confidence` field | LLM self-reports `confidence != high` | Informational | `review_status=needs_review`; `needs_review` SNS subscribers notified for human QA (FR9) |
| DR6 | Comprehend `DetectPiiEntities` | PII entities detected in raw email body | Informational | Redact before Bedrock call (FR3 — security gate, RAISE on failure); entity count → EMF metric |
| DR7 | Bedrock response validation (Layer 2 exhaustion) | Bedrock fails to return valid classification JSON after retries | Informational | Persist FR17 degraded record (`category=unclassified`, `review_status=needs_review`); emit `ClassificationFailure` metric |
| DR8 | Bedrock response validation (Layer 2 exhaustion, Lambda #3) | Bedrock fails to return valid synthesis JSON after retries within Lambda #3's tightened timeout (§7.3) | Informational | Return HTTP 503 `{"error":"synthesis_unavailable","records_considered":N}`; emit `SynthesisFailure` metric |

### 3.2 FR7 Escalation Keyword List

Case-insensitive substring match against **redacted** subject + body.

| Category | Phrases |
| --- | --- |
| Outage / access blocked | `down`, `outage`, `can't access`, `locked out` |
| Billing dispute | `charged twice`, `double charged`, `unauthorized charge` |
| Escalation / churn risk | `cancel my account`, `legal action` |
| Security concern | `data breach` |

**Storage**: hardcoded list constant in Lambda #2's shared code module — simplest for demo, consistent with the Layer 1/2 retry-constants decision. Production note: would likely move to SSM Parameter Store for tuning without redeployment.

### 3.3 Severity Rationale

- **High (DR1)** — outage/access-blocked and billing disputes have direct customer impact (lost productivity/money) and reputational/financial risk — these map to "Sev1"-style definitions industry-wide; immediate alerting is justified.
- **DR4 exists as a separate High path** — defense-in-depth. LLMs can occasionally under-rate urgency on subtly-worded or terse messages. A deterministic keyword check guarantees a small set of unambiguous high-stakes terms can never silently fall to medium/low due to model variance — the "trust but verify" pattern from the retry/backoff design.
- **Medium (DR2)** — bug reports/complaints need fixing but don't block the customer right now; doesn't justify interrupting on-call staff in real time.
- **Low (DR3)** — feature requests/inquiries/praise carry no per-email urgency; their value is aggregate (via `/insights`), not individual response.
- **Informational (DR5-DR8)** — these aren't about the email's urgency to the customer, they're about the pipeline's own quality/compliance posture: DR5 is a QA routing signal, DR6 is a compliance metric (PII exposure), DR7 ensures no email is silently lost when AI fails, DR8 is its `/insights`-side counterpart (a failed synthesis is surfaced to the caller rather than silently returning a stale or empty answer). None alone constitute a customer-facing emergency.
- **Why 4 tiers is enough** — at demo scale there are only two operational outcomes ("alert now" vs. "don't"), so finer-grained severity (e.g., P0-P4) would add complexity with no corresponding new escalation path.

## 4. Retry, Backoff & Failure Handling

### 4.1 Overview — Three-Layer Defense

Each layer targets a different failure mode and timescale — a transient network blip, a flaky LLM response, and a hard infrastructure failure are different problems and get different remedies. Layers 1-2 are *intra-invocation* (retried within a single Lambda execution); Layer 3 is *inter-invocation* (retried via SQS redelivery, a fresh Lambda execution each time).

### 4.2 Layer 1 — SDK-Level Retries (boto3/botocore)

Covers transient AWS API errors: throttling, 5xx responses, connection resets. Applies to every AWS SDK call, every Lambda, via a shared `retry_config.py` constants module.

| Client(s) | `max_attempts` | `connect_timeout` | `read_timeout` | Retry mode |
| --- | --- | --- | --- | --- |
| Comprehend, DynamoDB, SNS, S3, SQS | 3 | 3s | 5s | adaptive |
| Bedrock | 3 | 3s | 10s | adaptive |

`adaptive` mode adds exponential backoff + jitter between attempts automatically.

> **Exception — Lambda #3's Bedrock client** uses a tighter config (`max_attempts=2`, `read_timeout=5s`) than the table above, so its worst-case retry time fits comfortably within its 28s Lambda timeout. See §7.3.

### 4.3 Layer 2 — Application-Level Bedrock Response Validation Retry

Covers the case where Bedrock returns HTTP 200 but the content isn't a valid classification (unparseable JSON, missing fields, truncated output). Layer 1 can't catch this — the HTTP call succeeded.

| | Max attempts | Backoff | Corrective behavior |
| --- | --- | --- | --- |
| Lambda #2 (triage) | 2 (1 retry) | ~1s jittered | Retry prompt includes "previous response was not valid JSON, return ONLY JSON matching schema X"; bump `max_tokens` if truncation suspected |
| Lambda #3 (insights) | 2 (1 retry) | ~0.5s | Same corrective approach |

**Post-exhaustion behavior:**
- Lambda #2 → falls back to the FR17 degraded record (DR7).
- Lambda #3 → resolved in §7.3: returns HTTP 503 `{"error":"synthesis_unavailable","records_considered":N}` and emits the `SynthesisFailure` metric (DR8).

### 4.4 Layer 3 — SQS Redrive + DLQ

| Parameter | Value | Derivation |
| --- | --- | --- |
| Lambda #2 function timeout | 75s | Comprehend ~18s + Bedrock-loop ~14s + DynamoDB ~18s + SNS ~18s ≈ 68s, rounded up |
| SQS visibility timeout (demo) | 100s | ~1.33x function timeout — deliberate deviation from AWS's 6x guidance (see below) |
| `maxReceiveCount` | 2 | → 6 total Comprehend/DynamoDB attempts before DLQ (2 invocations × Layer 1's 3 attempts each) |
| Worst-case time-to-DLQ (demo) | ~3.3 min | 2 × 100s visibility timeout |
| DLQ retention | 14 days (1,209,600s) | Maximum allowed — maximizes investigation/redrive window |

**Why AWS recommends 6x function timeout (production rationale):** the multiplier isn't about processing time — it buffers against Lambda concurrency throttling delaying invocation start *while the visibility timer is already running*. At demo scale, with no concurrency contention, that risk is ~0, which is the justification for the 100s deviation. Documented prod value: **450s** (6×75), giving a worst-case-to-DLQ of ~15 min — impractical for a live demo, appropriate for production.

**DLQ-depth monitoring:** CloudWatch alarm on `ApproximateNumberOfMessagesVisible > 0` → publishes to a separate `ops-alarms` SNS topic (not the main `alert-topic` — CloudWatch alarm actions can't attach the `alert_type` message attribute, so the main topic's filter policies wouldn't match).

### 4.5 Failure Routing (RAISE vs. DEGRADE)

| Step | After Layers 1/2 exhausted | Routes to |
| --- | --- | --- |
| Comprehend `DetectPiiEntities` | **RAISE** | Layer 3 → SQS redelivery → DLQ (PII redaction is a hard security gate, FR3 — never skip) |
| Bedrock classify (Lambda #2) | **DEGRADE** | FR17 degraded record (DR7) + `ClassificationFailure` metric |
| DynamoDB `PutItem` | **RAISE** | Layer 3 (no fallback — FR8 has no degraded path if persistence itself fails) |
| SNS `Publish` | **DEGRADE** | Log + `AlertPublishFailure` metric; message still marked processed |

**Net effect:** only Comprehend/DynamoDB failures can drive a message to the DLQ — every other failure mode degrades gracefully and still produces a usable record.

**Concrete RAISE causes — Comprehend `DetectPiiEntities`:**
- `ThrottlingException` sustained across all 3 Layer 1 adaptive-retry attempts (account-level TPS limit)
- `InternalServerError` (5xx) from the service
- `TextSizeLimitExceededException` — email body exceeds Comprehend's 100KB input limit (non-retryable, fails on attempt 1, still propagates)
- `AccessDeniedException` — IAM misconfiguration (e.g., a bad Terraform apply)
- Connection/read timeout exhaustion (3 × 5s `read_timeout` all time out — real network-level failure)

**Concrete RAISE causes — DynamoDB `PutItem`:**
- `ThrottlingException` — possible even on-demand under a very large burst
- `InternalServerError` (5xx)
- `ResourceNotFoundException` — table name/ARN misconfiguration
- `ValidationException` — item exceeds DynamoDB's 400KB item-size limit, or an attribute has the wrong type
- `AccessDeniedException` — IAM misconfiguration
- Connection/read timeout exhaustion (3 × 5s `read_timeout`)

**Additional DLQ-eligible paths (not RAISE, but same redelivery effect):**
- **Unhandled code bugs / malformed input** — e.g., Lambda #1 sends a payload missing a required key, and Lambda #2's parsing throws `KeyError`. A true "poison pill": fails identically on every redelivery, which is exactly what `maxReceiveCount=2` + DLQ exists to catch. This is the mechanism behind the poison-pill fault-injection demo (a magic string in the email subject deliberately triggers this).
- **Lambda function timeout (75s) or OOM** — the Lambda service kills the execution mid-flight; nothing in the code "throws," but SQS never receives a successful completion, so the message is redelivered the same as a RAISE.

### 4.6 Idempotency Guard

At the start of Lambda #2: `GetItem` on `EmailTriageResults` for `email_id`. If a record already exists, return success immediately — skip Comprehend/Bedrock/DynamoDB/SNS entirely.

This is the standard "idempotent consumer" pattern for SQS's at-least-once delivery. It specifically protects against: a prior invocation fully succeeded (including the SNS publish) but the Lambda crashed/timed out after completing work and before returning cleanly to SQS — without this guard, redelivery would re-run paid Comprehend/Bedrock calls and double-publish an alert.

### 4.7 Parameter Summary — Where Each Value Lives

| Parameter | Location | Value |
| --- | --- | --- |
| Layer 1 `max_attempts`, timeouts | Hardcoded — shared `retry_config.py` module | as table above |
| Layer 2 `max_attempts`, backoff | Hardcoded — shared module | as table above |
| `sqs_visibility_timeout` | Terraform variable | demo=100, documented prod=450 |
| `sqs_max_receive_count` | Terraform variable | 2 |
| `lambda2_timeout` | Terraform variable | 75 (kept alongside visibility_timeout so the "visibility ≥ function timeout" relationship is visible/adjustable together) |
| DLQ `message_retention_seconds` | Hardcoded in Terraform module | 1,209,600 (14 days) |
| DLQ-depth alarm threshold | Hardcoded in Terraform module | `> 0`, `GreaterThanThreshold` |

Full Terraform wiring goes in `04-infrastructure-spec.md`'s variables table — this is the design-level summary.

## 5. Lambda / Compute Spec

### 5.1 Packaging & Runtime (applies to all 3 Lambdas)

| Decision | Choice | Why |
| --- | --- | --- |
| Packaging | `.zip` deployment package | Only dependency is boto3/botocore — no need for container images/ECR |
| Runtime | `python3.13` | Current Lambda-supported runtime; stdlib `email.parser` works fine |
| Architecture | `arm64` (Graviton2) | ~20% cheaper, no native-extension deps — small cost win consistent with NFR1 |
| Entry point | `handler.handler` for all 3 | Standard `def handler(event, context):` convention |
| Shared dependency layer | One Lambda Layer (`shared-utils`) containing pinned `boto3`/`botocore` (`>=1.34.0`) + `retry_config.py` | Lambda's bundled boto3 isn't guaranteed to support `bedrock-runtime`; a pinned layer guarantees Bedrock support across all 3 Lambdas and centralizes §4.2's `Config` objects |

### 5.2 Directory Structure

```
src/
├── lambda_ingest/        (Lambda #1)
│   ├── handler.py
│   └── mime_parser.py     — MIME parsing helpers (multipart/base64/quoted-printable)
├── lambda_triage/         (Lambda #2)
│   ├── handler.py
│   ├── pii.py               — Comprehend DetectPiiEntities + redaction
│   ├── classify.py           — Bedrock invoke + Layer 2 retry/validation (§4.3)
│   ├── keyword_rules.py       — FR7 escalation keyword list + override (DR4, §3.2)
│   └── persist.py              — idempotency GetItem + DynamoDB PutItem
├── lambda_insights/        (Lambda #3)
│   ├── handler.py
│   ├── query.py               — DynamoDB Scan + field projection (§2.2 step 24)
│   └── synthesize.py           — Bedrock invoke + Layer 2 retry (§4.3)
└── layers/shared_utils/
    └── retry_config.py          — GENERAL_CONFIG and BEDROCK_CONFIG (§4.2)
```

### 5.3 Per-Lambda Spec

| | Lambda #1 (ingest) | Lambda #2 (triage) | Lambda #3 (insights) |
| --- | --- | --- | --- |
| Trigger | S3 `ObjectCreated` | SQS, batch size 1 | API Gateway `POST /insights` |
| Memory | 256 MB | 512 MB (more CPU for the multi-call chain within 75s) | 256 MB |
| Timeout | 45s | **75s** (§4.4) | **28s** (see below) |
| Failure path | On-failure destination → `ops-alarms` SNS (§5.5) | SQS redrive + DLQ (§4) | Synchronous — errors returned directly to caller |

### 5.4 API Gateway's 29s Hard Timeout Caps Lambda #3

REST API Gateway kills the backend integration at **29 seconds** regardless of the Lambda's configured timeout. Lambda #3's actual time budget for DynamoDB Scan + Bedrock synthesis (+ Layer 2 retry) is therefore ≤29s. Setting **Lambda #3's timeout to 28s** (just under the ceiling) lets Lambda return its own clean error JSON instead of API Gateway's generic 504. In the happy path this is irrelevant (Scan + Bedrock ≈ 2-3s per NFR2); it only matters when Bedrock is degraded — and that case is resolved in §7.3: Lambda #3's tightened Bedrock client config (§4.2 exception) bounds worst-case retry time to ~21.5s, leaving headroom to always return its own structured response (success or `SynthesisFailure`, DR8) within this 28s budget rather than hitting a Lambda timeout / API Gateway 504.

### 5.5 Lambda #1 On-Failure Destination

Lambda #1 is invoked asynchronously by S3 (not via SQS), so §4's SQS+DLQ retry architecture doesn't cover it. Lambda async invocations retry automatically (2 retries, 3 total attempts); after that, an on-failure destination catches the event. Decision: reuse the existing `ops-alarms` SNS topic rather than introduce a 4th destination — a failed Lambda #1 invocation (e.g., a corrupted/unparseable `.eml`) is an ops concern, same category as DLQ depth.

## 6. IAM Permissions

General notes:
- **No KMS permissions anywhere** — S3 uses SSE-S3, DynamoDB/SQS/SNS use AWS-owned default encryption. No customer-managed keys in this design.
- **`comprehend:DetectPiiEntities` requires `Resource: "*"`** — synchronous text-detection API with no resource-level permissions defined by AWS, not a wildcard chosen by us.
- **`xray:PutTraceSegments`/`PutTelemetryRecords` require `Resource: "*"`** — same reason, AWS-imposed.
- **Bedrock model ARN is pinned** — `arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-3-haiku-20240307-v1:0`, no wildcard, no account ID (foundation models are AWS-owned shared resources).
- **No `cloudwatch:PutMetricData` anywhere** — EMF (Embedded Metric Format) metrics are parsed from structured `logs:PutLogEvents` output (doc02 §4 decision #6), so sentiment counts, PII-entity count, `ClassificationFailure`, `AlertPublishFailure` (FR11, FR17), and `SynthesisFailure` (FR12, DR8) need no extra permission.

### 6.1 Lambda #1 (ingest) — execution role

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ReadRawEmails",
      "Effect": "Allow",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::<RAW_EMAILS_BUCKET>/raw-emails/*"
      // Wildcard on object key: each email gets a unique S3 key (SES messageId-based) — cannot be enumerated in advance.
    },
    {
      "Sid": "SendToTriageQueue",
      "Effect": "Allow",
      "Action": "sqs:SendMessage",
      "Resource": "arn:aws:sqs:us-east-1:<ACCOUNT_ID>:email-triage-queue"
    },
    {
      "Sid": "PublishFailureToOpsAlarms",
      "Effect": "Allow",
      "Action": "sns:Publish",
      "Resource": "arn:aws:sns:us-east-1:<ACCOUNT_ID>:ops-alarms"
      // Async-invocation on-failure destination (§5.5).
    },
    {
      "Sid": "WriteLogs",
      "Effect": "Allow",
      "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
      "Resource": "arn:aws:logs:us-east-1:<ACCOUNT_ID>:log-group:/aws/lambda/email-ingest:*"
      // Trailing :* covers per-invocation log streams within this function's log group only.
    },
    {
      "Sid": "XRayTracing",
      "Effect": "Allow",
      "Action": ["xray:PutTraceSegments", "xray:PutTelemetryRecords"],
      "Resource": "*"
      // AWS-imposed: these actions don't support resource-level permissions.
    }
  ]
}
```

### 6.2 Lambda #2 (triage) — execution role

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ConsumeTriageQueue",
      "Effect": "Allow",
      "Action": ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"],
      "Resource": "arn:aws:sqs:us-east-1:<ACCOUNT_ID>:email-triage-queue"
      // Required by the SQS event source mapping itself, not just app code.
    },
    {
      "Sid": "DetectPii",
      "Effect": "Allow",
      "Action": "comprehend:DetectPiiEntities",
      "Resource": "*"
      // AWS-imposed: real-time detection on request input, no resource ARN exists for this action.
    },
    {
      "Sid": "InvokeClassificationModel",
      "Effect": "Allow",
      "Action": "bedrock:InvokeModel",
      "Resource": "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-3-haiku-20240307-v1:0"
    },
    {
      "Sid": "TriageRecordAccess",
      "Effect": "Allow",
      "Action": ["dynamodb:GetItem", "dynamodb:PutItem"],
      "Resource": "arn:aws:dynamodb:us-east-1:<ACCOUNT_ID>:table/EmailTriageResults-${var.env}"
      // GetItem = idempotency check (§4.6); PutItem = persist classification (FR8).
    },
    {
      "Sid": "PublishAlerts",
      "Effect": "Allow",
      "Action": "sns:Publish",
      "Resource": "arn:aws:sns:us-east-1:<ACCOUNT_ID>:alert-topic"
    },
    {
      "Sid": "WriteLogs",
      "Effect": "Allow",
      "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
      "Resource": "arn:aws:logs:us-east-1:<ACCOUNT_ID>:log-group:/aws/lambda/email-triage:*"
    },
    {
      "Sid": "XRayTracing",
      "Effect": "Allow",
      "Action": ["xray:PutTraceSegments", "xray:PutTelemetryRecords"],
      "Resource": "*"
    }
  ]
}
```

### 6.3 Lambda #3 (insights) — execution role

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ScanTriageRecords",
      "Effect": "Allow",
      "Action": "dynamodb:Scan",
      "Resource": "arn:aws:dynamodb:us-east-1:<ACCOUNT_ID>:table/EmailTriageResults-${var.env}"
    },
    {
      "Sid": "InvokeSynthesisModel",
      "Effect": "Allow",
      "Action": "bedrock:InvokeModel",
      "Resource": "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-3-haiku-20240307-v1:0"
    },
    {
      "Sid": "WriteLogs",
      "Effect": "Allow",
      "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
      "Resource": "arn:aws:logs:us-east-1:<ACCOUNT_ID>:log-group:/aws/lambda/email-insights:*"
    },
    {
      "Sid": "XRayTracing",
      "Effect": "Allow",
      "Action": ["xray:PutTraceSegments", "xray:PutTelemetryRecords"],
      "Resource": "*"
    }
  ]
}
```

### 6.4 Resource-Based "Invoke" Permissions

Not execution-role policies — these are resource policies attached to the Lambda functions themselves, granting other AWS services permission to invoke them.

```json
// On Lambda #1 — allows S3 to invoke it
{
  "Sid": "AllowS3Invoke",
  "Effect": "Allow",
  "Principal": { "Service": "s3.amazonaws.com" },
  "Action": "lambda:InvokeFunction",
  "Resource": "arn:aws:lambda:us-east-1:<ACCOUNT_ID>:function:email-ingest",
  "Condition": {
    "StringEquals": { "AWS:SourceAccount": "<ACCOUNT_ID>" },
    "ArnLike": { "AWS:SourceArn": "arn:aws:s3:::<RAW_EMAILS_BUCKET>" }
  }
}

// On Lambda #3 — allows API Gateway to invoke it
{
  "Sid": "AllowAPIGatewayInvoke",
  "Effect": "Allow",
  "Principal": { "Service": "apigateway.amazonaws.com" },
  "Action": "lambda:InvokeFunction",
  "Resource": "arn:aws:lambda:us-east-1:<ACCOUNT_ID>:function:email-insights",
  "Condition": {
    "ArnLike": { "AWS:SourceArn": "arn:aws:execute-api:us-east-1:<ACCOUNT_ID>:<API_ID>/*/POST/insights" }
  }
}
```

Lambda #2's SQS trigger needs no resource-based policy — event source mappings poll using the execution role's own permissions (§6.2).

### 6.5 `ECHOInsightsCaller` Role (FR16)

```json
// Trust policy — who can assume this role
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "AWS": "arn:aws:iam::<ACCOUNT_ID>:user/<MIKE_IAM_USER>" },
      "Action": "sts:AssumeRole"
    }
  ]
}

// Permissions policy — what the assumed role can do
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "InvokeInsightsOnly",
      "Effect": "Allow",
      "Action": "execute-api:Invoke",
      "Resource": "arn:aws:execute-api:us-east-1:<ACCOUNT_ID>:<API_ID>/*/POST/insights"
    }
  ]
}
```

## 7. Output / Report Formats

### 7.1 SNS Alert Format (`alert-topic`)

Every Lambda #2 invocation publishes exactly one message to `alert-topic` (step 17). The message **attribute** `alert_type` (String) = `urgent` | `needs_review` | `none` is what subscriber filter policies act on — SNS filter policies match attributes, not body content, so the body shape below is for the subscriber's consumption (e.g., a Lambda that posts to Slack/email), not for routing.

**`alert_type=urgent` (DR1/DR4):**
```json
{
  "email_id": "<ses-message-id>",
  "alert_type": "urgent",
  "received_at": "2026-06-13T14:32:05Z",
  "from_address": "customer@example.com",
  "subject": "Site has been down for an hour",
  "category": "bug_report",
  "urgency": "high",
  "urgency_override_applied": true,
  "sentiment": "negative",
  "confidence": "high",
  "suggested_reply": "Hi, thanks for flagging this — we're investigating the outage now and will update you shortly..."
}
```
`urgency_override_applied` is included here because it's most meaningful on the alert that triggers an immediate page — it tells the on-call responder whether DR1 (model judgment) or DR4 (keyword override) is why this fired.

**`alert_type=needs_review` (DR5 — low confidence):**
```json
{
  "email_id": "<ses-message-id>",
  "alert_type": "needs_review",
  "received_at": "2026-06-13T14:32:05Z",
  "from_address": "customer@example.com",
  "subject": "question about my account",
  "category": "general_inquiry",
  "urgency": "medium",
  "sentiment": "constructive",
  "confidence": "low",
  "review_reason": "low_confidence",
  "suggested_reply": "Hi, thanks for reaching out — could you clarify..."
}
```

**`alert_type=needs_review` (DR7 — FR17 degraded record):**
```json
{
  "email_id": "<ses-message-id>",
  "alert_type": "needs_review",
  "received_at": "2026-06-13T14:32:05Z",
  "from_address": "customer@example.com",
  "subject": "question about my account",
  "category": "unclassified",
  "urgency": "medium",
  "sentiment": "unknown",
  "confidence": "low",
  "review_reason": "classification_failed",
  "suggested_reply": null
}
```

`review_reason` is derived at publish time (`"classification_failed"` if `category=unclassified`, else `"low_confidence"`) — not a separately stored DynamoDB attribute. It tells the human reviewer *why* this landed in their queue: DR5 (model wasn't confident) vs. DR7 (model didn't respond usefully at all).

**`alert_type=none` (DR2/DR3 — auto-processed, no human action needed):**
```json
{
  "email_id": "<ses-message-id>",
  "alert_type": "none",
  "received_at": "2026-06-13T14:32:05Z",
  "category": "feature_request",
  "urgency": "low",
  "sentiment": "positive",
  "confidence": "high"
}
```
Deliberately minimal — no `from_address`/`subject`/`suggested_reply`, since no subscriber acts on it (data-minimization, same principle as step 24's `/insights` projection). Published for consistency (every triage produces exactly one publish event, giving a single auditable stream of all outcomes) and to leave room for a future "all emails" subscriber without changing Lambda #2.

**Illustrative subscriber filter policies** (full Terraform `aws_sns_topic_subscription` resources belong in doc04):
```json
// "urgent-ops" subscription
{ "alert_type": ["urgent"] }

// "needs-review" subscription
{ "alert_type": ["needs_review"] }
```
A message published with `alert_type=none` matches neither policy and is simply not delivered to either subscription — SNS doesn't error on an unmatched message, it's dropped silently (no DLQ needed for the topic itself at this scale).

### 7.2 `/insights` API Contract (FR12)

**Request:**
```json
POST /insights
{
  "question": "What are the top 3 most-requested features this month?"
}
```

**Success response — HTTP 200:**
```json
{
  "answer": "The top 3 most-requested features this month are: 1) dark mode (7 mentions), 2) CSV export (4 mentions), 3) SSO login (3 mentions).",
  "records_considered": 42
}
```
`records_considered` is the count of `review_status=auto_processed` records returned by step 24's Scan — included even on a "no data" answer (e.g., `records_considered: 0`) so the caller can distinguish "nothing happened yet" from "synthesis failed" (§7.3).

### 7.3 Lambda #3 Failure Response (DR8) & the 28s Budget

This resolves the open item flagged since §5.4: what `/insights` returns when Bedrock synthesis (step 25) fails validation on both Layer 2 attempts (step 26).

**Lambda #3's Bedrock client uses a tightened config** (exception to §4.2's table):

| Client | `max_attempts` | `connect_timeout` | `read_timeout` | mode |
| --- | --- | --- | --- | --- |
| Bedrock (Lambda #3 only) | 2 | 3s | 5s | adaptive |

**Worst-case timing derivation** (why this fits the 28s Lambda timeout, §5.4):
- Each Layer 2 attempt's Bedrock call: Layer 1 retries up to 2× at 5s `read_timeout` = **10s worst case per attempt**
- Layer 2 = 2 attempts total = **~20s** worst-case Bedrock time, + ~0.5s jittered backoff between them ≈ **20.5s**
- + DynamoDB Scan (small table, ~1s worst case at demo scale) ≈ **~21.5s total**
- Leaves **~6.5s headroom** under the 28s timeout for cold start, JSON parsing, and Lambda runtime overhead

This guarantees Lambda #3 *always* finishes within its own 28s timeout and returns its own response — it never relies on API Gateway's 504 or a Lambda-service `Task timed out` 502.

**Failure response — HTTP 503:**
```json
{
  "error": "synthesis_unavailable",
  "records_considered": 42
}
```
503 (not 500) signals a transient downstream-dependency issue — Bedrock throttling/instability is the most likely cause, and the same `question` may succeed on a retry. `records_considered` is still returned: the Scan succeeded, only synthesis degraded, so the caller learns data exists even though no answer could be generated.

Lambda #3 also emits a `SynthesisFailure` EMF metric on this path (DR8) — the `/insights`-side counterpart to Lambda #2's `ClassificationFailure` (DR7), feeding the same observability/alerting pattern (FR11/FR15).

## 8. Supporting Services & Data Stores

### 8.1 S3 — Raw Emails Bucket

| Setting | Value | Notes |
| --- | --- | --- |
| Bucket name | `<project>-raw-emails-<account-id>` | account-id suffix avoids global-namespace collisions |
| Prefix | `raw-emails/<ses-message-id>` | matches step 2 |
| Encryption | SSE-S3 (default, `AES256`) | no CMK, consistent with §6 |
| Block Public Access | all 4 settings enabled | no legitimate public access case |
| Versioning | disabled | each `email_id` (SES `messageId`) is unique — no overwrite risk, so version history adds cost/noise without benefit |
| Lifecycle policy | expire objects after 90 days | mirrors the DynamoDB `ttl` (`received_at` + 90d) — same data-retention story applies to the raw artifact as to the derived record |
| Bucket policy | allow `ses.amazonaws.com` to `PutObject` under `raw-emails/*`, conditioned on `aws:SourceAccount = <ACCOUNT_ID>` | standard SES-to-S3 receipt rule requirement; this is the resource-side counterpart to the receipt rule action in §8.2 |

### 8.2 SES

| Setting | Value | Notes |
| --- | --- | --- |
| Receipt rule set | single rule set, set active | only one rule set can be active per region at a time |
| Recipient condition | the address on Mike's domain (e.g. `support@<domain>`) | requires the domain's MX record to point at SES (NFR6) |
| Rule actions, in order | (1) implicit spam/virus scan (`ScanEnabled=true`), (2) S3 action → bucket/prefix from §8.1 | a failed scan drops the message before it ever reaches S3/Lambda #1 — out of scope to alert on (doc01 §6, synthetic/test traffic only) |
| Region | `us-east-1` | required (NFR6) |

### 8.3 SQS

| Setting | `email-triage-queue` | `email-triage-dlq` |
| --- | --- | --- |
| Visibility timeout | 100s (§4.4) | n/a (messages aren't reprocessed automatically — doc01 Out of Scope) |
| Message retention | 4 days (default) | 14 days / 1,209,600s (§4.4 — maximizes manual-redrive investigation window) |
| `maxReceiveCount` redrive | 2, target = DLQ above | — |
| Encryption | SSE-SQS (AWS-managed, `alias/aws/sqs`) | same |

4-day retention on the main queue is the AWS default and is generous relative to the 100s/2-receive path to the DLQ (~3.3min worst case, §4.4) — a message simply never sits in the main queue long enough for retention to matter; left at default rather than tuned down, since there's no cost difference at this volume.

### 8.4 SNS

| Topic | Purpose | Demo subscription(s) |
| --- | --- | --- |
| `alert-topic` | Per-email triage outcomes (§7.1), `alert_type` ∈ {urgent, needs_review, none} | Two email subscriptions with filter policies: "urgent-ops" (`alert_type=["urgent"]`), "needs-review" (`alert_type=["needs_review"]`) — both to Mike's address for demo |
| `ops-alarms` | Infrastructure-level signals: DLQ-depth alarm (§4.4), Lambda #1 async on-failure destination (§5.5), CloudWatch sentiment-anomaly alarm (§8.9) | One email subscription, no filter policy — everything here is actionable |

Both topics use default AWS-managed encryption (no CMK, consistent with §6). Email subscriptions require one-time confirmation (click the link AWS sends) — a manual demo setup step, not something Terraform can fully automate.

### 8.5 DynamoDB — `EmailTriageResults`

| Setting | Value |
| --- | --- |
| Partition key | `email_id` (String) — no sort key |
| Billing mode | On-demand (PAY_PER_REQUEST) |
| TTL attribute | `ttl` (Number, epoch seconds) = `received_at` + 90 days |
| Encryption | AWS-owned default (no CMK) |

Attributes (all non-key attributes are schemaless under DynamoDB's model — listed here for documentation):

| Attribute | Type | Set by | Notes |
| --- | --- | --- | --- |
| `email_id` | S | Lambda #1 | partition key, = SES `messageId` |
| `received_at` | S (ISO 8601) | Lambda #1 | |
| `from_address` | S | Lambda #1 | |
| `subject` | S | Lambda #1 | |
| `raw_s3_key` | S | Lambda #1 | pointer back to §8.1 |
| `category` | S | Lambda #2 | one of the 6 FR4 categories, or `unclassified` (FR17/DR7) |
| `urgency` | S | Lambda #2 | `high` \| `medium` \| `low` |
| `urgency_override_applied` | BOOL | Lambda #2 | true if DR4 fired |
| `sentiment` | S | Lambda #2 | `positive` \| `negative` \| `constructive` \| `unknown` (DR7) |
| `confidence` | S | Lambda #2 | `high` \| `medium` \| `low` |
| `review_status` | S | Lambda #2 | `auto_processed` \| `needs_review` |
| `suggested_reply` | S or NULL | Lambda #2 | |
| `feature_tags` | L (list of S) | Lambda #2 | only populated when `category=feature_request` (FR6) |
| `pii_entities_detected` | N | Lambda #2 | count from §8.8 |
| `processed_at` | S (ISO 8601) | Lambda #2 | |
| `ttl` | N | Lambda #2 | see above |

This is the single table in the design — Lambda #2 writes one item per email (step 15), Lambda #3 only reads via `Scan` (step 24, doc02 §4 decision #4 covers why Scan-and-filter rather than a GSI).

### 8.6 API Gateway

| Setting | Value | Notes |
| --- | --- | --- |
| API type | REST API (v1) | needed for the `AuthorizationType: AWS_IAM` per-method setting used in §6.5/FR16 |
| Route | `POST /insights` | only route in v1 |
| Authorization | `AWS_IAM` (SigV4) | FR16; unauthenticated → 403 |
| Stage | one stage, named to match the Terraform env (`dev`/`prod`, per `envs/` convention) | no blue/green or canary needs at demo scale |
| Integration | Lambda proxy (`AWS_PROXY`) | Lambda #3 returns `{statusCode, body}` directly — what lets it set 200 vs 503 itself (§7.3) |
| X-Ray tracing | enabled on the stage | FR13, step 28 |
| Execution logging | `INFO`-level access logs → CloudWatch Logs | feeds the FR14 dashboard (4xx/5xx counts, latency) |
| Throttling | account/stage default (10,000 req/s burst) | no custom usage plan — FR16 is IAM-auth-only, rate-limiting explicitly out of scope (doc01 §6) |

### 8.7 Bedrock

| Setting | Lambda #2 (classify, step 11-12) | Lambda #3 (synthesize, step 25-26) |
| --- | --- | --- |
| Model ID | `anthropic.claude-3-haiku-20240307-v1:0` (pinned, §6) | same |
| `temperature` | 0.0 | 0.3 |
| `max_tokens` | 512 (attempt 1) → 768 (Layer 2 retry, §4.3 — guards against truncated JSON) | 400 |

Rationale for the split: classification is a deterministic structured-output task — `temperature=0` minimizes run-to-run variance in `category`/`urgency`/`confidence`, which matters because DR4's keyword override and DR5's confidence-based routing both depend on stable model behavior. Synthesis (`/insights`) is a short natural-language summary where a small amount of variance (`0.3`) produces more readable prose without risking factual drift, since the input (projected DynamoDB records) is already a closed, deterministic dataset — temperature only affects phrasing, not which records get summarized.

No provisioned throughput or inference profile needed — Claude 3 Haiku is available on-demand in `us-east-1` (NFR6), invoked directly via `bedrock-runtime:InvokeModel`.

Prompt construction (system prompt = output-schema contract, user message = redacted body or projected records + question) is implementation detail for `06-development-plan.md`, not repeated here.

### 8.8 Comprehend

| Setting | Value | Notes |
| --- | --- | --- |
| API | `DetectPiiEntities` | synchronous, single call per email (step 10) |
| `LanguageCode` | `en` | hardcoded — multi-language is out of scope (doc01 §6) |
| Redaction rule | replace each returned entity's `[BeginOffset, EndOffset)` span with `[<Type>]` (e.g. `[NAME]`, `[EMAIL]`, `[PHONE]`) | applied for every entity type Comprehend returns — no type allowlist, simplest defensible "redact everything flagged" policy for a security demo |
| Score threshold | `Score >= 0.5` | Comprehend's own commonly-cited default for acting on a detection; entities below this are left as-is rather than over-redacting on low-confidence matches |
| Metric | `pii_entities_detected` = count of entities at/above the threshold | feeds FR11/§8.5 |

### 8.9 Observability Stack

**X-Ray** — Active tracing (`tracing_config { mode = "Active" }`) enabled on all 3 Lambdas and the API Gateway stage (§8.6). Lambda #1/#2 annotate their segment with `email_id` (FR13); Lambda #3's segment is unannotated (step 28 — `/insights` is an aggregate query, no single `email_id`).

**CloudWatch EMF** — namespace `ECHO`. Metrics emitted via structured log lines (no `PutMetricData`, §6):

| Metric | Emitted by | Dimensions | Used by |
| --- | --- | --- | --- |
| `SentimentCount` | Lambda #2 (step 16) | `sentiment` (positive/negative/constructive) | FR11, FR15 anomaly detection (on `negative`) |
| `PiiEntitiesDetected` | Lambda #2 (step 16) | — | FR11, §8.8 |
| `ClassificationFailure` | Lambda #2 (DR7) | — | FR17 |
| `AlertPublishFailure` | Lambda #2 (§4.5 DEGRADE) | — | reliability visibility |
| `SynthesisFailure` | Lambda #3 (DR8, §7.3) | — | FR12 reliability visibility |

**CloudWatch Dashboard (FR14)** — two widget groups:
- *Pipeline health*: per-Lambda invocations/errors/duration (all 3 functions), `email-triage-queue` + DLQ depth, API Gateway 4xx/5xx + latency
- *Triage metrics*: `SentimentCount` over time (stacked by dimension), `PiiEntitiesDetected`, and the three failure metrics above

**CloudWatch Anomaly Detection (FR15)** — anomaly detection model on `SentimentCount{sentiment=negative}`; alarm on "outside the anomaly band" → `ops-alarms` (§8.4). This is the same topic as the DLQ-depth alarm (§4.4) — both are infrastructure/health signals for the operator, distinct from the per-email `alert-topic`.

**CloudTrail** — single trail in `us-east-1` (NFR6), management events (read+write) enabled by default. Additionally, S3 data events (read+write) enabled for the `raw-emails` bucket only (§8.1) — this is the demoable control for "who/what accessed pre-redaction email content containing PII," directly supporting the security/compliance narrative in doc01's problem statement. Data-event logging is scoped to this one bucket (not account-wide) to keep volume/cost negligible.

GuardDuty, Security Hub, and Config are account-level posture tools (doc01 §5's security-finding severity scale) rather than resources in this pipeline's data flow — their configuration belongs in `04-infrastructure-spec.md`, not here.

## 9. Glossary / Acronyms

### 9.1 Project-Specific Reference Codes

| Code | Meaning | Defined in |
| --- | --- | --- |
| `ECHO` | **E**mail **C**lassification & **H**andling **O**rchestrator — this project's product name | doc01 (title) |
| `FR#` | Functional Requirement | doc01 §3 |
| `NFR#` | Non-Functional Requirement | doc01 §4 |
| `DR#` | Detection Rule | §3.1 |

### 9.2 AWS Services & Features

| Acronym | Meaning |
| --- | --- |
| S3 | Simple Storage Service |
| SES | Simple Email Service |
| SQS | Simple Queue Service |
| SNS | Simple Notification Service |
| IAM | Identity and Access Management |
| KMS | Key Management Service |
| CMK | Customer Master Key (a KMS-managed encryption key — this design uses none, §6) |
| SSE | Server-Side Encryption (`SSE-S3`, `SSE-SQS` = AWS-managed key variants) |
| AES256 | Advanced Encryption Standard, 256-bit (the cipher behind SSE-S3) |
| DLQ | Dead Letter Queue (SQS) |
| GSI | Global Secondary Index (DynamoDB) |
| TTL | Time To Live (DynamoDB item auto-expiry / S3 lifecycle expiration) |
| VPC | Virtual Private Cloud |
| ENI | Elastic Network Interface |
| NAT (Gateway) | Network Address Translation |
| ECR | Elastic Container Registry |
| SSM | Systems Manager (specifically, Parameter Store) |
| ARN | Amazon Resource Name |
| SigV4 | Signature Version 4 — AWS's request-signing protocol, used for `AWS_IAM`-authorized API Gateway calls (FR16) |
| EMF | Embedded Metric Format — CloudWatch's structured-log metric format (§6, §8.9) |
| CIS | Center for Internet Security — benchmark referenced by Security Hub findings (doc01 §5) |

### 9.3 General Technical Terms

| Acronym | Meaning |
| --- | --- |
| API | Application Programming Interface |
| REST | Representational State Transfer |
| HTTP | Hypertext Transfer Protocol |
| JSON | JavaScript Object Notation |
| SDK | Software Development Kit |
| PII | Personally Identifiable Information |
| LLM | Large Language Model |
| AI | Artificial Intelligence |
| MIME | Multipurpose Internet Mail Extensions — the raw email format parsed in step 4 |
| MX record | Mail Exchange record — the DNS record that points a domain at SES (NFR6) |
| PK | Partition Key (DynamoDB) |
| ISO 8601 | Date/time string format used throughout (e.g. `2026-06-13T14:32:05Z`) |
| QA | Quality Assurance |
| TPS | Transactions Per Second |
| OOM | Out Of Memory |
