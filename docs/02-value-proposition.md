# 02 - Value Proposition

> **ECHO** (Email Classification & Handling Orchestrator) — an automated email triage, classification, and insights pipeline.

## 1. Why Not the AWS Console?

If a support lead just used the AWS console, SES, and S3 directly, the system would provide **storage and visibility into individual objects**, but zero **processing, judgment, or aggregation**. Every one of the following is a manual, unscalable human step:

| Limitation | What the console gives you instead |
| ---------- | ------------------------------------ |
| **No classification** | Raw `.eml` files sitting in an S3 bucket — someone has to open and read each one to figure out category/urgency/sentiment |
| **No PII redaction** | Full email content (names, account numbers, phone numbers) is visible to anyone browsing the bucket, with no enforced redaction step before that text gets pasted into an AI tool for help drafting a reply |
| **No alerting** | An "urgent" email (outage, billing dispute) sits in S3 indefinitely until someone happens to check — no push notification |
| **No reply drafts** | Every response is written from scratch |
| **No aggregate insights** | "What are the top 3 requested features this month?" requires manually opening and tallying every email by hand |
| **No metrics/trends** | Sentiment volume over time, PII-exposure counts — none of this exists without manual counting |
| **No correlation/tracing** | If something goes wrong, there's no single `email_id` to follow through ingest → classify → alert — just disconnected S3/CloudWatch console views |

## 2. Why Not Existing AWS-Native Tools?

Four AWS-native products could be pitched as "you didn't need to build this." Each is examined for cost, complexity, and fit.

### 2.1 Amazon Connect (+ Cases + Contact Lens)

| | Connect-based | ECHO |
| --- | --- | --- |
| Cost | Per-minute/contact + Cases (~$1.20/case) + Contact Lens analytics — real recurring cost even at low volume | Near $0 — serverless pay-per-invocation |
| Complexity | Full contact-center setup: instance, routing profiles, queues, flows, Cases domain, Contact Lens config | A handful of Lambdas + SQS/SNS/DynamoDB |
| Fit | Email channel support is limited and built for human-agent routing, not automated AI triage; no native Bedrock classification or insights Q&A | Purpose-built for AI-driven triage + insights |

**FR-by-FR: could Connect (+ add-ons) cover every feature in this system?**

