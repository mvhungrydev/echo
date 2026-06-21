# 06 - Development Plan

> **ECHO** (Email Classification & Handling Orchestrator) — an automated email triage, classification, and insights pipeline.

> Status: All 8 docs reviewed and approved (2026-06-14). Phase 1 scaffold created. Next: Phase 2 (`shared-utils` layer, `retry_config.py`) in Teaching Mode — Mike writes, `pmc` for full code.

## Overview

doc06 is a story-by-story **blueprint** — not a code dump. It's sequenced for TDD (Red → Green → Refactor, per doc08). Phase 1 is procedural scaffolding; Phases 2-5 follow doc03's component breakdown (shared-utils layer → Lambda #1 → #2 → #3); Phase 6 implements the 12 Terraform modules from doc04; Phase 7 is the first real deploy + demo.

Every Phase 2+ story includes:

- **Background** — AWS API behavior, async/encoding quirks, moto support, prerequisite concepts
- **Test** — what each test covers and why, helper functions, boundary conditions
- **Implementation** — function signatures, ordered logic steps, response shapes, normalization, design rationale — described in prose/pseudocode, **not** runnable code blocks

The actual code gets written during the build phase, one story at a time, in **Teaching Mode** (global CLAUDE.md): Mike writes it with guidance, unless he says `pmc <thing>`.

| Phase | Scope                                                                                                     | Depth                                                                                |
| ----- | --------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| 1     | Scaffold: repo structure, config files, CI workflow, empty Terraform modules                              | Procedural                                                                           |
| 2     | `shared-utils` Lambda layer — `retry_config.py` only (`GENERAL_CONFIG`/`BEDROCK_CONFIG`, doc03 §4.2/§5.2) | Full                                                                                 |
| 3     | Lambda #1 — Ingest                                                                                        | Full                                                                                 |
| 4     | Lambda #2 — Triage                                                                                        | Full                                                                                 |
| 5     | Lambda #3 — Insights                                                                                      | Full                                                                                 |
| 6     | Terraform modules (12)                                                                                    | Lighter — implement against doc04's spec, `terraform validate`/`checkov` as the gate |
| 7     | Bootstrap deploy + demo                                                                                   | Procedural/runbook                                                                   |

## Phase 1 — Scaffold

Procedural — creates the directory structure and config files that Phases 2-7 build into.

### 1.1 Directory Tree

```
smart_email/
├── .github/
│   └── workflows/
│       └── deploy.yml              # doc05 §7 — copied in verbatim
├── .gitignore                       # Python, Terraform, AWS creds, macOS, IDE
├── requirements-dev.txt             # pytest, moto, coverage (doc08)
├── pytest.ini                       # doc08
├── src/
│   ├── lambda_ingest/               # Phase 3
│   ├── lambda_triage/               # Phase 4
│   ├── lambda_insights/             # Phase 5
│   └── layers/
│       └── shared_utils/
│           └── requirements.txt     # boto3/botocore + aws-xray-sdk pinned (doc05 §4.4, FR13)
├── tests/                            # mirrors src/ — kept separate so test files
│   ├── __init__.py                  # tests/ + every subdir below is a package —
│   ├── lambda_ingest/               # aren't bundled into Lambda .zip/layer    avoids pytest basename collisions
│   │   └── __init__.py              # artifacts by doc05 §4.6's packaging step (3x test_handler.py, doc08 §3)
│   ├── lambda_triage/
│   │   └── __init__.py
│   ├── lambda_insights/
│   │   └── __init__.py
│   ├── layers/
│   │   └── shared_utils/
│   │       └── __init__.py
│   └── conftest.py                  # shared fixtures (doc08)
└── infra/
    ├── modules/
    │   ├── s3/{main.tf,variables.tf,outputs.tf}
    │   ├── ses/{...}
    │   ├── sqs/{...}
    │   ├── sns/{...}
    │   ├── dynamodb/{...}
    │   ├── iam/{...}
    │   ├── lambda/{...}
    │   ├── apigateway/{...}
    │   ├── cloudwatch/{...}
    │   ├── cloudtrail/{...}
    │   ├── security-baseline/{...}
    │   └── demo-data/{...}
    └── envs/
        ├── dev/
        │   ├── main.tf
        │   ├── backend.tf            # doc04 §7.1
        │   ├── variables.tf
        │   ├── terraform.tfvars.example
        │   └── outputs.tf
        └── prod/
            ├── main.tf
            ├── backend.tf            # doc04 §7.2
            ├── variables.tf
            ├── terraform.tfvars.example
            └── outputs.tf
```

Each `modules/*/` 3-file skeleton is created empty (`# TODO: Phase 6`) — populated in Phase 6. Each `tests/<component>/` directory starts empty — its first test file is written as the Red step of that component's first Phase 2-5 story.

### 1.2 Scaffold Checklist

| #   | Item                                                                                          | Source        |
| --- | --------------------------------------------------------------------------------------------- | ------------- |
| 1   | `src/lambda_{ingest,triage,insights}/`, `src/layers/shared_utils/`                            | doc03 §5.2    |
| 2   | `tests/lambda_{ingest,triage,insights}/`, `tests/layers/shared_utils/`, `tests/conftest.py`   | doc08         |
| 3   | `src/layers/shared_utils/requirements.txt` (pinned boto3/botocore + aws-xray-sdk)             | doc05 §4.4    |
| 4   | `requirements-dev.txt` (pytest, moto, coverage)                                               | doc08         |
| 5   | `pytest.ini`                                                                                  | doc08         |
| 6   | `infra/modules/<12 modules>/{main,variables,outputs}.tf` — empty, 3-file convention           | doc04 §1.2    |
| 7   | `infra/envs/{dev,prod}/{main.tf,backend.tf,variables.tf,terraform.tfvars.example,outputs.tf}` | doc04 §1.2/§7 |
| 8   | `.github/workflows/deploy.yml`                                                                | doc05 §7      |
| 9   | `.gitignore` (Python, Terraform, AWS creds, macOS, IDE)                                       |               |

## Phase 2 — `shared-utils` Layer: `retry_config.py`

A single story. Per doc03 §5.2, the layer's **application code** contains **only** `retry_config.py` — two `botocore.config.Config` objects (`GENERAL_CONFIG`, `BEDROCK_CONFIG`) consumed by every boto3 client across all 3 Lambdas (doc03 §4.2). `requirements.txt` additionally pins `aws-xray-sdk` (doc03 §8.9, FR13) — not used by `retry_config.py` itself, but available at `/opt/python` for Lambda #1/#2's `handler.py` to import (Phases 3.2/4.5) for the `email_id` segment annotation.

### 2.1 `retry_config.py`

**Background**

- `botocore.config.Config` is passed as `boto3.client("s3", config=GENERAL_CONFIG)` — it controls connection/read timeouts and retry behavior for that client.
- `retries={"mode": "adaptive", "max_attempts": 3}` — `max_attempts` includes the _initial_ attempt (so 3 = 1 try + 2 retries). `adaptive` mode adds exponential backoff+jitter **and** client-side rate limiting once throttling is observed — stronger than `"standard"` mode, appropriate for AWS API throttling (doc03 §4.2).
- Two configs, differing only in `read_timeout` (doc03 §4.2's table):
  - `GENERAL_CONFIG` — Comprehend/DynamoDB/SNS/S3/SQS: `max_attempts=3`, `connect_timeout=3`, `read_timeout=5`, `mode="adaptive"`
  - `BEDROCK_CONFIG` — Bedrock: same except `read_timeout=10` (LLM calls run longer)
- **This story has zero AWS dependency** — `Config` objects are pure data, constructed with no network calls. No `@mock_aws` needed. It's a deliberate first TDD story: proves the `tests/` ↔ `src/` import wiring (pytest path config, doc08) works before any AWS-touching code is written.
- Runtime import path: as a Lambda layer, this file lands at `/opt/python/retry_config.py` (extracted from the layer zip's `python/` dir, doc05 §4.6). Locally, `tests/layers/shared_utils/test_retry_config.py` imports it as `from retry_config import GENERAL_CONFIG, BEDROCK_CONFIG` — doc08's `pytest.ini`/`conftest.py` must put `src/layers/shared_utils/` on `sys.path` for this bare import to resolve in both contexts.
- **Not part of this story** — Lambda #3's "tightened" Bedrock config (`max_attempts=2`, `read_timeout=5s`, doc03 §4.2 exception/§7.3) is function-specific, built inline in `lambda_insights/synthesize.py` (Phase 5). It must **not** reuse the name `BEDROCK_CONFIG` — flagging now so Phase 5 picks a distinct name (e.g., `INSIGHTS_BEDROCK_CONFIG`).

**Test** (`tests/layers/shared_utils/test_retry_config.py`)

| #   | Test                                                                | Why it matters                                                                                                                                                                                               |
| --- | ------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1   | `GENERAL_CONFIG` is a `botocore.config.Config` instance             | Catches a typo'd import or wrong return type                                                                                                                                                                 |
| 2   | `GENERAL_CONFIG.retries == {"max_attempts": 3, "mode": "adaptive"}` | Pins the exact retry dict doc03 §4.2 specifies                                                                                                                                                               |
| 3   | `GENERAL_CONFIG.connect_timeout == 3` and `.read_timeout == 5`      | Pins timeout values used by 5 of the 6 AWS services in this design                                                                                                                                           |
| 4   | `BEDROCK_CONFIG` is a `botocore.config.Config` instance             | Same as #1, for the second object                                                                                                                                                                            |
| 5   | `BEDROCK_CONFIG.retries == {"max_attempts": 3, "mode": "adaptive"}` | Pins retry dict for Bedrock                                                                                                                                                                                  |
| 6   | `BEDROCK_CONFIG.connect_timeout == 3` and `.read_timeout == 10`     | Pins the 10s Bedrock read timeout                                                                                                                                                                            |
| 7   | `GENERAL_CONFIG.read_timeout != BEDROCK_CONFIG.read_timeout`        | **Boundary case**: the two configs differ in exactly one field. This regression test catches the most likely future mistake — copy-pasting one config over the other and forgetting to change `read_timeout` |

No fixtures, no moto, no `conftest.py` dependency — this test file is self-contained.

**Implementation**

`src/layers/shared_utils/retry_config.py` — two module-level constants, both `botocore.config.Config` instances. No functions, no classes, no imports beyond `from botocore.config import Config`.

| Constant         | `retries`                                 | `connect_timeout` | `read_timeout` |
| ---------------- | ----------------------------------------- | ----------------- | -------------- |
| `GENERAL_CONFIG` | `{"max_attempts": 3, "mode": "adaptive"}` | `3`               | `5`            |
| `BEDROCK_CONFIG` | `{"max_attempts": 3, "mode": "adaptive"}` | `3`               | `10`           |

Design decisions:

- Module-level constants, not factory functions (`get_general_config()`) — `Config` objects are immutable value objects, and `boto3.client(..., config=GENERAL_CONFIG)` doesn't mutate the `Config` it's given, so every client across all 3 Lambdas can safely share the same two instances.
- Usage pattern each later Lambda story will follow (not built here): `boto3.client("dynamodb", config=GENERAL_CONFIG)`, `boto3.client("bedrock-runtime", config=BEDROCK_CONFIG)`.

## Phase 3 — Lambda #1 — Ingest

### 3.1 `mime_parser.py`

**Background**

- `email.parser.BytesParser(policy=email.policy.default).parsebytes(raw_bytes)` parses the raw `.eml` bytes into an `EmailMessage`. With `policy.default`, header access (`msg["subject"]`, `msg["from"]`) returns objects that `str()` into **fully RFC 2047-decoded** text — no manual `decode_header` needed for non-ASCII subjects.
- `msg.get_body(preferencelist=("plain", "html"))` walks multipart/alternative and multipart/mixed trees and returns the best-matching part (or `None` if no body part exists — e.g., an attachment-only email).
- `.get_content()` on that part transparently decodes `Content-Transfer-Encoding: base64` / `quoted-printable` and returns a `str` — this is what satisfies doc03 step 4's "handles multipart/base64/quoted-printable" requirement; we don't hand-roll decoding.
- `From: "Jane Doe" <jane@example.com>` — `email.utils.parseaddr(str(msg["from"]))` returns `(realname, email_address)`; we keep only `[1]`.
- Zero AWS dependency — same as Phase 2, no `@mock_aws` needed. Test fixtures are built with stdlib's own `EmailMessage` (`.set_content()` / `.add_alternative()`) rather than hand-written raw strings, guaranteeing valid MIME.

**Test** (`tests/lambda_ingest/test_mime_parser.py`)

| #   | Test                                                                                 | Why it matters                                                                                |
| --- | ------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------- |
| 1   | Simple plain-text email → correct `from_address`, `subject`, `body`                  | Baseline happy path                                                                           |
| 2   | Multipart/alternative (plain + html) → `body` is the **plain** part                  | Confirms `preferencelist=("plain","html")` ordering                                           |
| 3   | `Content-Transfer-Encoding: base64` body → decoded to original text                  | Pins doc03's "handles base64" requirement                                                     |
| 4   | `Content-Transfer-Encoding: quoted-printable` body → decoded to original text        | Pins "handles quoted-printable"                                                               |
| 5   | RFC 2047 encoded-word subject (e.g. non-ASCII chars) → decoded readable string       | Confirms `policy.default` header decoding                                                     |
| 6   | `From: "Jane Doe" <jane@example.com>` → `from_address == "jane@example.com"`         | Confirms display-name stripping                                                               |
| 7   | **Boundary**: email with no body part (attachment-only) → `body == ""`, no exception | `get_body()` returning `None` is a real edge case that would otherwise raise `AttributeError` |

Helper: `build_eml(**kwargs) -> bytes` constructs test messages via `EmailMessage()` + `.set_content()`/`.add_alternative()`, returned via `.as_bytes()` — keeps fixtures realistic and short.

**Implementation**

`src/lambda_ingest/mime_parser.py` — one function, three stdlib imports (`from email import policy`, `from email.parser import BytesParser`, `from email.utils import parseaddr`).

`parse_email(raw_bytes: bytes) -> dict`

1. Parse: `BytesParser(policy=policy.default).parsebytes(raw_bytes)` → `msg` (an `EmailMessage`).
2. `from_address`: read `msg["from"]`. If the header exists, `parseaddr(str(msg["from"]))[1]` (the address half of the `(realname, email)` tuple); if absent, `""`.
3. `subject`: `str(msg["subject"])` if the header exists, else `""`.
4. `body`: `msg.get_body(preferencelist=("plain", "html"))` — if it returns a part, `.get_content()` on that part (transparently decodes base64/quoted-printable); if it returns `None` (attachment-only email), `""`.
5. Return `{"from_address": ..., "subject": ..., "body": ...}` — always exactly these 3 keys, always strings (never `None`).

### 3.2 `handler.py`

**Background**

- S3 event shape: `event["Records"][0]["s3"]["bucket"]["name"]` / `["object"]["key"]`. The key is **URL-encoded** by S3 (e.g., spaces → `+`) — must `urllib.parse.unquote_plus()` before use. Defensive, since real SES messageIds are alphanumeric and rarely need decoding, but this is the standard S3-event-handler pattern.
- `email_id` = SES messageId = the filename portion of the key (`raw-emails/<ses-message-id>` → split on the last `/`), per doc03 step 5 — **not** re-derived from MIME headers, so it's stable for the §4.6 idempotency guard.
- `s3.get_object()`'s `Body` is a `StreamingBody` — single-read, must call `.read()` to get bytes.
- `received_at` comes from the `get_object` response's `LastModified` field (a `datetime`, boto3-parsed already) → `.isoformat()`. No extra API call, and it reflects when SES actually wrote the object — closer to "received" than Lambda invocation time.
- **Poison-pill demo** (doc03 §4.5): a magic marker in the subject (`POISON_PILL_MARKER = "ECHO-POISON-PILL"`) causes the handler to **omit the `body` key** from the SQS payload — deliberately malformed input that makes Lambda #2 throw `KeyError` on every redelivery, demonstrating the DLQ path.
- **Module-level boto3 clients + moto timing**: `s3`/`sqs` clients are constructed at module import time (standard Lambda warm-start reuse pattern, per NFR1). For tests, `@mock_aws` must be active **before** these clients are constructed, or they'll attempt real AWS calls. Tests work around this with `importlib.reload(handler)` inside an active `mock_aws()` context — this is the "botocore patching" pattern doc08 needs to document centrally.
- Failure handling: Lambda #1 is invoked **async by S3** (not SQS) — if `handler()` raises, Lambda's built-in async retries (2 retries) + the on-failure destination (`ops-alarms` SNS, doc03 §5.5, wired in Terraform) handle it. **No try/except needed in `handler.py`** — let exceptions propagate (RAISE).
- **X-Ray annotation** (FR13, doc03 §8.9): Lambda's Active Tracing (enabled in Phase 6's Terraform) creates the invocation's segment automatically — application code attaches an `email_id` annotation to that segment via `aws_xray_sdk.core.xray_recorder.put_annotation("email_id", email_id)`. Outside Lambda (pytest), no segment exists; `xray_recorder.configure(context_missing="LOG_ERROR")` (set once at module import) makes `put_annotation` log-and-continue instead of raising `SegmentNotFoundException` — so this call needs no dedicated test fixture.
- Resolved in doc08 §4.4: `src/lambda_ingest/` is **not** added to `pytest.ini`'s global `pythonpath` (alongside Phase 2's `src/layers/shared_utils/`) — all 3 Lambdas have a same-named `handler.py`, so a global addition would create import collisions once `lambda_triage`/`lambda_insights` tests also run. Instead, the `ingest_handler` fixture uses `monkeypatch.syspath_prepend()` + `sys.modules.pop("handler", None)` to resolve `handler` to _this_ Lambda's file each test — mirroring `/var/task`'s per-Lambda isolation. `from mime_parser import parse_email` resolves via that same prepended path; `from retry_config import GENERAL_CONFIG` resolves via Phase 2's global `pythonpath` entry.

**Test** (`tests/lambda_ingest/test_handler.py`)

| #   | Test                                                                                                                                    | Why it matters                                                                                                       |
| --- | --------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| 1   | Happy path: plain-text email in S3 → SQS message has correct `email_id`, `from_address`, `subject`, `body`, `received_at`, `raw_s3_key` | Core data-flow correctness (doc03 steps 4-6)                                                                         |
| 2   | S3 key `raw-emails/<msgid>` → payload `email_id == "<msgid>"`                                                                           | Pins the idempotency-key derivation (§4.6 depends on this)                                                           |
| 3   | URL-encoded S3 key (e.g. `%20`/`+`) → still resolves the right object and `email_id`                                                    | S3 event key-encoding quirk                                                                                          |
| 4   | `received_at` equals `get_object()`'s `LastModified.isoformat()`                                                                        | Pins the timestamp source/format                                                                                     |
| 5   | Subject contains `POISON_PILL_MARKER` → SQS message is **missing** the `body` key                                                       | Demo fault-injection path (doc03 §4.5)                                                                               |
| 6   | Multipart email in S3 → `body` matches what `parse_email` would extract                                                                 | Confirms handler wiring to `mime_parser`, not re-testing its internals                                               |
| 7   | **Boundary**: SQS message body round-trips through `json.loads()`                                                                       | Catches serialization bugs (e.g., an un-stringified `datetime` breaking `json.dumps`)                                |
| 8   | `xray_recorder.put_annotation` (patched via `patch.object`) is called with `("email_id", "<msgid>")`                                    | FR13 — confirms the annotation call fires with the correct value, independent of whether a real X-Ray segment exists |

Fixtures (in `conftest.py`, doc08): `aws_credentials` (fake env vars, required even under moto); a fixture that creates the S3 bucket + SQS queue under `mock_aws()`, sets `TRIAGE_QUEUE_URL`, and yields `handler` reloaded via `importlib.reload()` inside that context.

**Implementation**

`src/lambda_ingest/handler.py`

Module-level setup:

- Imports: `json`, `os`, `unquote_plus` from `urllib.parse`, `boto3`, `parse_email` from `mime_parser`, `GENERAL_CONFIG` from `retry_config`, `xray_recorder` from `aws_xray_sdk.core`.
- Clients (constructed once at import time, for warm-start reuse): `s3 = boto3.client("s3", config=GENERAL_CONFIG)`, `sqs = boto3.client("sqs", config=GENERAL_CONFIG)`.
- `xray_recorder.configure(context_missing="LOG_ERROR")` — called once at module level (see Background's X-Ray annotation note).
- Constant: `POISON_PILL_MARKER = "ECHO-POISON-PILL"`.

`handler(event, context)`

1. `record = event["Records"][0]["s3"]` — S3 event notification shape.
2. `bucket = record["bucket"]["name"]`.
3. `key = unquote_plus(record["object"]["key"])` — S3 URL-encodes keys (e.g. spaces → `+`); must decode before use.
4. `email_id = key.rsplit("/", 1)[-1]` — the filename portion after the last `/` (the SES messageId). Immediately call `xray_recorder.put_annotation("email_id", email_id)` (FR13, doc03 §8.9).
5. `response = s3.get_object(Bucket=bucket, Key=key)`.
6. `raw_bytes = response["Body"].read()` — `Body` is a `StreamingBody`, single-read.
7. `received_at = response["LastModified"].isoformat()` — boto3 already parses `LastModified` into a `datetime`; no extra API call.
8. `parsed = parse_email(raw_bytes)` → `from_address`, `subject`, `body`.
9. Build `payload` — 6 keys: `email_id`, `from_address`/`subject`/`body` (from `parsed`), `received_at`, `raw_s3_key` (= `key`).
10. Poison-pill check: if `POISON_PILL_MARKER in parsed["subject"]`, delete the `body` key from `payload` — intentionally produces a malformed message so Lambda #2 throws `KeyError`, demonstrating the DLQ path (doc03 §4.5).
11. `sqs.send_message(QueueUrl=os.environ["TRIAGE_QUEUE_URL"], MessageBody=json.dumps(payload))`.

Design notes:

- `TRIAGE_QUEUE_URL` is the first Lambda environment variable introduced — Terraform's `lambda` module wires it from the `sqs` module's `queue_url` output (doc04 §1.3).
- No try/except — RAISE is the correct behavior per doc03 §5.5; Lambda's async on-failure destination is the safety net, not application code.

## Phase 4 — Lambda #2 — Triage

Per doc03 §5.2, this Lambda has 5 files. Six stories, ordered by complexity (no-AWS → single-AWS-call → orchestration): 4.1 `keyword_rules.py`, 4.2 `pii.py`, 4.3 `classify.py`, 4.4 `persist.py`, 4.5-4.6 `handler.py` (orchestration core, then alerting + metrics).

### 4.1 `keyword_rules.py` (FR7 / DR4)

**Background**

- Pure Python, zero AWS dependency (same "first story" pattern as Phase 2/3.1) — this IS the "hardcoded list constant in Lambda #2's shared code module" doc03 §3.2 refers to.
- Case-insensitive **substring** match (doc03 §3.2's explicit choice, not word-boundary) against the redacted body — a deliberate simplification, not a bug, even though it means e.g. "shutdown" would match the `down` keyword.
- `urgency_override_applied` must reflect whether DR4 _specifically_ fired — not just whether the final `urgency` is `"high"` (it could already be `"high"` from DR1 with no keyword match).

**Test** (`tests/lambda_triage/test_keyword_rules.py`)

| #   | Test                                                                                                                              | Why it matters                                                                                                                   |
| --- | --------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Text contains `"outage"` + `urgency="medium"` → `urgency="high"`, `override_applied=True`                                         | Core DR4 override                                                                                                                |
| 2   | Text contains `"charged twice"` (multi-word phrase) → override applied                                                            | Confirms multi-word phrases match, not just single words                                                                         |
| 3   | Text contains `"cancel my account"` → override applied                                                                            | Escalation/churn category                                                                                                        |
| 4   | Text contains `"DATA BREACH"` (mixed case) → override applied                                                                     | Case-insensitivity                                                                                                               |
| 5   | Text contains none of the keywords, `urgency="low"` → `urgency="low"`, `override_applied=False`                                   | No false positives                                                                                                               |
| 6   | `urgency="high"` already (DR1, no keyword match) → stays `"high"`, `override_applied=False`                                       | **Boundary**: distinguishes DR1 (model) from DR4 (override) — `override_applied` must not be "true just because urgency is high" |
| 7   | **Boundary**: keyword as substring of a larger word (e.g., text contains `"shutdown"`) → still matches `"down"`, override applied | Confirms implementation follows doc03's deliberate substring-match choice, not an accidental word-boundary regex                 |

No fixtures, no moto — self-contained, like `test_retry_config.py`.

**Implementation**

`src/lambda_triage/keyword_rules.py` — one constant, one function.

`ESCALATION_KEYWORDS` — a list of 10 lowercase phrases, from doc03 §3.2's 4 categories:

- Outage/access: `"down"`, `"outage"`, `"can't access"`, `"locked out"`
- Billing dispute: `"charged twice"`, `"double charged"`, `"unauthorized charge"`
- Escalation/churn: `"cancel my account"`, `"legal action"`
- Security: `"data breach"`

`apply_keyword_override(text: str, urgency: str) -> dict`

1. `text_lower = text.lower()` — case-insensitive matching.
2. `override_applied = any(keyword in text_lower for keyword in ESCALATION_KEYWORDS)` — substring match, deliberately not word-boundary (doc03 §3.2's explicit choice).
3. If `override_applied`: return `{"urgency": "high", "urgency_override_applied": True}`.
4. Else: return `{"urgency": urgency, "urgency_override_applied": False}` — passes the input `urgency` through unchanged.

Return shape: always exactly `{"urgency": str, "urgency_override_applied": bool}`.

### 4.2 `pii.py` (Comprehend `DetectPiiEntities` + redaction, FR3/DR6)

**Background**

- `comprehend.detect_pii_entities(Text=..., LanguageCode="en")` returns `{"Entities": [{"Score": float, "Type": "NAME"|"PHONE"|..., "BeginOffset": int, "EndOffset": int}, ...]}` — offsets are character positions in the **original** input text.
- Redaction must not corrupt offsets while rewriting the string. Approach: sort entities by `BeginOffset` ascending, then do a **single left-to-right pass** building a new string — copy `text[cursor:entity.BeginOffset]`, append `[<Type>]`, advance `cursor = entity.EndOffset`, repeat, then append the remaining tail. Since all offsets reference the _original_ string and we never mutate it in place, no shifting issue arises.
- Only entities with `Score >= 0.5` are redacted (doc03 §8.8 threshold) — sub-threshold entities are left as-is and don't count toward `pii_entities_detected`.
- **moto does not support Comprehend** — there's no `@mock_aws` coverage for `detect_pii_entities`. Tests instead `unittest.mock.patch.object(pii.comprehend, "detect_pii_entities", return_value=...)` directly on the already-imported client. This is simpler than Phase 3's moto-timing problem — no `importlib.reload` needed, since we're not relying on moto's endpoint interception at all. Flag for doc08: this is the "moto doesn't support this service" pattern, distinct from the "moto must activate before client construction" pattern.
- `comprehend` client uses `GENERAL_CONFIG` (Comprehend is in the 5-service general table, doc03 §4.2).

**Test** (`tests/lambda_triage/test_pii.py`)

| #   | Test                                                                                                                                                  | Why it matters                                                                 |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| 1   | One entity (`NAME`, Score=0.9) → text has `[NAME]` substituted, surrounding text intact                                                               | Core redaction                                                                 |
| 2   | Two non-overlapping entities → both redacted, text between/around preserved                                                                           | Multi-entity reconstruction                                                    |
| 3   | Entity with `Score=0.3` (below threshold) → left unredacted, not counted                                                                              | Pins the 0.5 threshold (§8.8)                                                  |
| 4   | No entities returned → `redacted_text == text`, `pii_entities_detected == 0`                                                                          | Happy path / feeds `PiiEntitiesDetected` metric (FR11)                         |
| 5   | `pii_entities_detected` counts only entities **at/above** threshold                                                                                   | Pins the metric source separately from the redaction itself                    |
| 6   | Entities returned **out of `BeginOffset` order** → redaction still correct                                                                            | Comprehend doesn't guarantee ordering — confirms we sort before reconstructing |
| 7   | **Boundary**: entity at `BeginOffset=0` and another at `EndOffset=len(text)` (start/end of string) → no `IndexError`, redaction correct at both edges | String-slicing edge cases                                                      |

**Implementation**

`src/lambda_triage/pii.py`

Module-level setup:

- Imports: `boto3`, `GENERAL_CONFIG` from `retry_config`.
- Client: `comprehend = boto3.client("comprehend", config=GENERAL_CONFIG)`.
- Constant: `PII_SCORE_THRESHOLD = 0.5`.

`redact_pii(text: str) -> dict`

1. `response = comprehend.detect_pii_entities(Text=text, LanguageCode="en")` → `response["Entities"]` is a list of `{"Score": float, "Type": str, "BeginOffset": int, "EndOffset": int}`.
2. Filter to entities at/above threshold: keep only entities where `Score >= PII_SCORE_THRESHOLD`.
3. Sort the filtered entities by `BeginOffset` ascending — Comprehend doesn't guarantee order.
4. Single left-to-right reconstruction pass: start `cursor = 0`, build a list of string parts; for each entity in sorted order, append `text[cursor:BeginOffset]` then `f"[{Type}]"`, then set `cursor = EndOffset`; after the loop, append `text[cursor:]`.
5. `redacted_text = "".join(parts)`.
6. Return `{"redacted_text": str, "pii_entities_detected": len(entities)}`.

Design note: offsets all reference the _original_ `text`, and the string is never mutated in place — only the `parts` list is built — so no offset-shifting issue arises even with multiple entities.

### 4.3 `classify.py` (Bedrock invoke + Layer 2 retry, FR4/FR5/FR6/FR17/DR7)

**Background**

- Claude on Bedrock via `bedrock-runtime.invoke_model(modelId=..., body=json.dumps({...}))` uses the Anthropic Messages format: `{"anthropic_version": "bedrock-2023-05-31", "max_tokens": ..., "temperature": ..., "system": "...", "messages": [{"role": "user", "content": "..."}]}`.
- **Double JSON decode**: `response["body"]` is a `StreamingBody` (same `.read()` quirk as S3) → `json.loads()` gives the Bedrock envelope `{"content": [{"type": "text", "text": "..."}]}`. That `text` field is itself a _string_ containing the model's JSON output — needs a **second** `json.loads()`. Each retry is a fresh `invoke_model` call with its own fresh `StreamingBody`, so there's no "read twice" issue across retries.
- **New design decision — category/sentiment enums** (doc01/doc03 establish the _fields_ FR4 requires but not the literal enum values; this story defines them):
  - `category`: `bug_report` | `feature_request` | `general_inquiry` | `billing` | `complaint` | `praise` (the "6 FR4 categories" doc03 §8.5 references), or `unclassified` (FR17)
  - `sentiment`: `positive` | `negative` | `constructive` (doc03 §8.5), or `unknown` (FR17)
  - `urgency`/`confidence`: `high` | `medium` | `low`
  - `feature_tags`: list of strings, only meaningful when `category="feature_request"` (FR6) — for other categories it's just `[]`, not separately validated
- **Layer 2 retry** (doc03 §4.3): attempt 1 uses `max_tokens=512`; if the model's `text` isn't valid JSON, OR is missing a required key, OR has an enum value outside the sets above → retry once with a corrective system prompt + `max_tokens=768` (doc03 §8.7 — guards against truncation). Exhausting both → FR17 degraded record + `classification_failed=True` (handler uses this flag to emit `ClassificationFailure`, DR7).
- **moto does not support `bedrock-runtime`** — same pattern as 4.2's Comprehend. Tests `patch.object(classify.bedrock, "invoke_model", ...)`.
- Uses Phase 2's `BEDROCK_CONFIG` (read*timeout=10s) — this is the \_general* Bedrock config, not Lambda #3's tightened §7.3 exception.

**Test** (`tests/lambda_triage/test_classify.py`)

| #   | Test                                                                                                                                                                                       | Why it matters                                                                                 |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------- |
| 1   | Valid JSON on attempt 1 → returns parsed dict, `classification_failed=False`, only 1 `invoke_model` call                                                                                   | Happy path                                                                                     |
| 2   | Invalid JSON on attempt 1, valid on attempt 2 → returns attempt-2 result; attempt 2 called with `max_tokens=768` and the corrective system prompt                                          | Confirms retry escalation (doc03 §8.7)                                                         |
| 3   | Invalid JSON on **both** attempts → returns FR17 degraded dict (`category="unclassified"`, `sentiment="unknown"`, `suggested_reply=None`, `feature_tags=[]`), `classification_failed=True` | DR7 fallback                                                                                   |
| 4   | Valid JSON but missing a required key (e.g. no `confidence`) → treated as invalid, triggers retry                                                                                          | Validation, not just `json.loads()` success                                                    |
| 5   | Valid JSON but `urgency="critical"` (not in `{high,medium,low}`) → treated as invalid, triggers retry                                                                                      | Enum validation                                                                                |
| 6   | `category="general_inquiry"`, response omits `feature_tags` → result has `feature_tags=[]` (not missing, not erroring)                                                                     | FR6 — tags only matter for `feature_request`, but the field must always exist for `persist.py` |
| 7   | **Boundary**: `response["body"]` is consumed via `.read()` exactly once per `invoke_model` call — verified via a `BytesIO`-backed mock that raises on a second `.read()`                   | Catches an accidental double-read bug on the retry path                                        |

Helper: `mock_bedrock_response(text: str) -> dict` returns `{"body": io.BytesIO(json.dumps({"content": [{"type": "text", "text": text}]}).encode())}` — `io.BytesIO` has `.read()`, simulating `StreamingBody` without needing botocore internals.

**Implementation**

`src/lambda_triage/classify.py`

Module-level setup:

- Imports: `json`, `boto3`, `BEDROCK_CONFIG` from `retry_config`.
- Client: `bedrock = boto3.client("bedrock-runtime", config=BEDROCK_CONFIG)`.
- `MODEL_ID = "anthropic.claude-3-haiku-20240307-v1:0"` (pinned, doc03 §6/§8.7).

Enum sets — the literal values this story defines (doc01/doc03 establish the _fields_ FR4 requires, not the enum values):

| Set                | Values                                                                               |
| ------------------ | ------------------------------------------------------------------------------------ |
| `VALID_CATEGORIES` | `bug_report`, `feature_request`, `general_inquiry`, `billing`, `complaint`, `praise` |
| `VALID_URGENCY`    | `high`, `medium`, `low`                                                              |
| `VALID_SENTIMENT`  | `positive`, `negative`, `constructive`                                               |
| `VALID_CONFIDENCE` | `high`, `medium`, `low`                                                              |

- `REQUIRED_FIELDS = {"category", "urgency", "sentiment", "confidence", "suggested_reply"}` — `feature_tags` is deliberately excluded (defaulted in `_try_parse`, step 3 below).
- `SYSTEM_PROMPT` — a string instructing the model to return ONLY a JSON object with the 6 fields above (the 5 required fields + `feature_tags`), describing each field's valid values/format.
- `RETRY_SYSTEM_PROMPT = SYSTEM_PROMPT + <one sentence: "your previous response wasn't valid JSON matching this schema; return ONLY the JSON object">`.
- `DEGRADED_RESULT` — the FR17 fallback dict: `{"category": "unclassified", "urgency": "medium", "sentiment": "unknown", "confidence": "low", "suggested_reply": None, "feature_tags": []}`.

`_invoke(body_text, system_prompt, max_tokens) -> str`

1. `bedrock.invoke_model(modelId=MODEL_ID, contentType="application/json", accept="application/json", body=json.dumps({...}))` — body follows the Anthropic Messages format: `anthropic_version="bedrock-2023-05-31"`, `max_tokens`, `temperature=0.0`, `system=system_prompt`, `messages=[{"role": "user", "content": body_text}]`.
2. `response_body = json.loads(response["body"].read())` — first decode: unwraps the Bedrock envelope `{"content": [{"type": "text", "text": "..."}]}`.
3. Return `response_body["content"][0]["text"]` — itself a JSON _string_ (the model's output), decoded again by the caller.

`_validate(parsed: dict) -> bool`

1. Check `REQUIRED_FIELDS.issubset(parsed.keys())` — all 5 required fields present.
2. Check `category`/`urgency`/`sentiment`/`confidence` are each in their respective `VALID_*` set.
3. Return `True` only if both checks pass.

`_try_parse(raw_text: str) -> dict | None`

1. `json.loads(raw_text)` — second decode. Catch `json.JSONDecodeError` → return `None`.
2. `_validate(parsed)` — if `False`, return `None`.
3. `parsed.setdefault("feature_tags", [])` — ensures the field always exists, even when the model omits it for non-`feature_request` categories.
4. Return `parsed`.

`classify(body_text: str) -> dict`

1. Attempt 1: `_invoke(body_text, SYSTEM_PROMPT, max_tokens=512)` → `_try_parse(...)`.
2. If attempt 1 parsed successfully: return `{**parsed, "classification_failed": False}`.
3. Attempt 2 (Layer 2 retry, doc03 §4.3/§8.7): `_invoke(body_text, RETRY_SYSTEM_PROMPT, max_tokens=768)` → `_try_parse(...)` — larger `max_tokens` guards against truncation.
4. If attempt 2 parsed successfully: return `{**parsed, "classification_failed": False}`.
5. Both attempts failed: return `{**DEGRADED_RESULT, "classification_failed": True}` — FR17 degraded record; the handler uses `classification_failed` to emit the `ClassificationFailure` metric (DR7).

Design note — double JSON decode: `response["body"]` is a `StreamingBody` (same `.read()`-once quirk as S3); `_invoke`'s first `json.loads` unwraps the Bedrock envelope, and `_try_parse`'s second `json.loads` unwraps the model's JSON text. Each retry is a fresh `invoke_model` call with its own fresh `StreamingBody`, so there's no "read twice" issue across attempts.

### 4.4 `persist.py` (idempotency `GetItem` + `PutItem`, FR8/§4.6)

**Background**

- **Resource API vs. client API** — design decision: `persist.py` uses `boto3.resource("dynamodb", config=GENERAL_CONFIG).Table(...)`, not `boto3.client("dynamodb")`. The resource API accepts/returns **native Python types** (`str`, `int`, `bool`, `list`, `None`) directly; the client API requires DynamoDB's typed-attribute format (`{"S": "..."}`, `{"N": "..."}`, `{"BOOL": True}`, `{"NULL": True}`) for every field. Given doc03 §8.5's item has 16 attributes of mixed types including a list (`feature_tags`) and a nullable field (`suggested_reply`), the resource API avoids a whole class of marshalling bugs. This is the only story using the resource API — every other AWS call in this design (S3, SQS, Comprehend, Bedrock, SNS) has a flat/simple payload better suited to the client API.

Note: `redacted_body` is stored as-is from `pii_result["redacted_text"]` — the email body with high-confidence PII entities substituted (e.g. `[SSN]`, `[PHONE]`). `NAME`, `EMAIL`, and `PHONE` are intentionally not redacted (`PII_TYPES_TO_SKIP`) so the stored body retains enough context for human review.
- `table.get_item(Key={"email_id": email_id})` → response **has no `"Item"` key at all** if not found (not `{"Item": None}`). Must use `response.get("Item")`, which correctly returns `None` when absent — this is the §4.6 idempotency check's return value.
- `ttl` (doc03 §8.5) = `received_at` (ISO8601, from Lambda #1) parsed via `datetime.fromisoformat()` → `.timestamp()` → epoch seconds (int) + 90 days (`90 * 86400 = 7,776,000`).
- `processed_at` = `datetime.now(timezone.utc).isoformat()`, set at write time — not passed in by the caller.
- Table name comes from `os.environ["DYNAMODB_TABLE_NAME"]` (doc04 §1.3: `lambda` module receives `dynamodb_table_name` from the `dynamodb` module's output) — same env-var pattern as Phase 3's `TRIAGE_QUEUE_URL`.
- **moto fully supports DynamoDB** — `@mock_aws` + `create_table(...)` works normally. But the module-level `table = dynamodb.Table(os.environ["DYNAMODB_TABLE_NAME"])` is still evaluated at import time, so the same `importlib.reload()`-inside-`mock_aws()` pattern from Phase 3.2 applies here too (env var must be set, and the table must exist, before reload).

**Test** (`tests/lambda_triage/test_persist.py`)

| #   | Test                                                                                                      | Why it matters                                                                                     |
| --- | --------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| 1   | `get_existing_record(email_id)` with no item written → returns `None`                                     | §4.6 idempotency check, "not found" path                                                           |
| 2   | `put_triage_record(record)` then `get_existing_record(email_id)` → returns the same data                  | Round-trip correctness                                                                             |
| 3   | `ttl` stored is `int(received_at.timestamp()) + 7_776_000`                                                | Pins the TTL derivation (doc03 §8.5)                                                               |
| 4   | `processed_at` is set to an ISO8601 string not present in the input `record`                              | Confirms it's computed at write time, not passed through                                           |
| 5   | `suggested_reply=None` and `feature_tags=[]` round-trip as `None`/`[]` (not stringified or dropped)       | Resource API's native-type handling for `NULL`/empty list                                          |
| 6   | `urgency_override_applied=True`/`False` round-trips as a Python `bool`, not `"True"`/`1`                  | Resource API `BOOL` handling                                                                       |
| 7   | **Boundary**: after `put_triage_record`, `get_existing_record` for the same `email_id` returns non-`None` | Confirms the "already processed → skip" branch of §4.6 would correctly short-circuit on redelivery |

**Implementation**

`src/lambda_triage/persist.py`

Module-level setup:

- Imports: `os`, `datetime`/`timezone` from `datetime`, `boto3`, `GENERAL_CONFIG` from `retry_config`.
- `dynamodb = boto3.resource("dynamodb", config=GENERAL_CONFIG)`.
- `table = dynamodb.Table(os.environ["DYNAMODB_TABLE_NAME"])` — table name comes from the Lambda env var wired in doc04 §1.3.
- `TTL_SECONDS = 90 * 24 * 60 * 60` (= `7_776_000`, 90 days, per doc03 §8.5).

`get_existing_record(email_id: str) -> dict | None`

1. `response = table.get_item(Key={"email_id": email_id})`.
2. Return `response.get("Item")` — the response has **no `"Item"` key at all** when not found (not `{"Item": None}`), so `.get()` is required to correctly yield `None`. This is the §4.6 idempotency check's return value.

`put_triage_record(record: dict) -> None`

1. `received_at = datetime.fromisoformat(record["received_at"])` — parse the ISO8601 string from Lambda #1.
2. `ttl = int(received_at.timestamp()) + TTL_SECONDS` — epoch seconds + 90 days.
3. Build `item = {**record, "processed_at": <now in UTC, ISO8601>, "ttl": ttl}` — `processed_at` is computed at write time, not passed in by the caller.
4. `table.put_item(Item=item)`.

Design note — resource API vs. client API: this is the only story using `boto3.resource(...)` rather than `boto3.client(...)`. The resource API accepts/returns native Python types (`str`, `int`, `bool`, `list`, `None`) directly; the client API would require DynamoDB's typed-attribute wrappers (`{"S": ...}`, `{"N": ...}`, `{"BOOL": ...}`, `{"NULL": True}`) for every one of the item's 16 attributes, including a list (`feature_tags`) and a nullable field (`suggested_reply`). Every other AWS call in this design (S3, SQS, Comprehend, Bedrock, SNS) has a flat/simple payload better suited to the client API.

### 4.5 `handler.py` — orchestration core (doc03 §2.1 steps 9-15)

**Background**

- SQS message body is the JSON string Lambda #1 sent (doc03 step 6): `message = json.loads(event["Records"][0]["body"])`. Batch size is 1 (doc03 §5.3), so `event["Records"]` always has exactly one element.
- **Idempotency guard** (doc03 §4.6): `persist.get_existing_record(message["email_id"])` runs first. If it returns non-`None`, the handler returns immediately — success, SQS deletes the message, and Comprehend/Bedrock/DynamoDB/SNS are never called. This protects against a prior invocation that fully succeeded but crashed before returning cleanly to SQS.
- `handler.py` doesn't construct its own boto3 clients for this story — it imports the sibling modules (`pii`, `classify`, `keyword_rules`, `persist`) and calls their functions. Each sibling module constructs its own client at import time (4.2-4.4). For tests, this means the `importlib.reload()` pattern from 3.2 must reload **all** of `persist`, `pii`, `classify`, and `handler` inside the active `mock_aws()`/`patch.object` context — reload order matters if any module imports another at module scope. Flag for doc08: this is the "reload chain" pattern, an extension of 3.2's single-module reload.
- **Double-mocking** (doc08 pattern, first introduced at scale here): tests combine `mock_aws()` (for `persist`'s DynamoDB calls — moto fully supports DynamoDB) with `patch.object(pii.comprehend, "detect_pii_entities", ...)` and `patch.object(classify.bedrock, "invoke_model", ...)` (moto doesn't support Comprehend/Bedrock) in the same fixture.
- **Poison-pill propagation** (doc03 §4.5 "Additional DLQ-eligible paths"): if Lambda #1 omitted `body` from the payload, `message["body"]` (step 3 below) raises `KeyError` immediately — before any AWS calls — and propagates uncaught. SQS redelivers up to `maxReceiveCount=2`, then routes to the DLQ.
- **`keyword_input` construction** (design decision made during this story): `message["subject"] + " " + pii_result["redacted_text"]` — not the raw, unredacted body. Rationale: FR7's escalation keywords (e.g., `"data breach"`, `"cancel my account"`) aren't PII themselves, so matching against the already-redacted text loses no detection capability, and reuses `redacted_text` instead of a second pass over the raw body.
- **X-Ray annotation** (FR13, doc03 §8.9): same pattern as Lambda #1 (3.2) — `xray_recorder.put_annotation("email_id", message["email_id"])` right after `message` is parsed (step 1 below), using the same module-level `xray_recorder.configure(context_missing="LOG_ERROR")` setup. Annotating before the idempotency check (step 2) means even short-circuited (already-processed) invocations are still traceable by `email_id`.

**Test** (`tests/lambda_triage/test_handler.py`, part 1 — orchestration)

| #   | Test                                                                                                                                                                      | Why it matters                                                                                |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| 1   | Happy path, `confidence="high"` → `persist.put_triage_record` called once with all 15 record fields correct, `review_status="auto_processed"`                             | Core orchestration correctness (doc03 steps 9-15)                                             |
| 2   | `persist.get_existing_record` returns an existing item → handler returns early; Comprehend/Bedrock/`put_triage_record` are **not** called                                 | §4.6 idempotency guard                                                                        |
| 3   | `confidence="low"` → `review_status="needs_review"`                                                                                                                       | DR5 routing                                                                                   |
| 4   | `classify.classify` returns `classification_failed=True` (DR7 degraded) → `review_status="needs_review"` regardless of `confidence`                                       | FR17/DR7 routing                                                                              |
| 5   | Redacted text contains an escalation keyword (DR4) and Bedrock returned `urgency="medium"` → persisted record has `urgency="high"`, `urgency_override_applied=True`       | Confirms keyword override wins over the model's urgency                                       |
| 6   | `category="feature_request"` with non-empty `feature_tags` from Bedrock → `feature_tags` persisted as-is; for any other category, `feature_tags=[]` persisted             | FR6 round-trip through the full chain                                                         |
| 7   | **Boundary**: SQS message missing the `body` key (poison pill) → `KeyError` raised and **not caught** by `handler()`                                                      | Confirms no defensive try/except was added that would swallow the doc03 §4.5 poison-pill path |
| 8   | **Boundary**: Comprehend returns zero entities → persisted record has `pii_entities_detected=0` (field present, not omitted)                                              | Feeds 4.6's `PiiEntitiesDetected` metric even on the "nothing found" case                     |
| 9   | `xray_recorder.put_annotation` (patched via `patch.object`) is called with `("email_id", message["email_id"])`, including on the idempotency short-circuit path (test #2) | FR13 — confirms every invocation is traceable by `email_id`, even ones that skip AWS calls    |

**Implementation**

`src/lambda_triage/handler.py` (story 4.5 covers steps 1-8; 4.6 below extends the same `handler()` with steps 9-12)

Module-level setup:

- Imports: `json`, plus the sibling modules as modules — `import pii`, `import classify`, `import keyword_rules`, `import persist` (importing as modules, not `from X import Y`, keeps each module's client — e.g. `pii.comprehend`, `classify.bedrock` — accessible for test patching), and `xray_recorder` from `aws_xray_sdk.core`.
- No new boto3 clients constructed directly for this story (4.6 adds `sns`).
- `xray_recorder.configure(context_missing="LOG_ERROR")` — called once at module level (same as 3.2's setup, doc03 §8.9/FR13).

`handler(event, context)`

1. `message = json.loads(event["Records"][0]["body"])`. Immediately call `xray_recorder.put_annotation("email_id", message["email_id"])` (FR13, doc03 §8.9).
2. Idempotency check: `existing = persist.get_existing_record(message["email_id"])`. If `existing is not None`, return (success — doc03 §4.6).
3. PII redaction: `pii_result = pii.redact_pii(message["body"])` → `{"redacted_text": str, "pii_entities_detected": int}`. (`message["body"]` is where the poison-pill `KeyError` surfaces.)
4. Classification: `classification = classify.classify(pii_result["redacted_text"])` → `{"category", "urgency", "sentiment", "confidence", "suggested_reply", "feature_tags", "classification_failed"}`.
5. Keyword override: `keyword_input = message["subject"] + " " + pii_result["redacted_text"]`; `override = keyword_rules.apply_keyword_override(keyword_input, classification["urgency"])` → `{"urgency", "urgency_override_applied"}`.
6. `review_status`: `"needs_review"` if `classification["confidence"] != "high"` or `classification["classification_failed"]`, else `"auto_processed"` (doc03 step 14, DR5/DR7).
7. Build `record` — 15 keys: `email_id`/`received_at`/`from_address`/`subject`/`raw_s3_key` (passthrough from `message`) + `category`/`sentiment`/`confidence`/`suggested_reply`/`feature_tags` (from `classification`) + `urgency`/`urgency_override_applied` (from `override`) + `review_status` (step 6) + `pii_entities_detected`/`redacted_body` (from `pii_result`).
8. `persist.put_triage_record(record)` (doc03 step 15).

Design notes:

- No try/except around steps 3/4/8 — RAISE per doc03 §4.5 (Comprehend, DynamoDB `PutItem`). Bedrock failures don't raise; `classify.py` degrades internally to `classification_failed=True`.
- 4.6 picks up immediately after step 8, in the same `handler()` — not a separate function.

### 4.6 `handler.py` — alerting + EMF metrics (doc03 §2.1 steps 16-18, §7.1, §8.9)

**Background**

- **EMF (CloudWatch Embedded Metric Format)**: a single structured JSON document printed to stdout via `print(json.dumps(...))`. It contains an `_aws.CloudWatchMetrics` block (`Namespace`, `Dimensions`, `Metrics` — names/units) plus top-level keys for each dimension's value and each metric's value. CloudWatch Logs' EMF processor parses this automatically into custom metrics under namespace `ECHO` (doc03 §8.9) — no `cloudwatch:PutMetricData` IAM permission needed (doc03 §6).
- **`_alert_type` precedence** (design decision made during Phase 4 drafting): `"urgent"` if `record["urgency"] == "high"`; else `"needs_review"` if `record["review_status"] == "needs_review"`; else `"none"`. `urgent` wins even if `review_status="needs_review"` is also true (e.g., DR4 fired _and_ confidence is low) — an urgent page is strictly more actionable than a review-queue item.
- **`_build_alert_body` — 3 shapes** (doc03 §7.1):
  - `urgent`: `email_id`, `alert_type`, `received_at`, `from_address`, `subject`, `category`, `urgency`, `urgency_override_applied`, `sentiment`, `confidence`, `suggested_reply`.
  - `needs_review`: same as `urgent` minus `urgency_override_applied`, plus a derived `review_reason` — `"classification_failed"` if `record["category"] == "unclassified"`, else `"low_confidence"`.
  - `none`: minimal — `email_id`, `alert_type`, `received_at`, `category`, `urgency`, `sentiment`, `confidence` only (no `from_address`/`subject`/`suggested_reply` — data-minimization, doc03 §7.1).
- **SNS publish + filter policies**: `sns.publish(TopicArn=..., Message=json.dumps(alert_body), MessageAttributes={"alert_type": {"DataType": "String", "StringValue": alert_type}})`. Subscriber filter policies match the **MessageAttribute**, not the body (doc03 §7.1) — a `none`-typed message simply isn't delivered to either filtered subscription.
- **DEGRADE on SNS failure** (doc03 §4.5): the `sns.publish` call is wrapped in try/except. On exception, set a flag, do **not** re-raise — the message is still considered successfully processed (avoids re-running paid Comprehend/Bedrock calls on redelivery just to retry a notification).
- **EMF metrics emitted** (doc03 §8.9): `SentimentCount` (dimension = `sentiment`), `PiiEntitiesDetected` (value = `record["pii_entities_detected"]`, always emitted even when `0`), `ClassificationFailure` (only if `classification["classification_failed"]`), `AlertPublishFailure` (only if the SNS publish failed) — all combined into **one** EMF document per invocation (simpler to test via a single captured stdout line; EMF supports multiple metrics per document).
- `sns = boto3.client("sns", config=GENERAL_CONFIG)` — SNS is in the 5-service general table (doc03 §4.2). This is `handler.py`'s **first own** client (4.5 only used sibling-module clients). moto fully supports SNS (`create_topic` under `mock_aws()`), same `importlib.reload()` consideration as 4.4's table.
- `os.environ["ALERT_TOPIC_ARN"]` — env var for the `alert-topic` ARN, wired by Terraform's `lambda` module from the `sns` module's output (doc04), same pattern as `TRIAGE_QUEUE_URL`/`DYNAMODB_TABLE_NAME`.

**Test** (`tests/lambda_triage/test_handler.py`, part 2 — alerting/metrics)

| #   | Test                                                                                                                                                                                                                    | Why it matters                                                    |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| 1   | `urgency="high"` → `_alert_type` returns `"urgent"`; SNS `MessageAttributes={"alert_type": {"DataType": "String", "StringValue": "urgent"}}`; body matches the §7.1 `urgent` shape including `urgency_override_applied` | Core DR1/DR4 alert path                                           |
| 2   | `urgency != "high"`, `review_status="needs_review"`, `category != "unclassified"` → `alert_type="needs_review"`, body's `review_reason="low_confidence"`                                                                | DR5 alert path                                                    |
| 3   | `classification_failed=True` (`category="unclassified"`) → `alert_type="needs_review"`, body's `review_reason="classification_failed"`                                                                                  | DR7 alert path                                                    |
| 4   | `urgency != "high"`, `review_status="auto_processed"` → `alert_type="none"`, body is the minimal shape (no `from_address`/`subject`/`suggested_reply`)                                                                  | DR2/DR3 alert path, data-minimization                             |
| 5   | **Boundary**: `urgency="high"` AND `review_status="needs_review"` simultaneously → `alert_type="urgent"` (not `"needs_review"`)                                                                                         | Pins the precedence order in `_alert_type`                        |
| 6   | EMF output includes `SentimentCount` with dimension value = `record["sentiment"]`                                                                                                                                       | FR11/FR15                                                         |
| 7   | `pii_entities_detected=0` → EMF still includes `PiiEntitiesDetected: 0` (not omitted)                                                                                                                                   | FR11 — distinguishes "checked, found nothing" from "didn't check" |
| 8   | `classification_failed=True` → EMF includes `ClassificationFailure`                                                                                                                                                     | FR17/DR7 metric                                                   |
| 9   | `sns.publish` raises → handler does **not** re-raise; EMF includes `AlertPublishFailure`; `persist.put_triage_record` (from 4.5) already succeeded before this point                                                    | DEGRADE per doc03 §4.5                                            |

Helper: a `capsys`-based assertion reads the single `print()`'d EMF JSON line and `json.loads()`s it for key/value checks.

**Implementation**

`src/lambda_triage/handler.py` (continued — steps 9-12, appended after 4.5's step 8)

Additional module-level setup:

- Add imports: `os`, `boto3`, `GENERAL_CONFIG` from `retry_config`.
- Add client: `sns = boto3.client("sns", config=GENERAL_CONFIG)`.

`_alert_type(record: dict) -> str`

1. If `record["urgency"] == "high"`: return `"urgent"`.
2. Elif `record["review_status"] == "needs_review"`: return `"needs_review"`.
3. Else: return `"none"`.

`_build_alert_body(record: dict, alert_type: str) -> dict`

1. Start with the 3 common fields: `email_id`, `alert_type`, `received_at`.
2. If `alert_type == "urgent"`: add `from_address`, `subject`, `category`, `urgency`, `urgency_override_applied`, `sentiment`, `confidence`, `suggested_reply`.
3. If `alert_type == "needs_review"`: add the same fields as `urgent` minus `urgency_override_applied`, plus `review_reason` = `"classification_failed"` if `record["category"] == "unclassified"` else `"low_confidence"`.
4. If `alert_type == "none"`: add only `category`, `urgency`, `sentiment`, `confidence`.
5. Return the assembled dict.

`_emit_emf(record: dict, classification_failed: bool, alert_publish_failed: bool) -> None`

1. Build one EMF document: `_aws.CloudWatchMetrics[0]` = `{"Namespace": "ECHO", "Dimensions": [["sentiment"]], "Metrics": [...]}` listing the metric names that appear in this document.
2. Top-level keys: `sentiment` (the dimension value, = `record["sentiment"]`), `SentimentCount=1`, `PiiEntitiesDetected=record["pii_entities_detected"]`, and conditionally `ClassificationFailure=1` (if `classification_failed`) and `AlertPublishFailure=1` (if `alert_publish_failed`).
3. `print(json.dumps(emf_document))`.

`handler(event, context)` — steps 9-12, appended after 4.5's step 8:

9. `alert_type = _alert_type(record)`.
10. `alert_body = _build_alert_body(record, alert_type)`.
11. `try: sns.publish(TopicArn=os.environ["ALERT_TOPIC_ARN"], Message=json.dumps(alert_body), MessageAttributes={"alert_type": {"DataType": "String", "StringValue": alert_type}})` — `except Exception:` set `alert_publish_failed = True`, do not re-raise (DEGRADE, doc03 §4.5).
12. `_emit_emf(record, classification["classification_failed"], alert_publish_failed)`.

Design notes:

- `_alert_type`'s precedence (`urgent` > `needs_review` > `none`) means `urgency="high"` always wins, even when `review_status="needs_review"` is also true — there's no need for both an urgent page and a review-queue entry for the same email.
- One EMF document per invocation, not one `print()` per metric — simpler to test (single `capsys`-captured line) and within EMF's spec (multiple metrics per document).
- `ALERT_TOPIC_ARN` env var — same wiring pattern as `TRIAGE_QUEUE_URL` (3.2) and `DYNAMODB_TABLE_NAME` (4.4).

---

## Phase 5 — Lambda #3 — Insights

Per doc03 §5.2, Lambda#3's package has 3 files: `handler.py`, `query.py`, `synthesize.py`. Three stories, in dependency order: 5.1 `query.py` (DynamoDB Scan + projection), 5.2 `synthesize.py` (Bedrock synthesis with a tightened, single-Lambda retry config), 5.3 `handler.py` (API Gateway request/response shaping that wires the other two together).

### 5.1 `query.py`

**Background**

- `table.scan(FilterExpression=..., ProjectionExpression=...)` — DynamoDB `Scan` reads the **entire table** and applies `FilterExpression` server-side, _after_ reading each item (still consumes read capacity for every item scanned, not just the matches). This is the documented tradeoff acknowledged in doc02 §4 decision #4: fine at demo scale (a handful of items), would need a GSI or an external index (e.g., OpenSearch) at production scale.
- `FilterExpression=Attr("review_status").eq("auto_processed")` — `Attr` comes from `boto3.dynamodb.conditions`, the same resource-API convenience 4.4's `persist.py` uses for its conditional `put_item`.
- `ProjectionExpression="category, urgency, sentiment, feature_tags, received_at"` — projects only these 5 fields onto the wire (doc03 step 24 / doc02 §4 data-minimization decision). None of these 5 attribute names appear on DynamoDB's reserved-words list, so no `ExpressionAttributeNames` aliasing is required.
- **Pagination**: `scan()` returns at most 1MB of data per call and includes a `LastEvaluatedKey` in the response if more items remain beyond that page. At demo scale a single call covers the whole table, but the function loops on `LastEvaluatedKey` regardless — this is standard `Scan` hygiene and the "quirk" this story's tests pin down.
- This module constructs its **own** `dynamodb`/`table` objects. `lambda_insights/query.py` is a separate deployment package from `lambda_triage/persist.py` (doc03 §5.2) — both point at the same `EmailTriageResults` table, but each Lambda reads `DYNAMODB_TABLE_NAME` from its own environment block (set independently in Phase 6's Terraform).
- moto fully supports `Scan` with `FilterExpression` and `ProjectionExpression` under `@mock_aws`. Because `table` is constructed at import time, tests use the same `importlib.reload(query)` pattern as 4.4 to ensure the mocked table exists before the module-level client is built.

**Test** (`tests/lambda_insights/test_query.py`)

| #   | Test                                                                                                                                                                                    | Why it matters                                                                      |
| --- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| 1   | Table contains a mix of `review_status="auto_processed"` and `"needs_review"` items → only the `auto_processed` items are returned                                                      | Core filter correctness (doc03 step 24)                                             |
| 2   | Returned items contain **only** the 5 projected fields — no `email_id`, `suggested_reply`, `from_address`, etc.                                                                         | Data-minimization (doc02 §4)                                                        |
| 3   | Empty table → returns `[]` with no exception                                                                                                                                            | Boundary — feeds `records_considered=0` downstream in 5.3                           |
| 4   | An item with `category="feature_request"` and a non-empty `feature_tags` list round-trips that list correctly through the projection                                                    | FR6 must survive into `/insights`                                                   |
| 5   | **Boundary**: `query.table.scan` mocked via `patch.object` with `side_effect=[<page 1 with LastEvaluatedKey>, <page 2 without>]` → both pages' `Items` are concatenated into the result | Pins the pagination loop; a demo-scale moto table alone wouldn't exercise this path |

**Implementation**

`src/lambda_insights/query.py`

Module-level setup:

- Imports: `boto3`, `Attr` from `boto3.dynamodb.conditions`, `GENERAL_CONFIG` from `retry_config`, `os`.
- `dynamodb = boto3.resource("dynamodb", config=GENERAL_CONFIG)`.
- `table = dynamodb.Table(os.environ["DYNAMODB_TABLE_NAME"])`.

`get_auto_processed_records() -> list[dict]`

1. Initialize `records = []` and `scan_kwargs = {"FilterExpression": Attr("review_status").eq("auto_processed"), "ProjectionExpression": "category, urgency, sentiment, feature_tags, received_at"}`.
2. Call `response = table.scan(**scan_kwargs)` and extend `records` with `response["Items"]`.
3. If `"LastEvaluatedKey"` is present in `response`, set `scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]` and repeat step 2; otherwise stop looping.
4. Return `records` — a list of dicts, each containing exactly the 5 projected keys.

Design note: `dynamodb`/`table` are constructed independently from 4.4's `persist.py`, pointing at the same table by name — this duplication is intentional, since each Lambda's deployment package must be self-contained (doc03 §5.2).

### 5.2 `synthesize.py`

**Background**

- Reuses the overall shape of 4.3's Bedrock calling pattern — `_invoke` → JSON-decode the Bedrock envelope → `_try_parse` the model's text → Layer 2 retry with a corrective system prompt on failure — but differs in three ways: a **tightened** Bedrock client config, different prompt/temperature/`max_tokens` values (doc03 §8.7), and a much simpler response schema (`{"answer": "<string>"}` vs. classify.py's 6-field schema).
- **`INSIGHTS_BEDROCK_CONFIG`** (doc03 §7.3 — the named exception to §4.2's shared-config table): `Config(retries={"max_attempts": 2, "mode": "adaptive"}, connect_timeout=3, read_timeout=5)`. Story 2.1 flagged that this config must **not** reuse the shared layer's `BEDROCK_CONFIG` name. Design decision for this story: `INSIGHTS_BEDROCK_CONFIG` is defined **locally in `synthesize.py`**, not added to `retry_config.py` — doc03 §5.2 scopes the shared layer to "only" `GENERAL_CONFIG`/`BEDROCK_CONFIG`, and this config is a single-client, single-Lambda exception with no reuse case elsewhere.
- doc03 §8.7 (already locked): `temperature=0.3` (vs. classify.py's `0.0`) and `max_tokens=400`. Rationale: synthesis produces short natural-language prose over an already-fixed, deterministic record set — a little variance improves readability without affecting _which_ records get summarized (unlike classify.py, where determinism matters for the structured output).
- `MODEL_ID` — the same pinned `anthropic.claude-3-haiku-20240307-v1:0` as classify.py, but **redefined locally** here. doc03 §5.2's directory tree has no shared constants module beyond `retry_config.py`.
- **Response schema** is just `{"answer": "<string>"}`. `records_considered` — the other field in the final `/insights` response (doc03 §7.2) — is **not** part of the model's output; it's `len()` of the records list, computed in 5.1's `query.py` and merged in by 5.3's `handler.py`.
- **Empty `records` list is a valid input.** If `query.get_auto_processed_records()` returns `[]`, `synthesize()` is still called — there's no special-cased early return. The system prompt instructs the model to say so in its `answer` (e.g., "No triage data is available yet"), keeping the "no data yet" case inside the normal 200 response.
- moto doesn't support `bedrock-runtime` — same `patch.object(synthesize.bedrock, "invoke_model", ...)` pattern as 4.3, including the `io.BytesIO`-backed mock `"body"` (StreamingBody is single-read).

**Test** (`tests/lambda_insights/test_synthesize.py`)

| #   | Test                                                                                                                                                                     | Why it matters                                                                                            |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------- |
| 1   | Valid `{"answer": "..."}` JSON on attempt 1 → returns `{"answer": "...", "synthesis_failed": False}`; only 1 `invoke_model` call made                                    | Happy path                                                                                                |
| 2   | Invalid JSON on attempt 1, valid on attempt 2 → returns the attempt-2 result; attempt 2 is invoked with `RETRY_SYSTEM_PROMPT`                                            | Layer 2 retry (doc03 §4.3)                                                                                |
| 3   | Invalid JSON on **both** attempts → returns `{"answer": None, "synthesis_failed": True}`                                                                                 | DR8 fallback — 5.3's handler turns this into HTTP 503                                                     |
| 4   | Valid JSON but `"answer"` is missing or not a string → treated as invalid, triggers the retry                                                                            | Validation goes beyond `json.loads()` succeeding                                                          |
| 5   | `records=[]` → Bedrock is still invoked (not short-circuited); the serialized prompt's `records` field is `[]`                                                           | Confirms the "no data → model says so" design (doc03 step 25)                                             |
| 6   | `invoke_model` is called with `temperature=0.3` and `max_tokens=400`                                                                                                     | Pins doc03 §8.7's synthesis-specific values, distinct from classify.py's                                  |
| 7   | **Boundary**: `INSIGHTS_BEDROCK_CONFIG.retries == {"max_attempts": 2, "mode": "adaptive"}`, `.read_timeout == 5`, and it is a **different object** from `BEDROCK_CONFIG` | Regression test in the spirit of 2.1's test #7 — pins that the tightened config exists and stays distinct |

Helper: reuses 4.3's `mock_bedrock_response(text: str) -> dict` helper for building the mocked `invoke_model` return value.

**Implementation**

`src/lambda_insights/synthesize.py`

Module-level setup:

- Imports: `json`, `boto3`, `Config` from `botocore.config`.
- `INSIGHTS_BEDROCK_CONFIG = Config(retries={"max_attempts": 2, "mode": "adaptive"}, connect_timeout=3, read_timeout=5)` — defined here, not imported from `retry_config`.
- `bedrock = boto3.client("bedrock-runtime", config=INSIGHTS_BEDROCK_CONFIG)`.
- `MODEL_ID = "anthropic.claude-3-haiku-20240307-v1:0"`.
- `SYSTEM_PROMPT` — instructs the model: given a JSON list of triage records and a question, return ONLY `{"answer": "<string>"}` that answers the question using the records provided; if the records list is empty, say that no data is available yet.
- `RETRY_SYSTEM_PROMPT = SYSTEM_PROMPT` plus a corrective sentence reiterating the exact required JSON shape, same pattern as 4.3's `RETRY_SYSTEM_PROMPT`.

`_invoke(records: list[dict], question: str, system_prompt: str) -> str`

1. Build the user message content as a single string combining both inputs, e.g. `f"Records: {json.dumps(records)}\n\nQuestion: {question}"`.
2. Call `bedrock.invoke_model(modelId=MODEL_ID, contentType="application/json", accept="application/json", body=json.dumps({"anthropic_version": "bedrock-2023-05-31", "max_tokens": 400, "temperature": 0.3, "system": system_prompt, "messages": [{"role": "user", "content": user_content}]}))`.
3. `response_body = json.loads(response["body"].read())` — first decode, unwraps the Bedrock envelope.
4. Return `response_body["content"][0]["text"]` — the model's raw text, a second-decode candidate.

`_try_parse(raw_text: str) -> dict | None`

1. `json.loads(raw_text)`, catching `json.JSONDecodeError` → return `None` on failure.
2. Valid only if the parsed value has an `"answer"` key whose value is a `str`.
3. Return `{"answer": parsed["answer"]}` if valid, else `None`.

`synthesize(records: list[dict], question: str) -> dict`

1. Attempt 1: `_invoke(records, question, SYSTEM_PROMPT)`, then `_try_parse(...)` the result.
2. If valid: return `{"answer": parsed["answer"], "synthesis_failed": False}`.
3. Attempt 2 (Layer 2 retry): `_invoke(records, question, RETRY_SYSTEM_PROMPT)`, then `_try_parse(...)` the result.
4. If valid: return `{"answer": parsed["answer"], "synthesis_failed": False}`.
5. If both attempts failed: return `{"answer": None, "synthesis_failed": True}` — 5.3's handler turns this into HTTP 503 plus the `SynthesisFailure` EMF metric (DR8).

Design note: `synthesize()` mirrors `classify()`'s "two attempts, then a `*_failed` flag in the return dict rather than raising" shape (4.3) — the Layer 2 retry pattern stays consistent across both Bedrock-calling Lambdas even though their schemas, prompts, and configs differ.

### 5.3 `handler.py`

**Background**

- **API Gateway Lambda proxy integration** (`AWS_PROXY`, doc03 §8.6): `event["body"]` arrives as a JSON **string**, not a dict — the handler must `json.loads(event["body"])` to read `{"question": "..."}` (doc03 §7.2). The return value must itself be a dict shaped `{"statusCode": int, "body": <JSON string>, "headers": {...}}` — this is what lets the Lambda choose between 200 and 503 (doc03 §7.3) rather than relying on API Gateway's default status-code mapping.
- **Orchestration**: `query.get_auto_processed_records()` (5.1) → `synthesize.synthesize(records, question)` (5.2) → shape the response per doc03 §7.2 (success) or §7.3 (failure).
- **`records_considered`** = `len(records)`, computed once and included in **both** the 200 and 503 response bodies (doc03 §7.2: included even on a "no data" answer, so the caller can distinguish "nothing has been processed yet" from "synthesis failed").
- **503 is not a catch-all.** doc03 §7.3's HTTP 503 `{"error": "synthesis_unavailable", "records_considered": N}` is specifically the outcome when Bedrock synthesis exhausts its Layer 2 retry (`synthesis_failed=True` from 5.2). A DynamoDB `Scan` failure (step 3 below) is a genuine infrastructure problem and is **not** caught — it RAISEs, the same "let infrastructure failures propagate" pattern used throughout Phases 3-4. An uncaught exception here surfaces to the caller as API Gateway's generic 502, which is intentionally distinct from the application-level 503.
- **Timeout / X-Ray** (doc03 §5.4, step 28): the 28s Lambda timeout and Active Tracing (with no `email_id` annotation, since `/insights` is an aggregate query with no single email to annotate) are Lambda _configuration_, set in Phase 6's Terraform — not application code. 5.2's `INSIGHTS_BEDROCK_CONFIG` is what bounds worst-case Bedrock time to ~21.5s, leaving ~6.5s of headroom under that 28s ceiling.
- **`SynthesisFailure` EMF metric** (doc03 §8.9, DR8) has no dimensions (unlike 4.6's `SentimentCount`), and is emitted only on the 503 path.
- Same double-mocking as Phase 4.5/4.6: moto (`mock_aws`) for DynamoDB via `query`, `patch.object` for Bedrock via `synthesize`; both sibling modules are imported as modules (`import query`, `import synthesize`) so tests can patch their attributes.
- No idempotency guard — `/insights` is a synchronous, read-only request with no SQS at-least-once-delivery concern.

**Test** (`tests/lambda_insights/test_handler.py`)

| #   | Test                                                                                                                                                                                                                                                                         | Why it matters                                                                                            |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| 1   | Happy path: `event["body"]` is a JSON string containing a question, records exist, Bedrock returns a valid `{"answer": ...}` → `statusCode=200`, and `body` decodes to `{"answer": "...", "records_considered": N}` where `N` matches the number of records `query` returned | Core contract (doc03 §7.2)                                                                                |
| 2   | `synthesize.synthesize` returns `synthesis_failed=True` → `statusCode=503`, `body` decodes to `{"error": "synthesis_unavailable", "records_considered": N}`, and a `SynthesisFailure` EMF line is printed                                                                    | DR8 / §7.3                                                                                                |
| 3   | `query.get_auto_processed_records()` returns `[]` → `statusCode=200`, `records_considered=0`, and `answer` reflects Bedrock's "no data yet" response                                                                                                                         | Boundary — confirms "no data yet" ≠ "synthesis failed"                                                    |
| 4   | `event["body"]` is passed as a JSON **string** (e.g. `'{"question": "..."}'`) → handler `json.loads`s it before reading `"question"`                                                                                                                                         | API Gateway proxy-integration shape                                                                       |
| 5   | Response dict has exactly the keys `statusCode`, `body`, `headers`, and `body` is a `str` (via `json.dumps`), not a raw dict                                                                                                                                                 | Confirms the proxy-integration return contract                                                            |
| 6   | **Boundary**: `query.table.scan` raises (mocked `ClientError`) → the exception propagates **uncaught**, not converted to a 503                                                                                                                                               | Distinguishes infrastructure failure (→ API Gateway 502) from synthesis failure (→ application 503, §7.3) |
| 7   | On the 200 path, no `SynthesisFailure` EMF line is printed                                                                                                                                                                                                                   | Confirms the metric is conditional on the 503 path only                                                   |

**Implementation**

`src/lambda_insights/handler.py`

Module-level setup:

- Imports: `json`, and sibling modules `import query`, `import synthesize` (module-level imports, same test-patchability pattern as 4.5).

`_emit_synthesis_failure_emf() -> None`

1. Build one EMF document: `_aws.CloudWatchMetrics[0]` = `{"Namespace": "ECHO", "Dimensions": [[]], "Metrics": [{"Name": "SynthesisFailure", ...}]}` — no dimensions (doc03 §8.9).
2. Top-level key: `SynthesisFailure=1`.
3. `print(json.dumps(emf_document))`.

`handler(event, context)`

1. `request_body = json.loads(event["body"])`.
2. `question = request_body["question"]`.
3. `records = query.get_auto_processed_records()` (doc03 step 24).
4. `records_considered = len(records)`.
5. `result = synthesize.synthesize(records, question)` (doc03 steps 25-26).
6. If `result["synthesis_failed"]` is `False`, return `{"statusCode": 200, "body": json.dumps({"answer": result["answer"], "records_considered": records_considered}), "headers": {"Content-Type": "application/json"}}`.
7. Otherwise, call `_emit_synthesis_failure_emf()`, then return `{"statusCode": 503, "body": json.dumps({"error": "synthesis_unavailable", "records_considered": records_considered}), "headers": {"Content-Type": "application/json"}}`.

Design notes:

- No try/except around step 3 — RAISE, per the same "infrastructure failure propagates" pattern as Phases 3-4. API Gateway's generic 502 covers this case, kept distinct from the application-level 503.
- `records_considered` (step 4) is computed once and reused in both branches of steps 6/7, avoiding a second `Scan`.
- This is the simplest of the 3 Lambda handlers — no env vars of its own (5.1 and 5.2's modules each own their env vars and clients), no SQS, no idempotency guard, no alert publish.

---

## Phase 6 — Terraform Modules (12)

Built in the dependency order from doc04 §1.3. Each module's resource list, variable/output names, and notable config are already fully specified in doc04 §1.2/§2 — this phase doesn't restate them. Each story below adds what doc04 doesn't cover: build-order quirks within a module's `main.tf` (internal resource references, `data` sources), expected `checkov` findings and whether to fix or suppress (with a documented reason, per doc05 §4's IaC-scan gate), and any new design questions surfaced while writing the HCL.

**The TDD-equivalent for Terraform** (doc05 §4's gates, run on every push):

- **Red** = `terraform validate` fails (syntax error, undefined reference, type mismatch), or `checkov` flags an unaddressed finding.
- **Green** = `terraform validate` passes; `terraform plan` produces the expected resource list with no unexpected `(known after apply)` on values that should be static; `checkov` either passes cleanly or has a documented `#checkov:skip=<ID>: <reason>` for findings that are deliberate design decisions already justified in doc03/doc04.
- **Refactor** = simplify `main.tf` (e.g. collapsing repeated argument blocks) without changing `terraform plan`'s output.

No `terraform apply` happens in Phase 6 — that's Phase 7, against `envs/dev` only (doc04 §1.3's "only `envs/dev` is deployed" decision).

Story format: **Scope** (doc04 pointer) → **Inputs → Outputs** → **Build order** (internal dependencies / data sources) → **Validation** (checkov expectations) → **Design notes** (anything new, not already in doc04).

### 6.1 `s3`

**Scope**: doc04 §2 row 1 — `raw-emails` bucket: `aws_s3_bucket` + `_server_side_encryption_configuration` (SSE-S3/AES256) + `_public_access_block` (all 4 on) + `_versioning` (disabled) + `_lifecycle_configuration` (90-day expiration) + `_policy` (allows `ses.amazonaws.com` `PutObject`, conditioned on `aws:SourceAccount`).

**Inputs → Outputs**: `variables.tf` = `env`, `region`. `outputs.tf` = `bucket_id`, `bucket_arn`, `bucket_name` — consumed by `ses`, `iam`, `lambda`, `cloudtrail` (doc04 §1.3 row 1).

**Build order**: this is the dependency root — zero references to other modules' outputs. The bucket policy's `aws:SourceAccount` condition needs the account ID, which comes from `data.aws_caller_identity.current.account_id` — the project's first `data` block (no variable for account ID exists, per doc04 §6).

**Validation**:

- `checkov` will likely flag `CKV_AWS_18` (S3 access logging not enabled) and `CKV_AWS_21` (versioning) — both are deliberate decisions already justified in doc03 §8.1 (demo-scale cost tradeoff; versioning intentionally disabled). Suppress both with `#checkov:skip=<ID>: <reason>` comments pointing at doc03 §8.1, rather than "fixing" them.
- `terraform validate` should pass cleanly — single self-contained module, the first one written, so it also establishes the `main.tf`/`variables.tf`/`outputs.tf` convention the rest follow.

**Design notes**: first use of `data "aws_caller_identity" "current"` — every later module that needs the account ID (e.g., `iam`'s OIDC trust policy, doc05 §5.3) reuses this pattern within its own `main.tf` rather than passing the account ID as a variable.

### 6.2 `ses`

**Scope**: doc04 §2 rows 2-3 — receipt rule set (`aws_ses_receipt_rule_set` + `aws_ses_active_receipt_rule_set`) + receipt rule (`aws_ses_receipt_rule`, S3 action → `raw-emails/` prefix, spam/virus scan enabled).

**Inputs → Outputs**: `variables.tf` = `bucket_name` (from `s3`), `ses_recipient_address` (doc04 §6). `outputs.tf` = none — terminal module (doc04 §1.2).

**Build order**: `aws_ses_receipt_rule_set` must exist before `aws_ses_active_receipt_rule_set` (activates it by name) before `aws_ses_receipt_rule` (attaches to the rule set) — Terraform resolves this from the resource references themselves, no `depends_on` needed.

**Validation**:

- `terraform plan` should show the receipt rule's `bucket_name` argument as a known (non-computed) value, since `s3`'s `bucket_name` output isn't itself derived from a still-unknown ARN.
- `checkov` has limited SES-specific rules; nothing expected to fire here.

**Design notes — flag for Phase 7**: doc04 §2's resource table for this module lists only the receipt rule set/rule — it does **not** include `aws_ses_domain_identity` (domain verification). SES inbound receiving requires the recipient domain to be a verified identity in the region, separate from the MX record doc04 §2.1 already flags as a manual prerequisite. Before writing this module's `main.tf`, confirm whether domain verification (1) is also a manual one-time step (alongside the MX record) or (2) needs an `aws_ses_domain_identity` resource + a DNS TXT record added to this module's scope. Resolve this when 6.2 is actually built — don't block the rest of Phase 6 on it.

### 6.3 `sqs`

**Scope**: doc04 §2 rows 4-5 — `email-triage-queue` (`aws_sqs_queue`, `visibility_timeout_seconds=var.sqs_visibility_timeout`, `sqs_managed_sse_enabled=true`, `redrive_policy` → DLQ with `maxReceiveCount=var.sqs_max_receive_count`) + `email-triage-dlq` (`aws_sqs_queue` + `aws_sqs_queue_redrive_allow_policy`, `message_retention_seconds=1209600`, SSE-SQS).

**Inputs → Outputs**: `variables.tf` = `env`, `sqs_visibility_timeout`, `sqs_max_receive_count` (doc04 §6). `outputs.tf` = `queue_arn`, `queue_url`, `dlq_arn` — consumed by `iam`, `lambda`, `cloudwatch` (doc04 §1.3 row 3). Note: the DLQ-depth alarm (`cloudwatch`, 6.9) needs `dlq_arn` for its alarm dimension, not a `dlq_url` — doc04 §1.2's `outputs.tf` comment mentions `dlq_url` but §1.3's "key outputs" row only lists `dlq_arn`; export both, but only `dlq_arn` is load-bearing for 6.9.

**Build order**: the main queue's `redrive_policy` references `aws_sqs_queue.dlq.arn`, and the DLQ's `aws_sqs_queue_redrive_allow_policy` references `aws_sqs_queue.main.arn` back — a two-way attribute reference between two resources in the same `main.tf`. Terraform builds its dependency graph from these references (not declaration order), so this resolves fine; worth knowing going in, since "redrive policy points at the DLQ" + "redrive _allow_ policy points back at the source queue" is a common source of confusion when reading the HCL later.

**Validation**:

- `checkov`'s SQS encryption rule (`CKV_AWS_27`) should pass cleanly given `sqs_managed_sse_enabled=true` — a "Green via correct config," not a suppression, unlike 6.1/most of this phase.
- `terraform validate` — confirms `redrive_policy`/`redrive_allow_policy` are valid `jsonencode(...)` of `{maxReceiveCount=..., deadLetterTargetArn=...}` / `{redrivePermission="byQueue", sourceQueueArns=[...]}` — easy to typo a key name and have it silently accepted as a string.

**Design notes**: first module where two resources in the same `main.tf` reference each other's attributes — a concrete example that "the module is the unit of organization, not the file" (the global 3-file convention).

### 6.4 `sns`

**Scope**: doc04 §2 rows 6-7 — `alert-topic` (`aws_sns_topic` + 2× `aws_sns_topic_subscription` with filter policies `{"alert_type":["urgent"]}` / `{"alert_type":["needs_review"]}`, doc03 §7.1) + `ops-alarms` topic (`aws_sns_topic` + 1× unfiltered subscription).

**Inputs → Outputs**: `variables.tf` = `env`, `alert_email` (doc04 §6 — the same address subscribes to both topics). `outputs.tf` = `alert_topic_arn`, `ops_alarms_topic_arn` — consumed by `iam`+`lambda` (`alert_topic_arn`) and `cloudwatch` (`ops_alarms_topic_arn`) (doc04 §1.3 row 4).

**Build order**: both topics and their subscriptions are independent within this module — 4 sibling resource blocks, no internal ordering dependency.

**Validation**:

- `checkov`'s SNS KMS-encryption rule (`CKV_AWS_26`) will fire — doc03 §6 already decided "no KMS" for this project; suppress with `#checkov:skip=CKV_AWS_26: no KMS per doc03 §6, demo-scale cost tradeoff`.
- Not a `validate`/`plan`/`checkov` concern, but a real Phase 7 runbook item: `aws_sns_topic_subscription` with `protocol="email"` creates the subscription in `PendingConfirmation` state — `terraform apply` succeeds, but no alert/alarm actually delivers until the confirmation link in the inbox is clicked.

**Design notes**: the filter-policy JSON (`{"alert_type": ["urgent"]}` / `{"alert_type": ["needs_review"]}`) must match doc03 §7.1's `alert_type` values exactly — a typo here doesn't error, it just means the subscription silently never matches.

### 6.5 `dynamodb`

**Scope**: doc04 §2 row 8 / §3.1 — `EmailTriageResults` table (`aws_dynamodb_table`): PK `email_id` (S, no SK), `PAY_PER_REQUEST`, TTL enabled on `ttl`. doc04 §3.1 already gives this resource block close to verbatim — this module is mostly a copy-in, parameterizing only the table name.

**Inputs → Outputs**: `variables.tf` = `env` (table name = `EmailTriageResults-${var.env}`, doc04 §3.1). `outputs.tf` = `table_name`, `table_arn` — consumed by `iam`, `lambda`, `demo-data` (see design note below on doc04 §1.3's `apigateway` entry).

**Build order**: single resource, no internal dependencies — the simplest module in the project.

**Validation**:

- `checkov`'s point-in-time-recovery rule (`CKV_AWS_28`) will likely fire. Unlike 6.1/6.4's suppressions, this is a candidate to **fix** rather than suppress — a `point_in_time_recovery { enabled = true }` block is one line, adds no cost at `PAY_PER_REQUEST` demo scale beyond incidental backup storage, and isn't a tradeoff doc03/doc04 already made a call on. A "Green via fix" example, contrasting with 6.1/6.4's "Green via documented suppression."
- `terraform validate` — confirm the `ttl` block (`attribute_name`/`enabled`) syntax, and that the `attribute` list contains only `email_id` — doc04 §3.1 is explicit that all other item attributes are application-managed and never appear in Terraform.

**Design notes**: doc04 §1.3 row 5 lists `apigateway` as a consumer of `table_name`/`table_arn`, but doc04 §1.2's `apigateway/variables.tf` list has no DynamoDB inputs — none of `apigateway`'s resources (REST API, `ECHOInsightsCaller`, invoke permission) reference the table directly. Treat §1.3's row as the looser/aspirational list; when wiring `envs/dev/main.tf` (Phase 7), pass `dynamodb`'s outputs only to `iam`, `lambda`, and `demo-data`.

### 6.6 `iam`

**Scope**: doc04 §2 rows 9-12 — 3 Lambda execution roles (full inline policy JSON in doc03 §6.1-6.3) + GitHub OIDC provider + `ECHOGitHubActionsRole` (doc05 §5.2-5.4).

**Inputs → Outputs**: `variables.tf` = `s3_bucket_arn`, `sqs_queue_arn`, `dynamodb_table_arn`, `sns_alert_topic_arn`, `github_org`, `github_repo`, `env`, `region` (doc04 §1.2). `outputs.tf` = `lambda1/2/3_role_arn`, `github_actions_role_arn` — role ARNs consumed by `lambda` (6.7); `github_actions_role_arn` is also surfaced as an `envs/dev` output for doc05 §5.5's bootstrap step.

**Build order**:

- 3 execution roles = `aws_iam_role` ×3 + `aws_iam_role_policy` ×3 (inline policies, one per role) — each policy is a `jsonencode({...})` transcription of doc03 §6.1-6.3, with `<ACCOUNT_ID>` replaced by `data.aws_caller_identity.current.account_id` and `<RAW_EMAILS_BUCKET>`/queue/table/topic ARNs replaced by this module's input variables.
- GitHub OIDC chain: `data "tls_certificate" "github_oidc"` (doc05 §5.2) → `aws_iam_openid_connect_provider.github` → `aws_iam_role.github_actions` (trust policy doc05 §5.3, using `var.github_org`/`var.github_repo` + `data.aws_caller_identity.current.account_id` + the OIDC provider's own ARN) → `aws_iam_role_policy.github_actions` (12-statement permissions policy, doc05 §5.4).
- Second user of `data "aws_caller_identity" "current"` (first was 6.1) — every module needing the account ID declares its own `data` block; no cross-module account-ID variable exists.

**Validation**:

- `terraform validate` — each execution-role policy is a literal transcription of doc03 §6.1-6.3. Highest-risk typo: Lambda#2's policy has 7 statements total (SQS, Comprehend, Bedrock, DynamoDB, SNS, Logs, X-Ray) — easy to drop one. Cross-check statement counts against doc03 §6.2 as part of "Green."
- `checkov` will likely flag the `comprehend:DetectPiiEntities` and `xray:Put*` `Resource: "*"` statements (wildcard-resource findings, e.g. `CKV_AWS_111`/`CKV_AWS_107`-style). doc03 §6 already documents both as **AWS-imposed** — no resource-level permissions exist for these actions, so `Resource: "*"` isn't a choice. Suppress with `#checkov:skip=<ID>: AWS-imposed wildcard, doc03 §6`.
- `checkov` may also flag `ECHOGitHubActionsRole`'s broad `s3:*`/`dynamodb:*`/`lambda:*`/etc. statements vs. enumerated actions. doc05 §5.4 already documents the rationale (Terraform deployer needs full lifecycle management of resources it created, scoped to literal/`echo-*`/`ECHO*` resource names); suppress with a pointer to doc05 §5.4 rather than enumerating ~50 actions per service.
- `terraform plan` — `data.tls_certificate.github_oidc`'s `thumbprint_list` requires a live HTTPS request to `token.actions.githubusercontent.com` at plan time, not just an AWS API read. First `data` source in the project with an external network dependency — if that endpoint is unreachable, `plan` fails here, not just `apply`.

**Design notes**:

- Largest module by policy-statement count (~30 statements across 3 execution roles + the OIDC trust policy + the 12-statement deployer policy) — budget extra review time for transcription accuracy against doc03 §6 / doc05 §5.4.
- `ECHOInsightsCaller` and both resource-based invoke permissions (S3→Lambda#1, APIGW→Lambda#3) are deliberately **not** here (doc04 §1.1's cycle-avoidance rationale) — `ECHOInsightsCaller` lives in `apigateway` (6.8), both invoke permissions live in `lambda` (6.7).

### 6.7 `lambda`

**Scope**: doc04 §2 rows 13-15 — `shared-utils` layer (`aws_lambda_layer_version`, `retry_config.py` only, doc03 §5.2) + Lambda#1 (`aws_lambda_function` + `aws_s3_bucket_notification` + `aws_lambda_permission` for S3 invoke) + Lambda#2 (`aws_lambda_function` + `aws_lambda_event_source_mapping`, batch size 1) + Lambda#3 (`aws_lambda_function`, 28s timeout, doc03 §5.4).

**Inputs → Outputs**: `variables.tf` = `lambda{1,2,3}_role_arn` (from `iam`), `s3_bucket_id`/`s3_bucket_arn` (from `s3`), `sqs_queue_arn` (from `sqs`), `dynamodb_table_name` (from `dynamodb`), `sns_alert_topic_arn` (from `sns`), `env`, `region`, `lambda2_timeout`, plus `*_zip_path` variables for the 3 function packages and the layer (doc04 §6's `lambda_artifacts_dir`). `outputs.tf` = `layer_arn`, `lambda{1,2,3}_function_name`/`arn`/`invoke_arn` — consumed by `apigateway` (6.8) and `cloudwatch` (6.9).

**Build order**:

- `aws_lambda_layer_version` (shared-utils, from `${var.lambda_artifacts_dir}/shared_utils_layer.zip`) — no dependencies, build first.
- All 3 `aws_lambda_function` resources reference the layer's ARN in their `layers` argument and the matching `var.lambda{N}_role_arn`. All get `architectures = ["arm64"]`, `runtime = "python3.13"`, `handler = "handler.handler"`, `tracing_config { mode = "Active" }` (doc03 §5.1).
- Env vars per function (doc03 §5.2 / doc04 §3.2): Lambda#1 → `TRIAGE_QUEUE_URL`; Lambda#2 → `DYNAMODB_TABLE_NAME`, `ALERT_TOPIC_ARN`; Lambda#3 → `DYNAMODB_TABLE_NAME`.
- Lambda#1: `aws_s3_bucket_notification` on `var.s3_bucket_id` referencing `aws_lambda_function.ingest.arn`, plus `aws_lambda_permission` (S3 invoke, doc03 §6.4) with `source_arn = var.s3_bucket_arn` and `source_account = data.aws_caller_identity.current.account_id`. **Ordering note**: S3 validates the Lambda's resource policy when the notification is configured — if the permission doesn't exist yet, `apply` errors on the notification resource. The two resources don't directly reference each other's attributes, so add an explicit `depends_on = [aws_lambda_permission.s3_invoke_ingest]` on the notification resource as a safeguard.
- Lambda#2: `aws_lambda_event_source_mapping` (`event_source_arn = var.sqs_queue_arn`, `function_name = aws_lambda_function.triage.arn`, `batch_size = 1`).
- Lambda#3: no trigger resource here — its API Gateway invoke permission and wiring live in `apigateway` (6.8), which consumes this module's `lambda3_invoke_arn`/`arn`/`function_name` outputs.

**Validation**:

- `terraform validate` — each function's `filename`/`source_code_hash` reference the correct `var.*_zip_path`; doc05 §4.6's packaging stage must run before `apply` so these paths resolve to real files.
- `checkov` — X-Ray tracing-mode (`tracing_config.mode = "Active"`) should pass cleanly as configured ("Green via config"). Reserved-concurrency / per-function DLQ findings aren't a doc03/doc04 decision; likely suppress as out-of-scope for demo scale (`#checkov:skip=<ID>: demo-scale, no concurrency contention`).
- `terraform plan` — Lambda#3's `timeout = 28` must appear as a hardcoded literal (doc04 §6 deliberately excludes `lambda3_timeout` from variables). Watch for an accidental copy-paste from Lambda#2's block wiring it to `var.lambda2_timeout` instead.

**Design notes**:

- Most cross-module inputs of any module (6 modules' worth of outputs feed in here) — when wiring `envs/dev/main.tf` (Phase 7), this is the module call most likely to have a missed/misnamed argument; double-check against doc04 §1.3's full table before moving on to `apigateway`.
- The Lambda#1 S3-notification/permission ordering caveat above is the first place in Phase 6 where an explicit `depends_on` is needed despite Terraform's usual implicit-reference dependency graph.

### 6.8 `apigateway`

**Scope**: doc04 §2 rows 16-19 — REST API `/insights` (`aws_api_gateway_rest_api` + `_resource` + `_method` + `_integration` + `_deployment` + `_stage`; `AWS_IAM` auth; `AWS_PROXY` → Lambda#3; X-Ray + access logging on the stage) + `aws_api_gateway_account` (account-level singleton, CloudWatch Logs role) + Lambda#3 invoke permission (doc03 §6.4, scoped to `/*/POST/insights`) + `ECHOInsightsCaller` role (doc03 §6.5: trust = `var.caller_iam_user_arn` via `sts:AssumeRole`; permissions = `execute-api:Invoke` on `/insights` only).

**Inputs → Outputs**: `variables.tf` = `lambda3_invoke_arn`/`arn`/`function_name` (from `lambda`), `env`, `region`, `caller_iam_user_arn` (doc04 §6). `outputs.tf` = `api_endpoint`, `insights_caller_role_arn` — both surfaced as `envs/dev` outputs for Phase 7's demo runbook; `cloudwatch` (6.9) optionally consumes outputs from here for the dashboard (doc04 §1.3 row 8).

**Build order**:

- `aws_api_gateway_rest_api` → `_resource` (`/insights`) → `_method` (`POST`, `authorization = "AWS_IAM"`) → `_integration` (`AWS_PROXY`, `integration_http_method = "POST"`, `uri = var.lambda3_invoke_arn`) → `_deployment` → `_stage` (X-Ray active, access logging).
- `aws_lambda_permission` (Lambda#3 invoke): `source_arn` references this module's own `aws_api_gateway_rest_api`/`_stage` to build `.../*/POST/insights` — the one case doc04 §1.1 calls out as needing **no cross-module reference**, which is why this permission lives here rather than in `iam` or `lambda`.
- `ECHOInsightsCaller`: `aws_iam_role` (trust references `var.caller_iam_user_arn`) + `aws_iam_role_policy` (permissions reference this module's own REST API/stage to build the `execute-api:Invoke` ARN) — same "local reference" reasoning as above.
- `aws_api_gateway_account`: **account/region-level singleton** (doc04 §2.1 item 2, same caveat class as `security-baseline`, 6.11) — sets the CloudWatch Logs role for _all_ REST APIs in the account/region.

**Validation**:

- `checkov` will likely flag missing request validation / `aws_api_gateway_method_settings` (throttling, detailed metrics). doc01 explicitly defers rate-limiting/usage plans for v1; suppress with a pointer to doc01's "out of scope."
- `terraform plan` — `aws_lambda_permission.apigw_invoke_insights`'s `source_arn` and `ECHOInsightsCaller`'s policy `Resource` both depend on `aws_api_gateway_rest_api.insights.execution_arn`, which is `(known after apply)` for a brand-new API (the API ID doesn't exist until creation). **Expected**, not a wiring error — it resolves once `apply` creates the REST API.
- `terraform validate` — confirm `integration_http_method = "POST"` on the `AWS_PROXY` integration (required for Lambda proxy integrations regardless of the API method) — a common copy-paste mismatch with the `_method` resource's own `http_method`.

**Design notes**:

- This module is where doc04 §1.1's cycle-avoidance design pays off concretely: `ECHOInsightsCaller` and the Lambda#3 invoke permission both need _this module's own_ REST API/stage resources — which is why they couldn't live in `iam` (would need `apigateway`'s output) or `lambda` (would need both `iam`'s and `apigateway`'s output, while `apigateway` itself needs `lambda`'s output — the cycle).
- `caller_iam_user_arn` is the one "personal" value in the entire Terraform config — flag in Phase 7's `terraform.tfvars.example` as `# <your IAM user ARN — find via 'aws sts get-caller-identity'>`.

### 6.9 `cloudwatch`

**Scope**: doc04 §2 rows 20-23 — Dashboard (`aws_cloudwatch_dashboard`, FR14: pipeline-health + triage-metrics widget groups, doc03 §8.9) + DLQ-depth alarm (`aws_cloudwatch_metric_alarm`, `ApproximateNumberOfMessagesVisible > 0` on the DLQ → `ops-alarms`) + sentiment anomaly detector (`aws_cloudwatch_metric_alarm` with an anomaly-detection band on EMF `ECHO/SentimentCount{sentiment=negative}` → `ops-alarms`, FR15) + Lambda#1 on-failure destination (`aws_lambda_function_event_invoke_config`, doc03 §5.5).

**Inputs → Outputs**: `variables.tf` = `lambda{1,2,3}_function_name` (from `lambda`), `dlq_arn` (from `sqs`), `ops_alarms_topic_arn` (from `sns`), `env`, `region`. `outputs.tf` = none — terminal module.

**Build order**: 4 largely-independent resources, with two notes:

- The anomaly-detection alarm is a different `aws_cloudwatch_metric_alarm` shape from the DLQ alarm — it needs a `metrics` block with an `ANOMALY_DETECTION_BAND` expression over `ECHO/SentimentCount{sentiment=negative}` and `comparison_operator = "LessThanLowerOrGreaterThanUpperThreshold"`, vs. the DLQ alarm's single-metric `GreaterThanThreshold`. Don't copy-paste one into the other.
- The dashboard's `dashboard_body` is a single large `jsonencode(...)` — likely the longest attribute value in the whole config. doc04 doesn't mandate a structuring approach (e.g. `templatefile()` vs. inline `local`) — first place in Phase 6 left to the builder's judgment.

**Validation**:

- `terraform validate` won't catch malformed widget definitions inside `dashboard_body` (it's opaque JSON to Terraform) — only the console/`apply` surfaces that. This is the one resource in Phase 6 where `validate`/`plan` give weaker guarantees than usual.
- `checkov` — unlikely to flag much on alarms/dashboards; a missing `alarm_description` is the most likely (cosmetic) finding.
- `terraform plan` — the EMF-based alarms reference `ECHO/SentimentCount`, a metric that **doesn't exist yet** at `plan`/`apply` time (CloudWatch creates it implicitly the first time Lambda#2 emits a matching EMF log line). Alarms against not-yet-existent metrics are valid (`INSUFFICIENT_DATA` until data arrives) — expected, not an error, but the first resource in Phase 6 whose "real" target doesn't exist until application code runs in Phase 7.

**Design notes**: this module is the natural place to verify, end-to-end, that the EMF metric names/dimensions Lambda#2/#3 actually emit (Phases 4-5) match what these alarms reference exactly — a mismatch wouldn't fail `terraform apply`, it would just produce an alarm that silently never fires. Worth a Phase 7 smoke-test: trigger one email, confirm `SentimentCount` shows up under namespace `ECHO` in CloudWatch metrics.

### 6.10 `cloudtrail`

**Scope**: doc04 §2 rows 24-25 — single trail (`aws_cloudtrail`: all management events + S3 data-event logging scoped to the `raw-emails` bucket only, doc03 §8.9) + dedicated `cloudtrail-logs` S3 bucket (`aws_s3_bucket` + `_policy` for `cloudtrail.amazonaws.com`).

**Inputs → Outputs**: `variables.tf` = `s3_bucket_arn` (raw-emails, from `s3`, for the data-event selector), `env`, `region`. `outputs.tf` = `trail_arn`.

**Build order**: `cloudtrail-logs` bucket + its `cloudtrail.amazonaws.com` bucket policy must exist before `aws_cloudtrail` — inferred from the trail's `s3_bucket_name` argument referencing the bucket resource.

**Validation**:

- `checkov` will likely flag the same `CKV_AWS_18`/`CKV_AWS_21` (access logging/versioning) findings on `cloudtrail-logs` as 6.1 did on `raw-emails` — same suppression rationale, extending doc03 §8.1's pattern to this bucket. It may also flag log-file validation (`CKV_AWS_36`) — `enable_log_file_validation = true` is a one-line "Green via fix," in the spirit of 6.5's PITR fix.
- `terraform plan` — the S3 data-event selector must reference `"${var.s3_bucket_arn}/"` (trailing slash — CloudTrail's data-resource ARN format for "all objects in this bucket"). Getting this wrong doesn't error; it silently logs zero data events.

**Design notes**: second self-contained "owns its own logging bucket" module after 6.1's `raw-emails` — doc04 §2.1 item 1 already decided `cloudtrail`/`security-baseline` each get their own small bucket rather than sharing one "audit-logs" bucket; this is the first of those two.

### 6.11 `security-baseline`

**Scope**: doc04 §2 rows 26-29 — GuardDuty detector (`aws_guardduty_detector`, S3 Protection enabled) + Security Hub (`aws_securityhub_account` + `aws_securityhub_standards_subscription`, CIS AWS Foundations Benchmark) + AWS Config recorder (`aws_config_configuration_recorder` + `_delivery_channel` + `_configuration_recorder_status`, records all supported resource types) + dedicated `config-logs` S3 bucket (`aws_s3_bucket` + `_policy` for `config.amazonaws.com`).

**Inputs → Outputs**: `variables.tf` = `env`, `region`. `outputs.tf` = none.

**Build order**: `config-logs` bucket + policy before the Config delivery channel (same pattern as 6.10's `cloudtrail-logs`).

**Validation**:

- **Account/region-level singleton caveat** (doc04 §1.3 / §2.1 item 2): GuardDuty detector, Security Hub subscription, and Config recorder are each one-per-account/region. This is _the_ concrete reason `envs/prod` is documented-but-not-deployed (doc04 §1.3) — `terraform plan` for `envs/prod` would show these as resources to _create_, but `apply` would conflict with `envs/dev`'s already-existing detector/subscription/recorder in the same account+region.
- `checkov` — `config-logs` gets the same `CKV_AWS_18`/`CKV_AWS_21` treatment as 6.1/6.10; little applicability to the security-tooling resources themselves.
- **Cost/cleanup reminder**: GuardDuty and Security Hub both have 30-day free trials, then bill per-finding/per-check. Phase 7's runbook should note disabling both after the demo.

**Design notes — flag for Phase 7**: AWS Config requires an IAM role for the recorder (an `aws_iam_role` using the AWS-managed config-role policy), but doc04 §1.2's `iam` module scope is explicitly "3 Lambda execution roles + GitHub OIDC" — this Config-recorder role isn't accounted for anywhere. Most consistent option: this module creates its own small Config-recorder role inline (self-contained, same pattern as this module owning `config-logs`). Resolve when 6.11 is actually built — independent/terminal module (doc04 §1.3 row 11), so it doesn't block the rest of Phase 6.

### 6.12 `demo-data`

**Scope**: doc04 §2 row 30 — ~10-15 `aws_dynamodb_table_item` resources seeding synthetic `EmailTriageResults` records (`review_status=auto_processed`, varied `category`/`urgency`/`sentiment`/`feature_tags`) so `/insights` (FR12) has data immediately after `apply`, without waiting on real SES traffic.

**Inputs → Outputs**: `variables.tf` = `dynamodb_table_name` (from `dynamodb`). `outputs.tf` = none.

**Build order**: all items depend only on `dynamodb`'s table existing; independent of each other.

**Validation**:

- `terraform validate` — each item's `item` argument is a JSON string in DynamoDB's typed-attribute wire format (e.g. `{"email_id": {"S": "..."}, "feature_tags": {"L": [{"S": "..."}]}}`), not plain JSON. First place in Phase 6 requiring DynamoDB's type-annotation wrapper directly in HCL — a missing `{"S": ...}`/`{"L": ...}` is a `validate`-time error.
- `checkov` — no security-relevant findings expected on table-item resources.
- **Idempotency note**: `aws_dynamodb_table_item` manages items by primary key — if a real ingested email ever collided with a seed item's `email_id`, the next `plan` would show drift. Use an obviously-synthetic prefix (e.g. `demo-email-001`) for seed `email_id` values — both for readability and to make such a collision impossible (real `email_id`s are SES `messageId`s).

**Design notes**: doc04 §6's `demo_seed_data_file` variable (`./seed-data/email_triage_results.json`) holds the ~10-15 records in plain JSON. This module likely uses `jsondecode(file(var.demo_seed_data_file))` with `for_each` over the decoded list — the first use of `for_each` in Phase 6 — rather than 10-15 hand-written resource blocks. Converting each record's plain-JSON fields into DynamoDB's `{"S": ...}`/`{"L": ...}`/`{"N": ...}`/`{"BOOL": ...}` wire format inside that `for_each` is a design detail to resolve when this story is built.

---

## Phase 7 — Bootstrap Deploy & Demo

Procedural — wires the 12 modules into `envs/dev`, runs the first `terraform apply` (necessarily local, doc05 §5.5), hands off to CI, and documents the interview demo + teardown. No new design decisions expected here; this phase is sequencing and verification of decisions already locked in docs 03-06.

### 7.1 One-Time Prerequisites (before any `terraform apply`)

These must happen first, in roughly this order — none of them are Terraform resources:

1. **Domain DNS — MX record** (doc04 §2.1 item 3): point Mike's domain's MX record at `inbound-smtp.us-east-1.amazonaws.com` (priority 10), at the domain registrar.
2. **SES domain verification** (resolves 6.2's flag): verify the recipient domain as a SES identity in `us-east-1` — `aws_ses_domain_identity` + the DNS TXT record it requires, added to the registrar alongside the MX record. Decision: this is a **manual step alongside the MX record**, not a Terraform resource in the `ses` module — both are one-time DNS changes at a registrar Terraform doesn't control, so grouping them as one runbook step (not splitting one into IaC and one into a manual list) keeps this prerequisite list coherent.
3. **Terraform state S3 bucket** (doc04 §7.2): `aws s3 mb s3://echo-terraform-state-<ACCOUNT_ID> --region us-east-1`, then enable versioning and default SSE-S3 encryption on it. Must exist before `terraform init` (the backend can't create the bucket it depends on).
4. **Local AWS credentials**: `aws configure` with an IAM user that has sufficient permissions for the first `apply` (doc05 §5.5 — CI's `ECHOGitHubActionsRole` doesn't exist yet, so this first run can't use OIDC).
5. **`caller_iam_user_arn`**: run `aws sts get-caller-identity` and copy the `Arn` — this is the value for `ECHOInsightsCaller`'s trust policy (doc03 §6.5), the one "personal" Terraform variable (flagged in 6.8).
6. **`infra/envs/dev/terraform.tfvars`**: copy from `terraform.tfvars.example` and fill in all required variables (doc04 §6): `env="dev"`, `region="us-east-1"`, `alert_email`, `ses_recipient_address`, `caller_iam_user_arn` (from step 5), `github_org`, `github_repo`, plus defaults for `sqs_visibility_timeout`/`sqs_max_receive_count`/`lambda2_timeout`/`bedrock_model_id`/`lambda_artifacts_dir`/`demo_seed_data_file`. Gitignored — never committed (global key rules).
7. **Package Lambda artifacts locally**: doc05 §4.6's packaging steps (`shared_utils_layer.zip`, `lambda_ingest.zip`, `lambda_triage.zip`, `lambda_insights.zip` into `build/`) run by hand for this first apply, since the CI pipeline that normally does this hasn't run yet — same commands as the `package` job's `run:` steps, executed locally.
8. **Demo seed data file**: create `infra/modules/demo-data`'s `./seed-data/email_triage_results.json` with ~10-15 synthetic records (doc04 §2/§6, 6.12).

### 7.2 `envs/dev` Wiring

`infra/envs/dev/main.tf` instantiates all 12 modules in doc04 §1.3's dependency order, passing each module's outputs to the next as inputs — the table in doc04 §1.3 is the literal wiring spec (module call → `source = "../../modules/<name>"` → `output.X` from an earlier module passed as `input.Y` to a later one). Two flagged items from Phase 6 to resolve while wiring:

- **6.2 `ses`**: confirm whether domain verification (7.1 step 2) needs an `aws_ses_domain_identity` resource inside the `ses` module (to surface verification status in `terraform plan`) or stays purely manual/external. Either way, `ses`'s module call here is unaffected — it only consumes `s3`'s `bucket_name` and `var.ses_recipient_address`.
- **6.11 `security-baseline`**: confirm the AWS Config recorder IAM role is created inline in this module (per 6.11's design note) before wiring `envs/dev`'s call to it — `security-baseline` takes no module-output inputs either way (doc04 §1.3 row 11, terminal).

`infra/envs/dev/outputs.tf` re-exports the demo-facing values: `api_endpoint` and `insights_caller_role_arn` (from `apigateway`), `github_actions_role_arn` (from `iam`, for step 7.3.4 below), and `dynamodb`'s `table_name` (useful for `aws dynamodb` CLI calls during the demo).

### 7.3 First `terraform apply` (bootstrap sequence)

1. `cd infra/envs/dev && terraform init` — initializes the S3 backend (doc04 §7.1) using the bucket created in 7.1 step 3.
2. `terraform plan` — review the full ~32-resource plan (doc04 §2's total) before applying. Expect several `(known after apply)` values flagged in Phase 6 (e.g. `apigateway`'s `execution_arn`-derived ARNs, 6.8) — these are normal for a first apply.
3. `terraform apply` — confirm. This is the **only** local apply expected for the project's lifetime; everything after this is CI-driven (7.5).
4. **Confirm SNS email subscriptions**: AWS sends confirmation emails for each `protocol="email"` subscription (3 total — 2 on `alert-topic`, 1 on `ops-alarms`, doc04 §2 rows 6-7 / 6.4). Click each confirmation link — until confirmed, subscriptions sit in `PendingConfirmation` and nothing delivers.
5. **Copy `github_actions_role_arn`** (from `terraform output`) into the GitHub repo as secret `AWS_CI_ROLE_ARN` (doc05 §5.5 / §4.7) — this is what lets the CI pipeline authenticate via OIDC from this point on.

### 7.4 Post-Apply Smoke Tests

Verify the deployed pipeline end-to-end before considering Phase 7 done, working forward through doc03's data-flow steps:

1. **Send a test email** to `ses_recipient_address` (a real email, per the project's "real SES ingest" design — not a synthetic `POST /email`).
2. **S3**: confirm a new object appears under `raw-emails/` in the bucket (doc03 step 1-2).
3. **DynamoDB**: `aws dynamodb scan --table-name <table_name>` (from `envs/dev`'s output) — confirm a new item with the test email's `email_id` (SES `messageId`), `category`/`urgency`/`sentiment`/`review_status` populated (doc03 steps 9-15).
4. **SNS alert**: confirm an email arrives on whichever `alert-topic` filter matches the test email's `alert_type` (doc03 §7.1) — if the test email's content doesn't trigger `urgent`/`needs_review`, this step may legitimately produce no alert; send a second test email with FR7 escalation language (e.g. "I can't login, this is urgent") to exercise the `urgent` path.
5. **CloudWatch EMF metrics**: in the CloudWatch console, confirm `ECHO/SentimentCount` (with a `sentiment` dimension matching the test email) and `ECHO/PiiEntitiesDetected` appear under namespace `ECHO` (doc03 §8.9, 6.9's design note) — this is the cross-check that Lambda#2's EMF output and `cloudwatch`'s alarms agree on metric names/dimensions.
6. **X-Ray**: confirm a trace appears for the Lambda#1 → Lambda#2 invocation chain, with the `email_id` annotation on the relevant segments (doc03 §8.9, FR13).
7. **CloudTrail**: confirm a data event for the `raw-emails` bucket `PutObject` (from SES) appears in CloudTrail (doc03 §8.9) — the demoable "who/what touched pre-redaction email content" control.
8. **`/insights` via `ECHOInsightsCaller`** (FR16 demo flow, from project planning): run `aws sts assume-role --role-arn <insights_caller_role_arn> --role-session-name insights-demo` to get temporary credentials, then use `awscurl` (SigV4) with those credentials to `POST` to `<api_endpoint>/insights` with `{"question": "..."}` — confirm a `200` with `{"answer": ..., "records_considered": N}` where `N` includes both the seeded demo-data records (6.12) and the test email(s) from step 1/4 (if `review_status=auto_processed`).
9. **Unauthenticated `/insights` call** (no SigV4) → confirm `403` — demonstrates FR16's IAM-auth gate is actually enforced, not just configured.

### 7.5 CI/CD Handoff

After 7.3 completes, the bootstrap is done — `infra/` and `src/` changes from this point on go through the normal flow (doc05 §1.1): `git push` to `main` → gitleaks/bandit/checkov/pip-audit/pytest gates → package → `terraform apply` via `ECHOGitHubActionsRole` (OIDC, §4.7). The first such push is a good validation that the OIDC handoff (7.3 step 5) actually works — e.g., push a trivial change (a comment in any module) and confirm the Actions run completes a real `apply` using the CI role, not local credentials.

### 7.6 Demo Test

when fully deployed, testing process order

1. **Architecture overview** — walk doc03 §1's diagrams (ingest/triage pipeline, insights API, observability/security overlay).
2. **Send a live email** — to `ses_recipient_address`, narrate steps 1-2 (SES → S3) as it happens.
3. **Show the DynamoDB record** — walk through `category`/`urgency`/`sentiment`/`confidence`/`suggested_reply`/`feature_tags`/`pii_entities_detected`/`urgency_override_applied` for the just-processed email (FR4-FR9).
4. **Show the SNS alert email** — tie `alert_type` back to the `urgency`/`review_status` just shown (doc03 §7.1, FR10).
5. **PII redaction narrative** — send an email containing a fake name/email/phone in the body; show `pii_entities_detected > 0` in DynamoDB and the corresponding CloudTrail data event for the _raw_ (pre-redaction) object in S3 — "this is what we're protecting" (FR3, doc01 problem statement).
6. **Keyword override (DR4)** — send an email with FR7 escalation language (e.g. "outage", "charged twice"); show `urgency_override_applied=true` even if the model alone might have scored it lower.
7. **CloudWatch dashboard** (FR14) — pipeline-health widgets (invocations/errors/duration, queue depth, API 4xx/5xx) and triage-metrics widgets (`SentimentCount`, `PiiEntitiesDetected`, failure metrics).
8. **Anomaly detection** (FR15) — explain the `SentimentCount{sentiment=negative}` anomaly band on `ops-alarms`, even if it hasn't fired (the _configuration_ is the demoable artifact at this volume).
9. **X-Ray trace** — open a trace for one of the demo emails, show the `email_id`-annotated segments across Lambda#1/#2 (FR13).
10. **`/insights` demo** (FR12/FR16) — the `sts assume-role` → `awscurl` SigV4 flow from 7.4 step 8, asking a real aggregate question (e.g. "what are the most common feature requests?") against the combined seed + live data; then the unauthenticated `403` from 7.4 step 9 as the "security control" beat.
11. **Security posture** — Security Hub CIS findings, GuardDuty (S3 Protection), AWS Config recorder — doc01 §5's severity scale applied to whatever findings exist at demo time.
12. **Degraded-path narrative** (optional, if time allows) — explain (without necessarily triggering live) FR17's `unclassified`/`needs_review` fallback and DR8's `SynthesisFailure` 503 path, pointing at doc03 §4.5/§7.3 — shows resilience thinking even if the happy path is all that's demoed live.

### 7.7 Teardown / Cost Hygiene

- **GuardDuty + Security Hub**: both have 30-day free trials, then bill per-finding/per-check (project memory). If the demo environment will be kept beyond 30 days without ongoing use, disable both (`aws guardduty delete-detector` / disable the Security Hub subscription) — or `terraform destroy -target` the `security-baseline` module's relevant resources.
- **Full teardown** (`terraform destroy` against `envs/dev`): safe for nearly everything, with two notes — (1) `demo-data`'s items will be destroyed along with the table, which is expected; (2) the `aws_api_gateway_account` resource (6.8) is an account/region-level singleton — destroying it affects CloudWatch Logs role config for _all_ REST APIs in the account/region, not just this one. If other API Gateway resources exist in the account, confirm before destroying this resource.
- **State bucket** (7.1 step 3) and the **GitHub OIDC provider** (`iam`, 6.6) are _not_ destroyed by `terraform destroy` of `envs/dev` resources that reference them only as data — but the OIDC provider and `ECHOGitHubActionsRole` ARE managed by `envs/dev`'s `iam` module, so a full destroy removes CI's ability to deploy again without repeating the 7.3 bootstrap.

---

]