| Our FR | Connect coverage |
| --- | --- |
| FR1 Email ingest | **Partial** — Connect's email channel (GA 2024) can receive email, creates a "contact" |
| FR2 Parse + unique ID | **Yes** — every contact gets a Contact ID |
| FR3 PII redaction | **Weak** — Contact Lens redaction is built for voice/chat transcripts; email-body redaction isn't a clean native fit |
| FR4 Category/urgency/sentiment/confidence | **Partial** — Contact Lens gives sentiment + rules-based categories (keyword/criteria rules, not LLM zero-shot); no self-reported "confidence" concept exists |
| FR5 Suggested reply draft | **Partial** — Amazon Q in Connect (agent-assist) can draft responses, but requires its own Knowledge Base setup + per-user cost, and it's agent-facing, not an automated stored field |
| FR6 Feature-tag extraction | **No** — not a Connect concept at all |
| FR7 Keyword override on urgency | **Partial** — rules can drive routing priority, but "LLM assigns, then a rule force-overrides" isn't a native pattern |
| FR8 Persist classification record | **No** — Connect stores Contact Trace Records/Cases, not a custom schema; you'd still build your own DynamoDB sink |
| FR9 Low-confidence → review routing | **No** — Connect routes by queue/skill, not by model confidence |
| FR10 Urgent alert | **Partial** — via priority queue + a Lambda hook in the contact flow (i.e., you're writing Lambda anyway) |
| FR11 Sentiment/PII metrics | **Partial** — Contact Lens surfaces sentiment trends; PII-entity-count is custom |
| FR12 `/insights` NL Q&A | **No** — would need Amazon Q Business (separate product, separate cost) |
| FR13 X-Ray tracing | **No** — Connect flows use their own contact-flow logs, not X-Ray |
| FR14/15 CloudWatch dashboard + anomaly detection | **Partial** — Connect publishes operational metrics (queue depth etc.); our specific triage metrics still need custom EMF |
| FR16 IAM auth on `/insights` | **N/A** — no native endpoint to protect |

**The bigger point:** even the "Partial" rows require stacking multiple paid add-ons — Contact Lens, Q in Connect (+ its own Knowledge Base), Cases — on top of core Connect, *and* writing custom Lambda integrations for everything in the "No" column anyway. You don't avoid building Lambda/Bedrock glue; you also pay for and configure a full contact-center platform underneath it.

There's also a philosophical mismatch: **Connect assumes a human agent handles every contact**, with AI as an assist layer. ECHO is the inverse — fully automated by default, with humans pulled in only as an *exception* (`needs_review` / `urgent`). That inversion is core to the value story.

### 2.2 Amazon Q Business (covers just the `/insights` piece)

| | Q Business | ECHO's `/insights` API |
| --- | --- | --- |
| Cost | ~$3-20/user/month — recurring per-user cost, breaks "near $0" | Pennies per Bedrock call at demo scale |
| Complexity | Set up a Q Business app + sync DynamoDB data via S3 (no native DynamoDB connector) | One Lambda, one Scan, one Bedrock call |
| Fit | Solves only the Q&A layer — still need the entire triage/PII/alerting pipeline underneath | Covers the full pipeline end-to-end |

### 2.3 Amazon Kendra + QnABot

| | Kendra+QnABot | ECHO's `/insights` API |
| --- | --- | --- |
| Cost | Kendra Developer Edition starts ~$810/month — blows the $200 credit in days | ~$0 |
| Complexity | Index + data source connectors + QnABot (Lex+Lambda+Kendra) deployment | One Lambda |
| Fit | Built for searching large unstructured document corpora (FAQs/manuals) | Right-sized for small structured aggregate queries |

### 2.4 Comprehend Custom Classification (vs Bedrock, for the triage step specifically)

| | Comprehend Custom Classification | Bedrock (Claude Haiku) |
| --- | --- | --- |
| Cost | Real-time endpoint billed hourly (~$0.50/hr min ≈ $360/mo if always-on) | ~$0.0003/email |
| Complexity | Needs a labeled training dataset (we have none — cold start) | Zero-shot prompt, no training data |
| Fit | Gives sentiment only; category/urgency/confidence/reply-draft/feature-tags need separate models | One prompt returns the full structured classification |

Note: `DetectPiiEntities` (Comprehend's pre-trained PII API, no training needed) stays in our design either way — this comparison is specifically Custom Classification vs Bedrock for triage.

## 3. What ECHO Adds

Synthesizing across the four alternatives above, here's the differentiation story:

1. **Automation-first, exception-based human routing** — the system handles every email by default; a human is pulled in only when confidence is low or urgency is high. Connect inverts this — it assumes an agent handles every contact, with AI as an assist layer.

2. **One LLM call → full structured classification** — category, urgency, sentiment, confidence, reply draft, and feature tags from a single Bedrock prompt. The alternatives need multiple bolted-on services to approximate this: Contact Lens for sentiment, a custom-trained Comprehend classifier for category, Q in Connect + a Knowledge Base for reply drafts — each with its own setup and bill.

3. **PII redaction as a pipeline gate, not a transcript afterthought** — `DetectPiiEntities` runs *before* anything reaches the LLM, with the count surfaced as a metric. Contact Lens redaction targets voice/chat transcripts after the fact.

4. **Defense-in-depth urgency** — LLM judgment plus a deterministic keyword override (FR7). None of the alternatives natively express "trust the model, but verify."

5. **Natural-language aggregate insights at near-zero cost** — `/insights` answers free-form questions over triage history via DynamoDB + Bedrock synthesis. Q Business (~$3-20/user/mo) and Kendra (~$810/mo min) solve a fraction of this for orders of magnitude more cost.

6. **End-to-end request tracing + custom metrics, correlated by `email_id`** — X-Ray + EMF + CloudTrail. Connect's internal flow logging isn't X-Ray-based and doesn't expose this granularity.

7. **IAM-authenticated analytics with a dedicated least-privilege caller role** — a concrete, demoable security pattern that off-the-shelf products abstract away entirely.

8. **Near-$0 at demo scale, serverless pay-per-invocation** — every alternative considered carries either per-user/month, per-case, or high fixed-minimum costs.

9. **A cohesive showcase of the full required service list** — Lambda, SQS, SNS, API Gateway, X-Ray, CloudWatch (EMF + anomaly detection), CloudTrail, IAM/SigV4, Comprehend, Bedrock, DynamoDB, S3, SES — one coherent pipeline, not isolated console clicks. For ECHO's purpose, the "value" includes demonstrating breadth of AWS competency to an interviewer.

## 4. Tooling Decisions

Non-obvious choices made during architecture design, with the trade-off that would flip each decision:

| # | Decision (chosen) | Alternative | When the alternative is better |
| --- | --- | --- | --- |
| 1 | SES → S3 (`raw-emails/`) → S3 event triggers Lambda#1 | SES receipt rule invokes Lambda#1 directly with inline MIME | Lower latency, fewer resources — but loses the durable raw artifact for audit/reprocessing, and SES's inline-content limit (~150KB) risks truncating emails with attachments |
| 2 | Comprehend `DetectPiiEntities` (redaction gate) + Bedrock (classification) — hybrid | Bedrock-only (ask the model to redact, or skip redaction) | If you fully trust the model provider with raw PII and don't need an auditable, demoable redaction metric — saves one call/latency |
| 3 | SQS + Lambda event-driven chaining | Step Functions state machine | Complex branching/retry, or long-running human-in-the-loop steps (task-token callbacks for `needs_review`) — but adds cost/complexity for what's a linear pipeline, and SQS+DLQ is itself a required competency to show |
| 4 | DynamoDB Scan+filter, single un-pre-filtered scan for `/insights` | GSI per query pattern, or OpenSearch Serverless (RAG) | Production scale (thousands+ records) where full Scan gets slow/costly, or semantic search over unstructured body text is needed — but OpenSearch Serverless carries a high monthly minimum that blows the demo budget |
| 5 | Single SNS topic + `alert_type` filter policies | Separate topics/queues per alert type | Different alert types need fundamentally different IAM boundaries, or 10+ alert categories make filter policies unwieldy — neither applies at our 3-value scale |
| 6 | CloudWatch EMF (structured log → auto-parsed metric) | Explicit `cloudwatch:PutMetricData` calls | Metrics from a source not already writing to CloudWatch Logs, or very high metric volume where log-ingestion cost exceeds PutMetricData cost — EMF needs zero extra IAM perms and keeps metric + context together |
| 7 | DynamoDB on-demand billing | Provisioned capacity (Always-Free 25 RCU/WCU tier) | Steady, predictable, higher-volume traffic — provisioned within the always-free tier could be literally $0; on-demand avoids capacity planning for our unpredictable, near-zero traffic |
| 8 | API Gateway `AWS_IAM` authorizer + dedicated `ECHOInsightsCaller` role | API key + usage plan | External callers without AWS IAM creds, or per-caller rate-limiting quotas needed — explicitly out of scope for v1 (FR16) |
