# 06 - Development Plan

> **ECHO** (Email Classification & Handling Orchestrator) — an automated email triage, classification, and insights pipeline.

## Build Tracker

| Story | File | Status | Gate to start |
|-------|------|--------|---------------|
| 1.1 | Scaffold (dirs + configs) | DONE | — |
| 2.1 | `layers/shared_utils/retry_config.py` | DONE | — |
| 3.1 | `lambda_ingest/mime_parser.py` | DONE | — |
| 3.2 | `lambda_ingest/handler.py` | DONE | 3.1, 2.1 |
| 4.1 | `lambda_triage/keyword_rules.py` | DONE | — |
| 4.2 | `lambda_triage/pii.py` | DONE | 2.1 |
| 4.3 | `lambda_triage/classify.py` | ◀ NEXT | 2.1 |
| 4.4 | `lambda_triage/persist.py` | TODO | 2.1 |
| 4.5 | `lambda_triage/handler.py` (orchestration) | TODO | 4.1–4.4 |
| 4.6 | `lambda_triage/handler.py` (alerting + EMF) | TODO | 4.5 |
| 5.1 | `lambda_insights/query.py` (parameterized + original) | DONE (original) / ◀ NEXT (parameterized) | 2.1 |
| 5.2 | `lambda_insights/synthesize.py` (Bedrock tool use) | TODO | 5.1 |
| 5.3 | `lambda_insights/handler.py` | TODO | 5.2 |
| 6.1 | `infra/modules/s3` | TODO | — |
| 6.2 | `infra/modules/ses` | TODO | 6.1 |
| 6.3 | `infra/modules/sqs` | TODO | — |
| 6.4 | `infra/modules/sns` | TODO | — |
| 6.5 | `infra/modules/dynamodb` | TODO | — |
| 6.6 | `infra/modules/iam` | TODO | 6.1, 6.3, 6.4, 6.5 |
| 6.7 | `infra/modules/lambda` | TODO | 6.6, 6.1, 6.3, 6.5, 6.4 |
| 6.8 | `infra/modules/apigateway` | TODO | 6.7 |
| 6.9 | `infra/modules/cloudwatch` | TODO | 6.7, 6.3, 6.4 |
| 6.10 | `infra/modules/cloudtrail` | TODO | 6.1 |
| 6.11 | `infra/modules/security-baseline` | TODO | — |
| 6.12 | `infra/modules/demo-data` | TODO | 6.5 |
| 7.1 | One-time prerequisites | TODO | Phase 6 |
| 7.2 | `envs/dev` wiring | TODO | 7.1 |
| 7.3 | First `terraform apply` | TODO | 7.2 |
| 7.4 | Post-apply smoke tests | TODO | 7.3 |
| 7.5 | CI/CD handoff | TODO | 7.4 |
| 7.6 | Demo test | TODO | 7.5 |
| 7.7 | Teardown / cost hygiene | TODO | — |

---

## How to Use This Document

doc06 is a story-by-story **blueprint** — not a code dump. It's sequenced for TDD (Red → Green → Refactor, per doc08). The actual code gets written during the build phase, one story at a time, in **Teaching Mode** (global CLAUDE.md): Mike writes it with guidance, unless he says `pmc <thing>`.

Each story uses this template:
- **Goal** — one-line summary of what you're building
- **Prereqs** — what must be green before starting + mocking strategy
- **Signatures** — functions/constants to define
- **TDD Order** — suggested Red→Green sequence
- **External Docs** — links to AWS/library references relevant to this story
- **Background** (collapsible) — AWS API behavior, quirks, design decisions
- **Full Test Table + Implementation** (collapsible) — detailed spec

| Phase | Scope | Depth |
|-------|-------|-------|
| 1 | Scaffold: repo structure, config files, CI workflow, empty Terraform modules | Procedural |
| 2 | `shared-utils` Lambda layer — `retry_config.py` only | Full |
| 3 | Lambda #1 — Ingest | Full |
| 4 | Lambda #2 — Triage | Full |
| 5 | Lambda #3 — Insights | Full |
| 6 | Terraform modules (12) | Lighter — `terraform validate`/`checkov` as the gate |
| 7 | Bootstrap deploy + demo | Procedural/runbook |

---

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

| # | Item | Source |
|---|------|--------|
| 1 | `src/lambda_{ingest,triage,insights}/`, `src/layers/shared_utils/` | doc03 §5.2 |
| 2 | `tests/lambda_{ingest,triage,insights}/`, `tests/layers/shared_utils/`, `tests/conftest.py` | doc08 |
| 3 | `src/layers/shared_utils/requirements.txt` (pinned boto3/botocore + aws-xray-sdk) | doc05 §4.4 |
| 4 | `requirements-dev.txt` (pytest, moto, coverage) | doc08 |
| 5 | `pytest.ini` | doc08 |
| 6 | `infra/modules/<12 modules>/{main,variables,outputs}.tf` — empty, 3-file convention | doc04 §1.2 |
| 7 | `infra/envs/{dev,prod}/{main.tf,backend.tf,variables.tf,terraform.tfvars.example,outputs.tf}` | doc04 §1.2/§7 |
| 8 | `.github/workflows/deploy.yml` | doc05 §7 |
| 9 | `.gitignore` (Python, Terraform, AWS creds, macOS, IDE) | |

---

## Phase 2 — `shared-utils` Layer: `retry_config.py`

---

### 2.1 `retry_config.py`

**Goal:** Create two `botocore.config.Config` constants (`GENERAL_CONFIG` / `BEDROCK_CONFIG`) consumed by every boto3 client across all 3 Lambdas.

**Prereqs:** None — zero AWS dependency. No `@mock_aws` needed. This story proves the `tests/` ↔ `src/` import wiring works.

**Signatures (build these):**

```
src/layers/shared_utils/retry_config.py

from botocore.config import Config

GENERAL_CONFIG = Config(...)   # retries adaptive/3, connect=3, read=5
BEDROCK_CONFIG = Config(...)   # retries adaptive/3, connect=3, read=10
```

**TDD Order (Red → Green):**
1. test #1 + #2 + #3 → build `GENERAL_CONFIG`
2. test #4 + #5 + #6 → build `BEDROCK_CONFIG`
3. test #7 → regression boundary (should already pass)

**External Docs:**
- [botocore Config reference](https://botocore.amazonaws.com/v1/documentation/api/latest/reference/config.html)
- [Retry behavior (adaptive mode)](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/retries.html)
- [boto3 client configuration](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/configuration.html)

**Input/Output Shapes:**

```python
# These are constants, not functions — here's how they're consumed and what attributes matter:

# GENERAL_CONFIG — used by: S3, SQS, Comprehend, DynamoDB, SNS clients
# Consumed as: boto3.client("s3", config=GENERAL_CONFIG)
GENERAL_CONFIG.retries          # {"max_attempts": 3, "mode": "adaptive"}
GENERAL_CONFIG.connect_timeout  # 3 (seconds)
GENERAL_CONFIG.read_timeout     # 5 (seconds)

# BEDROCK_CONFIG — used by: bedrock-runtime client only
# Consumed as: boto3.client("bedrock-runtime", config=BEDROCK_CONFIG)
BEDROCK_CONFIG.retries          # {"max_attempts": 3, "mode": "adaptive"}
BEDROCK_CONFIG.connect_timeout  # 3 (seconds)
BEDROCK_CONFIG.read_timeout     # 10 (seconds) — the ONE difference

# Both are botocore.config.Config instances (isinstance check in tests)
# Both are module-level constants — safe to share across clients (immutable)
```

**Sample Code — what the implementation looks like:**

```python
from botocore.config import Config

GENERAL_CONFIG = Config(
    retries={"max_attempts": 3, "mode": "adaptive"},
    connect_timeout=3,
    read_timeout=5,
)
```

**Sample Code — what a test looks like:**

```python
from retry_config import GENERAL_CONFIG, BEDROCK_CONFIG
from botocore.config import Config

def test_general_config_is_config_instance():
    assert isinstance(GENERAL_CONFIG, Config)

def test_general_config_retries():
    assert GENERAL_CONFIG.retries == {"max_attempts": 3, "mode": "adaptive"}
```

<details><summary><b>Background & design decisions</b></summary>

- `botocore.config.Config` is passed as `boto3.client("s3", config=GENERAL_CONFIG)` — it controls connection/read timeouts and retry behavior for that client.
- `retries={"mode": "adaptive", "max_attempts": 3}` — `max_attempts` includes the _initial_ attempt (so 3 = 1 try + 2 retries). `adaptive` mode adds exponential backoff+jitter **and** client-side rate limiting once throttling is observed — stronger than `"standard"` mode, appropriate for AWS API throttling (doc03 §4.2).
- Two configs, differing only in `read_timeout` (doc03 §4.2's table):
  - `GENERAL_CONFIG` — Comprehend/DynamoDB/SNS/S3/SQS: `max_attempts=3`, `connect_timeout=3`, `read_timeout=5`, `mode="adaptive"`
  - `BEDROCK_CONFIG` — Bedrock: same except `read_timeout=10` (LLM calls run longer)
- **This story has zero AWS dependency** — `Config` objects are pure data, constructed with no network calls. No `@mock_aws` needed.
- Runtime import path: as a Lambda layer, this file lands at `/opt/python/retry_config.py`. Locally, tests import it as `from retry_config import GENERAL_CONFIG, BEDROCK_CONFIG` — `pytest.ini` puts `src/layers/shared_utils/` on `sys.path`.
- **Not part of this story** — Lambda #3's "tightened" Bedrock config (`max_attempts=2`, `read_timeout=5s`) is function-specific, built inline in `lambda_insights/synthesize.py` (Phase 5).

</details>

<details><summary><b>Full test table + implementation</b></summary>

**Test** (`tests/layers/shared_utils/test_retry_config.py`)

| # | Test | Why it matters |
|---|------|----------------|
| 1 | `GENERAL_CONFIG` is a `botocore.config.Config` instance | Catches a typo'd import or wrong return type |
| 2 | `GENERAL_CONFIG.retries == {"max_attempts": 3, "mode": "adaptive"}` | Pins the exact retry dict doc03 §4.2 specifies |
| 3 | `GENERAL_CONFIG.connect_timeout == 3` and `.read_timeout == 5` | Pins timeout values used by 5 of the 6 AWS services |
| 4 | `BEDROCK_CONFIG` is a `botocore.config.Config` instance | Same as #1, for the second object |
| 5 | `BEDROCK_CONFIG.retries == {"max_attempts": 3, "mode": "adaptive"}` | Pins retry dict for Bedrock |
| 6 | `BEDROCK_CONFIG.connect_timeout == 3` and `.read_timeout == 10` | Pins the 10s Bedrock read timeout |
| 7 | `GENERAL_CONFIG.read_timeout != BEDROCK_CONFIG.read_timeout` | Boundary: regression test for the one-field difference |

No fixtures, no moto, no `conftest.py` dependency — self-contained.

**Implementation**

`src/layers/shared_utils/retry_config.py` — two module-level constants, both `botocore.config.Config` instances. No functions, no classes, no imports beyond `from botocore.config import Config`.

| Constant | `retries` | `connect_timeout` | `read_timeout` |
|----------|-----------|-------------------|----------------|
| `GENERAL_CONFIG` | `{"max_attempts": 3, "mode": "adaptive"}` | `3` | `5` |
| `BEDROCK_CONFIG` | `{"max_attempts": 3, "mode": "adaptive"}` | `3` | `10` |

Design decisions:
- Module-level constants, not factory functions — `Config` objects are immutable; clients sharing them is safe.
- Usage pattern each later story follows: `boto3.client("dynamodb", config=GENERAL_CONFIG)`.

</details>

---

## Phase 3 — Lambda #1 — Ingest

---

### 3.1 `mime_parser.py`

**Goal:** Parse raw `.eml` bytes into `{"from_address", "subject", "body"}` using Python's stdlib `email` library.

**Prereqs:** None — zero AWS dependency. Test fixtures use stdlib's `EmailMessage` to build valid MIME.

**Signatures (build these):**

```
src/lambda_ingest/mime_parser.py

from email import policy
from email.parser import BytesParser
from email.utils import parseaddr

def parse_email(raw_bytes: bytes) -> dict:
    # returns {"from_address": str, "subject": str, "body": str}
```

**TDD Order (Red → Green):**
1. test #1 (plain-text happy path) → build basic `parse_email` skeleton
2. test #6 (from_address extraction) → add `parseaddr` logic
3. test #2 (multipart/alternative) → add `get_body(preferencelist=...)`
4. test #3 + #4 (base64/quoted-printable) → confirm `.get_content()` handles them
5. test #5 (RFC 2047 subject) → confirm `policy.default` handles it
6. test #7 (no body — attachment-only) → add `None` guard on `get_body()`

**External Docs:**
- [Python `email` library](https://docs.python.org/3/library/email.html)
- [email.parser.BytesParser](https://docs.python.org/3/library/email.parser.html#email.parser.BytesParser)
- [email.utils.parseaddr](https://docs.python.org/3/library/email.utils.html#email.utils.parseaddr)
- [email.policy](https://docs.python.org/3/library/email.policy.html)
- [email.message.EmailMessage](https://docs.python.org/3/library/email.message.html#email.message.EmailMessage)
- [Content-Transfer-Encoding (RFC 2045)](https://datatracker.ietf.org/doc/html/rfc2045#section-6)

**Input/Output Shapes:**

```python
# INPUT — raw_bytes: what a .eml file looks like as bytes:
raw_bytes = b'From: Jane Doe <jane@example.com>\r\nSubject: Help needed\r\nContent-Type: text/plain\r\n\r\nI need help with my account.'

# OUTPUT — parse_email() always returns exactly these 3 keys, always strings:
{
    "from_address": "jane@example.com",   # just the email, no display name
    "subject": "Help needed",              # RFC 2047 decoded if encoded
    "body": "I need help with my account." # base64/QP decoded, plain preferred over html
}

# EDGE CASE — attachment-only email (no body part):
{
    "from_address": "sender@example.com",
    "subject": "See attached",
    "body": ""  # empty string, never None
}
```

**Sample Code — building a test fixture:**

```python
from email.message import EmailMessage

def build_eml(from_addr="jane@example.com", subject="Test", body="Hello"):
    msg = EmailMessage()
    msg["From"] = f"Jane Doe <{from_addr}>"
    msg["Subject"] = subject
    msg.set_content(body)
    return msg.as_bytes()

# Multipart alternative (plain + html):
def build_multipart_eml():
    msg = EmailMessage()
    msg["From"] = "test@example.com"
    msg["Subject"] = "Multi"
    msg.set_content("Plain text body")
    msg.add_alternative("<p>HTML body</p>", subtype="html")
    return msg.as_bytes()
```

**Sample Code — parsing:**

```python
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr

msg = BytesParser(policy=policy.default).parsebytes(raw_bytes)
from_address = parseaddr(str(msg["from"]))[1]  # "jane@example.com"
subject = str(msg["subject"])
part = msg.get_body(preferencelist=("plain", "html"))
body = part.get_content() if part else ""
```

<details><summary><b>Background & design decisions</b></summary>

- `email.parser.BytesParser(policy=email.policy.default).parsebytes(raw_bytes)` parses the raw `.eml` bytes into an `EmailMessage`. With `policy.default`, header access (`msg["subject"]`, `msg["from"]`) returns objects that `str()` into **fully RFC 2047-decoded** text — no manual `decode_header` needed for non-ASCII subjects.
- `msg.get_body(preferencelist=("plain", "html"))` walks multipart/alternative and multipart/mixed trees and returns the best-matching part (or `None` if no body part exists — e.g., an attachment-only email).
- `.get_content()` on that part transparently decodes `Content-Transfer-Encoding: base64` / `quoted-printable` and returns a `str` — this is what satisfies doc03 step 4's "handles multipart/base64/quoted-printable" requirement; we don't hand-roll decoding.
- `From: "Jane Doe" <jane@example.com>` — `email.utils.parseaddr(str(msg["from"]))` returns `(realname, email_address)`; we keep only `[1]`.
- Zero AWS dependency — same as Phase 2, no `@mock_aws` needed. Test fixtures are built with stdlib's own `EmailMessage` (`.set_content()` / `.add_alternative()`) rather than hand-written raw strings, guaranteeing valid MIME.

</details>

<details><summary><b>Full test table + implementation</b></summary>

**Test** (`tests/lambda_ingest/test_mime_parser.py`)

| # | Test | Why it matters |
|---|------|----------------|
| 1 | Simple plain-text email → correct `from_address`, `subject`, `body` | Baseline happy path |
| 2 | Multipart/alternative (plain + html) → `body` is the **plain** part | Confirms `preferencelist=("plain","html")` ordering |
| 3 | `Content-Transfer-Encoding: base64` body → decoded to original text | Pins doc03's "handles base64" requirement |
| 4 | `Content-Transfer-Encoding: quoted-printable` body → decoded to original text | Pins "handles quoted-printable" |
| 5 | RFC 2047 encoded-word subject (e.g. non-ASCII chars) → decoded readable string | Confirms `policy.default` header decoding |
| 6 | `From: "Jane Doe" <jane@example.com>` → `from_address == "jane@example.com"` | Confirms display-name stripping |
| 7 | **Boundary**: email with no body part (attachment-only) → `body == ""`, no exception | `get_body()` returning `None` is a real edge case |

Helper: `build_eml(**kwargs) -> bytes` constructs test messages via `EmailMessage()` + `.set_content()`/`.add_alternative()`, returned via `.as_bytes()`.

**Implementation**

`src/lambda_ingest/mime_parser.py` — one function, three stdlib imports.

`parse_email(raw_bytes: bytes) -> dict`

1. Parse: `BytesParser(policy=policy.default).parsebytes(raw_bytes)` → `msg`.
2. `from_address`: `parseaddr(str(msg["from"]))[1]` if header exists, else `""`.
3. `subject`: `str(msg["subject"])` if header exists, else `""`.
4. `body`: `msg.get_body(preferencelist=("plain", "html"))` — if part exists, `.get_content()`; if `None`, `""`.
5. Return `{"from_address": ..., "subject": ..., "body": ...}`.

</details>

---

### 3.2 `handler.py`

**Goal:** Read raw email from S3, extract `email_id` from the key, parse it via `mime_parser`, send structured JSON to SQS. Includes poison-pill demo path and X-Ray annotation.

**Prereqs:** 3.1 (`mime_parser`) + 2.1 (`GENERAL_CONFIG`). Uses `@mock_aws` (moto supports S3 + SQS). Module-level clients require `importlib.reload(handler)` inside `mock_aws()` context.

**Signatures (build these):**

```
src/lambda_ingest/handler.py

import json, os, boto3
from urllib.parse import unquote_plus
from mime_parser import parse_email
from retry_config import GENERAL_CONFIG
from aws_xray_sdk.core import xray_recorder

s3 = boto3.client("s3", config=GENERAL_CONFIG)
sqs = boto3.client("sqs", config=GENERAL_CONFIG)
xray_recorder.configure(context_missing="LOG_ERROR")
POISON_PILL_MARKER = "ECHO-POISON-PILL"

def handler(event, context):
    # S3 event → parse email → send to SQS
```

**TDD Order (Red → Green):**
1. test #1 (happy path) → build full handler skeleton
2. test #2 + #3 (`email_id` derivation, URL-encoded key) → add `unquote_plus` + `rsplit`
3. test #4 (`received_at` from `LastModified`) → wire timestamp
4. test #5 (poison pill) → add `POISON_PILL_MARKER` check
5. test #7 (JSON round-trip boundary) → should pass already
6. test #6 (multipart → correct body) → integration with `parse_email`
7. test #8 (X-Ray annotation) → add `put_annotation` call

**External Docs:**
- [S3 event notification format](https://docs.aws.amazon.com/AmazonS3/latest/userguide/notification-content-structure.html)
- [S3 GetObject](https://docs.aws.amazon.com/AmazonS3/latest/API/API_GetObject.html)
- [SQS SendMessage](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/APIReference/API_SendMessage.html)
- [moto — supported services](https://docs.getmoto.org/en/latest/docs/services/index.html)
- [moto `mock_aws` decorator](https://docs.getmoto.org/en/latest/docs/getting_started.html)
- [aws-xray-sdk Python](https://docs.aws.amazon.com/xray/latest/devguide/xray-sdk-python.html)
- [importlib.reload](https://docs.python.org/3/library/importlib.html#importlib.reload)
- [urllib.parse.unquote_plus](https://docs.python.org/3/library/urllib.parse.html#urllib.parse.unquote_plus)

**Input/Output Shapes:**

```python
# INPUT — event (S3 notification, only the keys handler uses):
event = {
    "Records": [{
        "s3": {
            "bucket": {"name": "echo-raw-emails-dev"},
            "object": {"key": "raw-emails/abc123def456"}  # URL-encoded by S3
        }
    }]
}

# INPUT — context: Lambda context object (unused by this handler, pass None in tests)

# INTERMEDIATE — s3.get_object() response shape:
response = {
    "Body": StreamingBody(...),         # .read() → raw .eml bytes
    "LastModified": datetime(2026, 6, 21, 14, 30, 0, tzinfo=timezone.utc),  # boto3-parsed
    "ContentType": "application/octet-stream",
    # ... other metadata we don't use
}

# OUTPUT — SQS message payload (json.dumps'd into MessageBody):
{
    "email_id": "abc123def456",                    # from S3 key, after last "/"
    "from_address": "jane@example.com",            # from parse_email()
    "subject": "Help with my account",             # from parse_email()
    "body": "I need help with my account...",      # from parse_email()
    "received_at": "2026-06-21T14:30:00+00:00",   # LastModified.isoformat()
    "raw_s3_key": "raw-emails/abc123def456"        # decoded key (for audit trail)
}

# POISON-PILL VARIANT — same but "body" key is DELETED:
{
    "email_id": "abc123def456",
    "from_address": "attacker@example.com",
    "subject": "ECHO-POISON-PILL test",
    "received_at": "2026-06-21T14:30:00+00:00",
    "raw_s3_key": "raw-emails/abc123def456"
    # NO "body" key — causes KeyError in Lambda #2
}
```

**Sample Code — test fixture with moto + importlib.reload:**

```python
import importlib
import os
import boto3
from moto import mock_aws

@mock_aws
def test_happy_path():
    # 1. Set env vars BEFORE reload
    os.environ["TRIAGE_QUEUE_URL"] = "https://sqs.us-east-1.amazonaws.com/123/queue"

    # 2. Create AWS resources under mock
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="echo-raw-emails-dev")
    sqs = boto3.client("sqs", region_name="us-east-1")
    queue = sqs.create_queue(QueueName="queue")

    # 3. Reload handler so its module-level clients bind to moto
    import handler
    importlib.reload(handler)

    # 4. Put a test .eml in S3
    s3.put_object(Bucket="echo-raw-emails-dev", Key="raw-emails/msg-001", Body=eml_bytes)

    # 5. Invoke and assert
    handler.handler(event, None)
    messages = sqs.receive_message(QueueUrl=queue["QueueUrl"])
    payload = json.loads(messages["Messages"][0]["Body"])
    assert payload["email_id"] == "msg-001"
```

> **Context digest:** S3 event keys are URL-encoded (must `unquote_plus`). `response["Body"]` is a StreamingBody (single `.read()`). `LastModified` is already a `datetime` from boto3. No try/except — RAISE on failure (doc03 §4.5).

<details><summary><b>Background & design decisions</b></summary>

- S3 event shape: `event["Records"][0]["s3"]["bucket"]["name"]` / `["object"]["key"]`. The key is **URL-encoded** by S3 (e.g., spaces → `+`) — must `urllib.parse.unquote_plus()` before use.
- `email_id` = SES messageId = the filename portion of the key (`raw-emails/<ses-message-id>` → split on the last `/`), per doc03 step 5.
- `s3.get_object()`'s `Body` is a `StreamingBody` — single-read, must call `.read()` to get bytes.
- `received_at` comes from the `get_object` response's `LastModified` field (a `datetime`, boto3-parsed already) → `.isoformat()`.
- **Poison-pill demo** (doc03 §4.5): a magic marker in the subject (`ECHO-POISON-PILL`) causes the handler to **omit the `body` key** from the SQS payload — deliberately malformed input that makes Lambda #2 throw `KeyError` on every redelivery, demonstrating the DLQ path.
- **Module-level boto3 clients + moto timing**: `s3`/`sqs` clients are constructed at module import time. For tests, `@mock_aws` must be active **before** these clients are constructed — tests use `importlib.reload(handler)` inside an active `mock_aws()` context.
- Failure handling: Lambda #1 is invoked async by S3 — if `handler()` raises, Lambda's built-in async retries handle it. **No try/except needed.**
- **X-Ray annotation** (FR13): `xray_recorder.put_annotation("email_id", email_id)`. Outside Lambda (pytest), `context_missing="LOG_ERROR"` makes this log-and-continue instead of raising.

</details>

<details><summary><b>Full test table + implementation</b></summary>

**Test** (`tests/lambda_ingest/test_handler.py`)

| # | Test | Why it matters |
|---|------|----------------|
| 1 | Happy path: plain-text email in S3 → SQS message has correct `email_id`, `from_address`, `subject`, `body`, `received_at`, `raw_s3_key` | Core data-flow correctness |
| 2 | S3 key `raw-emails/<msgid>` → payload `email_id == "<msgid>"` | Pins idempotency-key derivation |
| 3 | URL-encoded S3 key (e.g. `%20`/`+`) → still resolves the right object and `email_id` | S3 event key-encoding quirk |
| 4 | `received_at` equals `get_object()`'s `LastModified.isoformat()` | Pins timestamp source/format |
| 5 | Subject contains `POISON_PILL_MARKER` → SQS message is **missing** the `body` key | Demo fault-injection path |
| 6 | Multipart email in S3 → `body` matches what `parse_email` would extract | Confirms handler wiring to mime_parser |
| 7 | **Boundary**: SQS message body round-trips through `json.loads()` | Catches serialization bugs |
| 8 | `xray_recorder.put_annotation` called with `("email_id", "<msgid>")` | FR13 annotation |

Fixtures (in `conftest.py`): `aws_credentials` (fake env vars); a fixture that creates S3 bucket + SQS queue under `mock_aws()`, sets `TRIAGE_QUEUE_URL`, and yields `handler` reloaded via `importlib.reload()`.

**Implementation**

`src/lambda_ingest/handler.py`

`handler(event, context)`

1. `record = event["Records"][0]["s3"]`.
2. `bucket = record["bucket"]["name"]`.
3. `key = unquote_plus(record["object"]["key"])`.
4. `email_id = key.rsplit("/", 1)[-1]`. Call `xray_recorder.put_annotation("email_id", email_id)`.
5. `response = s3.get_object(Bucket=bucket, Key=key)`.
6. `raw_bytes = response["Body"].read()`.
7. `received_at = response["LastModified"].isoformat()`.
8. `parsed = parse_email(raw_bytes)`.
9. Build `payload` — 6 keys: `email_id`, `from_address`/`subject`/`body` (from `parsed`), `received_at`, `raw_s3_key` (= `key`).
10. Poison-pill check: if `POISON_PILL_MARKER in parsed["subject"]`, delete `body` from `payload`.
11. `sqs.send_message(QueueUrl=os.environ["TRIAGE_QUEUE_URL"], MessageBody=json.dumps(payload))`.

</details>

---

## Phase 4 — Lambda #2 — Triage

Per doc03 §5.2, this Lambda has 5 files. Six stories, ordered by complexity (no-AWS → single-AWS-call → orchestration): 4.1 `keyword_rules.py`, 4.2 `pii.py`, 4.3 `classify.py`, 4.4 `persist.py`, 4.5-4.6 `handler.py`.

---

### 4.1 `keyword_rules.py` (FR7 / DR4)

**Goal:** Pure-Python keyword matching — if the email body/subject contains an escalation phrase, override `urgency` to `"high"`.

**Prereqs:** None — zero AWS dependency. Self-contained like Phase 2.

**Signatures (build these):**

```
src/lambda_triage/keyword_rules.py

ESCALATION_KEYWORDS = [...]  # 10 lowercase phrases

def apply_keyword_override(text: str, urgency: str) -> dict:
    # returns {"urgency": str, "urgency_override_applied": bool}
```

**TDD Order (Red → Green):**
1. test #1 (single keyword match + override) → build basic function
2. test #4 (case-insensitivity) → add `.lower()`
3. test #2 + #3 (multi-word phrases) → confirm `in` substring match
4. test #5 (no match) → passthrough path
5. test #6 (already high, no keyword) → `override_applied=False` distinction
6. test #7 (substring boundary — "shutdown" matches "down") → confirms design choice

**External Docs:**
- [Python `any()` built-in](https://docs.python.org/3/library/functions.html#any)
- [Python `str.lower()`](https://docs.python.org/3/library/stdtypes.html#str.lower)
- [Python `in` operator for substring matching](https://docs.python.org/3/reference/expressions.html#membership-test-operations)

**Input/Output Shapes:**

```python
# INPUT — text: the concatenated subject + redacted body (built in handler 4.5 step 5):
text = "Help with billing I was charged twice for my subscription on [DATE]"
#       ^ subject           ^ " " + pii_result["redacted_text"]

# INPUT — urgency: the model's urgency from classify.py (before keyword override):
urgency = "medium"  # one of: "high", "medium", "low"

# OUTPUT — always exactly these 2 keys:
{"urgency": "high", "urgency_override_applied": True}   # keyword found
{"urgency": "medium", "urgency_override_applied": False} # no keyword found
{"urgency": "high", "urgency_override_applied": False}   # already high, no keyword
```

**Sample Code — implementation pattern:**

```python
ESCALATION_KEYWORDS = [
    "down", "outage", "can't access", "locked out",
    "charged twice", "double charged", "unauthorized charge",
    "cancel my account", "legal action", "data breach",
]

def apply_keyword_override(text: str, urgency: str) -> dict:
    text_lower = text.lower()
    override_applied = any(kw in text_lower for kw in ESCALATION_KEYWORDS)
    if override_applied:
        return {"urgency": "high", "urgency_override_applied": True}
    return {"urgency": urgency, "urgency_override_applied": False}
```

**Sample Code — test pattern:**

```python
def test_outage_triggers_override():
    result = apply_keyword_override("System is down since 3pm", urgency="medium")
    assert result == {"urgency": "high", "urgency_override_applied": True}

def test_no_keyword_passes_through():
    result = apply_keyword_override("Thanks for the quick reply!", urgency="low")
    assert result == {"urgency": "low", "urgency_override_applied": False}
```

> **Context digest:** Case-insensitive **substring** match (doc03 §3.2's explicit choice, not word-boundary). `urgency_override_applied` must reflect whether DR4 specifically fired — not just whether final urgency is "high".

<details><summary><b>Background & design decisions</b></summary>

- Pure Python, zero AWS dependency — this IS the "hardcoded list constant in Lambda #2's shared code module" doc03 §3.2 refers to.
- Case-insensitive **substring** match (doc03 §3.2's explicit choice, not word-boundary) against the redacted body — a deliberate simplification, not a bug, even though it means e.g. "shutdown" would match the `down` keyword.
- `urgency_override_applied` must reflect whether DR4 _specifically_ fired — not just whether the final `urgency` is `"high"` (it could already be `"high"` from DR1 with no keyword match).

</details>

<details><summary><b>Full test table + implementation</b></summary>

**Test** (`tests/lambda_triage/test_keyword_rules.py`)

| # | Test | Why it matters |
|---|------|----------------|
| 1 | Text contains `"outage"` + `urgency="medium"` → `urgency="high"`, `override_applied=True` | Core DR4 override |
| 2 | Text contains `"charged twice"` (multi-word phrase) → override applied | Multi-word phrases match |
| 3 | Text contains `"cancel my account"` → override applied | Escalation/churn category |
| 4 | Text contains `"DATA BREACH"` (mixed case) → override applied | Case-insensitivity |
| 5 | Text contains none of the keywords, `urgency="low"` → `urgency="low"`, `override_applied=False` | No false positives |
| 6 | `urgency="high"` already (no keyword match) → stays `"high"`, `override_applied=False` | Boundary: DR1 vs DR4 |
| 7 | **Boundary**: keyword as substring (e.g., `"shutdown"` matches `"down"`) → override applied | Confirms substring-match design |

No fixtures, no moto — self-contained.

**Implementation**

`ESCALATION_KEYWORDS` — 10 lowercase phrases from doc03 §3.2's 4 categories:
- Outage/access: `"down"`, `"outage"`, `"can't access"`, `"locked out"`
- Billing dispute: `"charged twice"`, `"double charged"`, `"unauthorized charge"`
- Escalation/churn: `"cancel my account"`, `"legal action"`
- Security: `"data breach"`

`apply_keyword_override(text: str, urgency: str) -> dict`

1. `text_lower = text.lower()`.
2. `override_applied = any(keyword in text_lower for keyword in ESCALATION_KEYWORDS)`.
3. If `override_applied`: return `{"urgency": "high", "urgency_override_applied": True}`.
4. Else: return `{"urgency": urgency, "urgency_override_applied": False}`.

</details>

---

### 4.2 `pii.py` (Comprehend `DetectPiiEntities` + redaction, FR3/DR6)

**Goal:** Call Comprehend to detect PII, redact entities above threshold with `[TYPE]` markers, return `{"redacted_text", "pii_entities_detected"}`.

**Prereqs:** 2.1 (`GENERAL_CONFIG`). moto does NOT support Comprehend — use `patch.object(pii.comprehend, "detect_pii_entities", ...)`.

**Signatures (build these):**

```
src/lambda_triage/pii.py

import boto3
from retry_config import GENERAL_CONFIG

comprehend = boto3.client("comprehend", config=GENERAL_CONFIG)
PII_SCORE_THRESHOLD = 0.5

def redact_pii(text: str) -> dict:
    # returns {"redacted_text": str, "pii_entities_detected": int}
```

**TDD Order (Red → Green):**
1. test #1 (single entity redaction) → build basic `redact_pii` with API call + replace
2. test #2 (two entities) → implement left-to-right reconstruction
3. test #6 (out-of-order entities) → add sort by `BeginOffset`
4. test #3 (below threshold) → add score filter
5. test #5 (count only above-threshold) → pin metric source
6. test #4 (no entities) → passthrough path
7. test #7 (edge offsets 0 and len) → boundary check

**External Docs:**
- [Comprehend DetectPiiEntities](https://docs.aws.amazon.com/comprehend/latest/APIReference/API_DetectPiiEntities.html)
- [Comprehend PII entity types](https://docs.aws.amazon.com/comprehend/latest/dg/how-pii.html)
- [boto3 Comprehend client](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/comprehend.html)
- [unittest.mock.patch.object](https://docs.python.org/3/library/unittest.mock.html#unittest.mock.patch.object)
- [unittest.mock — quick guide](https://docs.python.org/3/library/unittest.mock-examples.html)

**Input/Output Shapes:**

```python
# INPUT — text: the raw email body from Lambda #1's payload (before redaction):
text = "Hi, my name is John Doe. Call me at 555-123-4567. I live at 123 Main St."

# INTERMEDIATE — what Comprehend returns (the API response):
{
    "Entities": [
        {"Score": 0.9987, "Type": "NAME", "BeginOffset": 15, "EndOffset": 23},
        {"Score": 0.9500, "Type": "PHONE", "BeginOffset": 35, "EndOffset": 47},
        {"Score": 0.3000, "Type": "ADDRESS", "BeginOffset": 59, "EndOffset": 70},  # below 0.5 threshold
    ]
}

# OUTPUT — redact_pii() always returns exactly these 2 keys:
{
    "redacted_text": "Hi, my name is [NAME]. Call me at [PHONE]. I live at 123 Main St.",
    "pii_entities_detected": 2  # only entities >= 0.5 threshold count
}

# OUTPUT — when no PII found:
{
    "redacted_text": "Thanks for the quick reply!",  # unchanged
    "pii_entities_detected": 0
}
```

**Sample Code — Comprehend API response shape:**

```python
# What comprehend.detect_pii_entities() returns:
{
    "Entities": [
        {"Score": 0.9987, "Type": "NAME", "BeginOffset": 10, "EndOffset": 18},
        {"Score": 0.9500, "Type": "PHONE", "BeginOffset": 35, "EndOffset": 47},
        {"Score": 0.3000, "Type": "ADDRESS", "BeginOffset": 50, "EndOffset": 65},  # below threshold
    ]
}
```

**Sample Code — test with patch.object (moto doesn't support Comprehend):**

```python
from unittest.mock import patch
import pii  # import as module so pii.comprehend is patchable

def test_single_entity_redacted():
    mock_response = {
        "Entities": [
            {"Score": 0.99, "Type": "NAME", "BeginOffset": 5, "EndOffset": 13}
        ]
    }
    with patch.object(pii.comprehend, "detect_pii_entities", return_value=mock_response):
        result = pii.redact_pii("Hello John Doe here")
        assert result["redacted_text"] == "Hello [NAME] here"
        assert result["pii_entities_detected"] == 1
```

**Sample Code — left-to-right reconstruction pattern:**

```python
# text = "Call John Doe at 555-1234"
# entities (sorted): [{Type: NAME, Begin: 5, End: 13}, {Type: PHONE, Begin: 17, End: 25}]
cursor = 0
parts = []
for entity in sorted_entities:
    parts.append(text[cursor:entity["BeginOffset"]])  # "Call " / " at "
    parts.append(f"[{entity['Type']}]")                # "[NAME]" / "[PHONE]"
    cursor = entity["EndOffset"]
parts.append(text[cursor:])  # "" (tail)
redacted_text = "".join(parts)  # "Call [NAME] at [PHONE]"
```

> **Context digest:** Response = `{"Entities": [{"Score": float, "Type": str, "BeginOffset": int, "EndOffset": int}]}`. Offsets are character positions in original text. Sort by `BeginOffset` before reconstruction (Comprehend doesn't guarantee order). Only redact entities with `Score >= 0.5`.

<details><summary><b>Background & design decisions</b></summary>

- `comprehend.detect_pii_entities(Text=..., LanguageCode="en")` returns `{"Entities": [{"Score": float, "Type": "NAME"|"PHONE"|..., "BeginOffset": int, "EndOffset": int}, ...]}` — offsets are character positions in the **original** input text.
- Redaction must not corrupt offsets while rewriting the string. Approach: sort entities by `BeginOffset` ascending, then do a **single left-to-right pass** building a new string — copy `text[cursor:entity.BeginOffset]`, append `[<Type>]`, advance `cursor = entity.EndOffset`, repeat, then append the remaining tail.
- Only entities with `Score >= 0.5` are redacted (doc03 §8.8 threshold).
- **moto does not support Comprehend** — tests `patch.object(pii.comprehend, "detect_pii_entities", return_value=...)`. Simpler than Phase 3's moto-timing problem — no `importlib.reload` needed.
- `comprehend` client uses `GENERAL_CONFIG` (doc03 §4.2).

</details>

<details><summary><b>Full test table + implementation</b></summary>

**Test** (`tests/lambda_triage/test_pii.py`)

| # | Test | Why it matters |
|---|------|----------------|
| 1 | One entity (`NAME`, Score=0.9) → text has `[NAME]` substituted | Core redaction |
| 2 | Two non-overlapping entities → both redacted, surrounding text preserved | Multi-entity reconstruction |
| 3 | Entity with `Score=0.3` (below threshold) → left unredacted, not counted | Pins 0.5 threshold |
| 4 | No entities returned → `redacted_text == text`, `pii_entities_detected == 0` | Clean passthrough |
| 5 | `pii_entities_detected` counts only entities at/above threshold | Metric source separate from redaction |
| 6 | Entities returned out of `BeginOffset` order → redaction still correct | Comprehend doesn't guarantee ordering |
| 7 | **Boundary**: entity at `BeginOffset=0` and another at `EndOffset=len(text)` | String-slicing edge cases |

**Implementation**

`redact_pii(text: str) -> dict`

1. `response = comprehend.detect_pii_entities(Text=text, LanguageCode="en")`.
2. Filter to entities where `Score >= PII_SCORE_THRESHOLD`.
3. Sort filtered entities by `BeginOffset` ascending.
4. Single left-to-right pass: `cursor = 0`, build `parts` list; for each entity append `text[cursor:BeginOffset]` then `f"[{Type}]"`, set `cursor = EndOffset`; after loop append `text[cursor:]`.
5. `redacted_text = "".join(parts)`.
6. Return `{"redacted_text": str, "pii_entities_detected": len(filtered_entities)}`.

</details>

---

### 4.3 `classify.py` (Bedrock invoke + Layer 2 retry, FR4/FR5/FR6/FR17/DR7)

**Goal:** Call Bedrock (Claude Haiku), validate the structured JSON response, retry once with a corrective prompt on failure, degrade to FR17 record on double-failure.

**Prereqs:** 2.1 (`BEDROCK_CONFIG`). moto does NOT support `bedrock-runtime` — use `patch.object(classify.bedrock, "invoke_model", ...)`.

**Signatures (build these):**

```
src/lambda_triage/classify.py

import json, boto3
from retry_config import BEDROCK_CONFIG

bedrock = boto3.client("bedrock-runtime", config=BEDROCK_CONFIG)
MODEL_ID = "anthropic.claude-3-haiku-20240307-v1:0"

VALID_CATEGORIES = {"bug_report", "feature_request", "general_inquiry", "billing", "complaint", "praise"}
VALID_URGENCY = {"high", "medium", "low"}
VALID_SENTIMENT = {"positive", "negative", "constructive"}
VALID_CONFIDENCE = {"high", "medium", "low"}
REQUIRED_FIELDS = {"category", "urgency", "sentiment", "confidence", "suggested_reply"}

SYSTEM_PROMPT = "..."
RETRY_SYSTEM_PROMPT = "..."
DEGRADED_RESULT = {"category": "unclassified", "urgency": "medium", "sentiment": "unknown",
                   "confidence": "low", "suggested_reply": None, "feature_tags": []}

def _invoke(body_text: str, system_prompt: str, max_tokens: int) -> str: ...
def _validate(parsed: dict) -> bool: ...
def _try_parse(raw_text: str) -> dict | None: ...
def classify(body_text: str) -> dict: ...
```

**TDD Order (Red → Green):**
1. test #1 (valid response, happy path) → build `_invoke` + `_try_parse` + `classify` skeleton
2. test #4 (missing required key) → build `_validate` with field check
3. test #5 (invalid enum value) → add enum validation to `_validate`
4. test #2 (invalid then valid → retry) → wire attempt-2 with `RETRY_SYSTEM_PROMPT` + `max_tokens=768`
5. test #3 (both fail → degraded) → add `DEGRADED_RESULT` return path
6. test #6 (missing `feature_tags` defaults to `[]`) → add `setdefault` in `_try_parse`
7. test #7 (single-read boundary) → verify no double-read on retry path

**External Docs:**
- [Bedrock InvokeModel API](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_InvokeModel.html)
- [Anthropic Messages format on Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/model-parameters-anthropic-claude-messages.html)
- [Bedrock supported models](https://docs.aws.amazon.com/bedrock/latest/userguide/models-supported.html)
- [StreamingBody (botocore)](https://botocore.amazonaws.com/v1/documentation/api/latest/reference/response.html#botocore.response.StreamingBody)
- [json.JSONDecodeError](https://docs.python.org/3/library/json.html#json.JSONDecodeError)
- [io.BytesIO](https://docs.python.org/3/library/io.html#io.BytesIO)

**Input/Output Shapes:**

```python
# INPUT — body_text: the PII-redacted email body from pii.redact_pii():
body_text = "Hi, my name is [NAME]. I was charged twice for my subscription on [DATE]."

# OUTPUT — classify() on SUCCESS (valid model response):
{
    "category": "billing",                      # one of VALID_CATEGORIES
    "urgency": "high",                          # one of: high, medium, low
    "sentiment": "negative",                    # one of: positive, negative, constructive
    "confidence": "high",                       # one of: high, medium, low
    "suggested_reply": "We'll investigate the duplicate charge and issue a refund.",
    "feature_tags": [],                         # always present (setdefault)
    "classification_failed": False              # added by classify(), not the model
}

# OUTPUT — classify() on FAILURE (both attempts failed → FR17 degraded):
{
    "category": "unclassified",
    "urgency": "medium",
    "sentiment": "unknown",
    "confidence": "low",
    "suggested_reply": None,
    "feature_tags": [],
    "classification_failed": True               # handler uses this for DR7 metric
}

# OUTPUT — classify() for a feature_request:
{
    "category": "feature_request",
    "urgency": "low",
    "sentiment": "constructive",
    "confidence": "high",
    "suggested_reply": "Thank you for the suggestion! We'll add it to our backlog.",
    "feature_tags": ["dark-mode", "mobile-app"],  # only meaningful for feature_request
    "classification_failed": False
}

# INTERNAL — what the MODEL returns (the raw text inside Bedrock envelope):
'{"category":"billing","urgency":"high","sentiment":"negative","confidence":"high","suggested_reply":"We\'ll investigate...","feature_tags":[]}'

# ─── INTERNAL HELPER SHAPES ───

# _invoke(body_text: str, system_prompt: str, max_tokens: int) -> str
# INPUT:
#   body_text = "Hi, my name is [NAME]. I was charged twice..."
#   system_prompt = SYSTEM_PROMPT (or RETRY_SYSTEM_PROMPT on attempt 2)
#   max_tokens = 512 (attempt 1) or 768 (attempt 2)
# OUTPUT: the raw text string from the model (before second JSON decode):
"'{"category":"billing","urgency":"high",...}'"  # valid — _try_parse will succeed
"Sure! Here is the classification:\n{..."        # invalid — _try_parse returns None

# _validate(parsed: dict) -> bool
# INPUT: a dict that successfully json.loads'd from the model text:
parsed = {"category": "billing", "urgency": "high", "sentiment": "negative",
           "confidence": "high", "suggested_reply": "..."}
# OUTPUT:
True   # all REQUIRED_FIELDS present AND all enum values in their VALID_* sets
False  # missing key (e.g. no "confidence") OR invalid value (e.g. urgency="critical")

# _try_parse(raw_text: str) -> dict | None
# INPUT: the raw string returned by _invoke():
raw_text = '{"category":"billing","urgency":"high","sentiment":"negative","confidence":"high","suggested_reply":"...","feature_tags":["dark-mode"]}'
# OUTPUT on success (valid JSON + passes _validate):
{"category": "billing", "urgency": "high", "sentiment": "negative",
 "confidence": "high", "suggested_reply": "...", "feature_tags": ["dark-mode"]}
# OUTPUT on success when model omits feature_tags (setdefault adds it):
{"category": "billing", ..., "feature_tags": []}  # [] added by setdefault
# OUTPUT on failure (json.JSONDecodeError OR _validate returns False):
None
```

**Sample Code — Bedrock invoke_model request + response:**

```python
import json

# REQUEST (Anthropic Messages format for Bedrock):
response = bedrock.invoke_model(
    modelId="anthropic.claude-3-haiku-20240307-v1:0",
    contentType="application/json",
    accept="application/json",
    body=json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 512,
        "temperature": 0.0,
        "system": "Return ONLY a JSON object with these fields: ...",
        "messages": [{"role": "user", "content": "Classify this email: ..."}]
    })
)

# RESPONSE — response["body"] is a StreamingBody:
envelope = json.loads(response["body"].read())
# envelope = {"content": [{"type": "text", "text": '{"category":"billing",...}'}]}
model_text = envelope["content"][0]["text"]  # a JSON STRING needing second decode
parsed = json.loads(model_text)              # {"category": "billing", "urgency": "high", ...}
```

**Sample Code — mock_bedrock_response helper + test pattern:**

```python
import io
import json
from unittest.mock import patch
import classify

def mock_bedrock_response(text: str) -> dict:
    """Simulates Bedrock's StreamingBody — io.BytesIO has .read()"""
    envelope = json.dumps({"content": [{"type": "text", "text": text}]}).encode()
    return {"body": io.BytesIO(envelope)}

def test_valid_response_on_first_attempt():
    valid_json = json.dumps({
        "category": "billing",
        "urgency": "high",
        "sentiment": "negative",
        "confidence": "high",
        "suggested_reply": "We'll investigate the charge.",
        "feature_tags": []
    })
    with patch.object(classify.bedrock, "invoke_model",
                      return_value=mock_bedrock_response(valid_json)) as mock_invoke:
        result = classify.classify("I was charged twice for my subscription")
        assert result["category"] == "billing"
        assert result["classification_failed"] is False
        assert mock_invoke.call_count == 1

def test_invalid_then_valid_triggers_retry():
    valid_json = json.dumps({"category": "billing", "urgency": "high",
                             "sentiment": "negative", "confidence": "high",
                             "suggested_reply": "...", "feature_tags": []})
    with patch.object(classify.bedrock, "invoke_model",
                      side_effect=[
                          mock_bedrock_response("not json at all"),   # attempt 1 fails
                          mock_bedrock_response(valid_json),          # attempt 2 succeeds
                      ]) as mock_invoke:
        result = classify.classify("some email text")
        assert result["classification_failed"] is False
        assert mock_invoke.call_count == 2
        # Verify attempt 2 used larger max_tokens:
        second_call_body = json.loads(mock_invoke.call_args_list[1][1]["body"])
        assert second_call_body["max_tokens"] == 768
```

**Sample Code — single-read boundary test (test #7):**

```python
class SingleReadBytesIO(io.BytesIO):
    """Raises on second .read() to catch accidental double-reads."""
    def __init__(self, data):
        super().__init__(data)
        self._read_count = 0

    def read(self, *args):
        self._read_count += 1
        if self._read_count > 1:
            raise IOError("StreamingBody read twice!")
        return super().read(*args)
```

> **Context digest:** Double JSON decode — `response["body"].read()` gives the Bedrock envelope `{"content": [{"type": "text", "text": "..."}]}`; that `text` field is itself a JSON string needing a second `json.loads()`. Attempt 1 = `max_tokens=512`; attempt 2 = `max_tokens=768` (guards truncation). Enum values defined HERE (not doc03). DEGRADE-not-RAISE on Bedrock failure (doc03 §4.5).

<details><summary><b>Background & design decisions</b></summary>

- Claude on Bedrock via `bedrock-runtime.invoke_model(modelId=..., body=json.dumps({...}))` uses the Anthropic Messages format: `{"anthropic_version": "bedrock-2023-05-31", "max_tokens": ..., "temperature": ..., "system": "...", "messages": [{"role": "user", "content": "..."}]}`.
- **Double JSON decode**: `response["body"]` is a `StreamingBody` (same `.read()` quirk as S3) → `json.loads()` gives the Bedrock envelope `{"content": [{"type": "text", "text": "..."}]}`. That `text` field is itself a _string_ containing the model's JSON output — needs a **second** `json.loads()`. Each retry is a fresh `invoke_model` call with its own fresh `StreamingBody`, so there's no "read twice" issue across retries.
- **New design decision — category/sentiment enums** (doc01/doc03 establish the _fields_ FR4 requires but not the literal enum values; this story defines them):
  - `category`: `bug_report` | `feature_request` | `general_inquiry` | `billing` | `complaint` | `praise` (the "6 FR4 categories"), or `unclassified` (FR17)
  - `sentiment`: `positive` | `negative` | `constructive`, or `unknown` (FR17)
  - `urgency`/`confidence`: `high` | `medium` | `low`
  - `feature_tags`: list of strings, only meaningful when `category="feature_request"` (FR6)
- **Layer 2 retry** (doc03 §4.3): attempt 1 uses `max_tokens=512`; if the model's `text` isn't valid JSON, OR is missing a required key, OR has an enum value outside the sets above → retry once with a corrective system prompt + `max_tokens=768` (guards against truncation). Exhausting both → FR17 degraded record + `classification_failed=True`.
- **moto does not support `bedrock-runtime`** — same pattern as 4.2's Comprehend.
- Uses Phase 2's `BEDROCK_CONFIG` (read_timeout=10s).

**Sample `invoke_model` call:**

```python
response = bedrock.invoke_model(
    modelId=MODEL_ID,
    contentType="application/json",
    accept="application/json",
    body=json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 512,
        "temperature": 0.0,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": body_text}]
    })
)
raw_text = json.loads(response["body"].read())["content"][0]["text"]
```

</details>

<details><summary><b>Full test table + implementation</b></summary>

**Test** (`tests/lambda_triage/test_classify.py`)

| # | Test | Why it matters |
|---|------|----------------|
| 1 | Valid JSON on attempt 1 → returns parsed dict, `classification_failed=False`, only 1 `invoke_model` call | Happy path |
| 2 | Invalid JSON on attempt 1, valid on attempt 2 → returns attempt-2 result; attempt 2 called with `max_tokens=768` and corrective system prompt | Retry escalation |
| 3 | Invalid JSON on **both** attempts → returns FR17 degraded dict, `classification_failed=True` | DR7 fallback |
| 4 | Valid JSON but missing a required key (e.g. no `confidence`) → treated as invalid, triggers retry | Validation beyond json.loads |
| 5 | Valid JSON but `urgency="critical"` (not in VALID_URGENCY) → treated as invalid, triggers retry | Enum validation |
| 6 | `category="general_inquiry"`, response omits `feature_tags` → result has `feature_tags=[]` | FR6 — field must always exist for persist.py |
| 7 | **Boundary**: `response["body"]` consumed via `.read()` exactly once per call — raises on second `.read()` | Catches double-read bug on retry path |

Helper: `mock_bedrock_response(text: str) -> dict` returns `{"body": io.BytesIO(json.dumps({"content": [{"type": "text", "text": text}]}).encode())}`.

**Implementation**

`_invoke(body_text, system_prompt, max_tokens) -> str`

1. `bedrock.invoke_model(modelId=MODEL_ID, contentType="application/json", accept="application/json", body=json.dumps({...}))` — Anthropic Messages format: `anthropic_version="bedrock-2023-05-31"`, `max_tokens`, `temperature=0.0`, `system=system_prompt`, `messages=[{"role": "user", "content": body_text}]`.
2. `response_body = json.loads(response["body"].read())` — first decode.
3. Return `response_body["content"][0]["text"]`.

`_validate(parsed: dict) -> bool`

1. Check `REQUIRED_FIELDS.issubset(parsed.keys())`.
2. Check `category`/`urgency`/`sentiment`/`confidence` each in their `VALID_*` set.
3. Return `True` only if both pass.

`_try_parse(raw_text: str) -> dict | None`

1. `json.loads(raw_text)` — catch `JSONDecodeError` → return `None`.
2. `_validate(parsed)` — if `False`, return `None`.
3. `parsed.setdefault("feature_tags", [])`.
4. Return `parsed`.

`classify(body_text: str) -> dict`

1. Attempt 1: `_invoke(body_text, SYSTEM_PROMPT, max_tokens=512)` → `_try_parse(...)`.
2. If valid: return `{**parsed, "classification_failed": False}`.
3. Attempt 2: `_invoke(body_text, RETRY_SYSTEM_PROMPT, max_tokens=768)` → `_try_parse(...)`.
4. If valid: return `{**parsed, "classification_failed": False}`.
5. Both failed: return `{**DEGRADED_RESULT, "classification_failed": True}`.

</details>

---

### 4.4 `persist.py` (idempotency `GetItem` + `PutItem`, FR8/§4.6)

**Goal:** DynamoDB idempotency check (`get_existing_record`) and write (`put_triage_record`) using the boto3 resource API for native Python type handling.

**Prereqs:** 2.1 (`GENERAL_CONFIG`). moto fully supports DynamoDB — use `@mock_aws`. Module-level `table` requires `importlib.reload(persist)` inside `mock_aws()` context (same as 3.2).

**Signatures (build these):**

```
src/lambda_triage/persist.py

import os
from datetime import datetime, timezone
import boto3
from retry_config import GENERAL_CONFIG

dynamodb = boto3.resource("dynamodb", config=GENERAL_CONFIG)
table = dynamodb.Table(os.environ["DYNAMODB_TABLE_NAME"])
TTL_SECONDS = 90 * 24 * 60 * 60  # 7_776_000

def get_existing_record(email_id: str) -> dict | None: ...
def put_triage_record(record: dict) -> None: ...
```

**TDD Order (Red → Green):**
1. test #1 (get with no item → `None`) → build `get_existing_record`
2. test #2 (put then get round-trip) → build `put_triage_record`
3. test #3 (TTL derivation) → add `fromisoformat` + epoch + 90 days
4. test #4 (`processed_at` computed at write time) → add `datetime.now(timezone.utc).isoformat()`
5. test #5 (`None` / `[]` round-trip) → should pass with resource API
6. test #6 (`bool` round-trip) → should pass with resource API
7. test #7 (idempotency boundary) → confirm non-`None` after put

**External Docs:**
- [DynamoDB resource API (Table)](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/dynamodb.html)
- [Table.get_item](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/dynamodb/table/get_item.html)
- [Table.put_item](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/dynamodb/table/put_item.html)
- [DynamoDB TTL](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/TTL.html)
- [Resource API vs Client API](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/migration.html#resource-objects)
- [datetime.fromisoformat](https://docs.python.org/3/library/datetime.html#datetime.datetime.fromisoformat)
- [moto DynamoDB support](https://docs.getmoto.org/en/latest/docs/services/dynamodb.html)

**Input/Output Shapes:**

```python
# INPUT to get_existing_record — just the email_id string:
email_id = "abc123def456"  # the SES messageId from Lambda #1

# OUTPUT of get_existing_record — None if not found, full item dict if found:
None                         # not found → handler proceeds with processing
{"email_id": "abc123def456", "category": "billing", ...}  # found → handler short-circuits

# INPUT to put_triage_record — the full 15-field record dict from handler step 7:
record = {
    "email_id": "abc123def456",
    "received_at": "2026-06-21T14:30:00+00:00",
    "from_address": "jane@example.com",
    "subject": "Charged twice",
    "raw_s3_key": "raw-emails/abc123def456",
    "category": "billing",
    "urgency": "high",
    "sentiment": "negative",
    "confidence": "high",
    "suggested_reply": "We'll investigate the duplicate charge.",
    "feature_tags": [],
    "urgency_override_applied": True,
    "review_status": "auto_processed",
    "pii_entities_detected": 2,
    "redacted_body": "Hi, my name is [NAME]. I was charged twice..."
}

# WHAT GETS WRITTEN TO DYNAMODB (put_triage_record adds 2 fields):
{
    **record,                                                    # all 15 fields above
    "processed_at": "2026-06-21T14:30:05+00:00",               # computed at write time
    "ttl": 1758466200                                            # epoch + 90 days
}
```

**Sample Code — get_item response shapes:**

```python
# When item EXISTS:
response = table.get_item(Key={"email_id": "abc123"})
# response = {"Item": {"email_id": "abc123", "category": "billing", ...}, "ResponseMetadata": {...}}
item = response.get("Item")  # {"email_id": "abc123", ...}

# When item DOES NOT EXIST:
response = table.get_item(Key={"email_id": "nonexistent"})
# response = {"ResponseMetadata": {...}}  — NO "Item" key at all!
item = response.get("Item")  # None (NOT KeyError)
```

**Sample Code — TTL calculation:**

```python
from datetime import datetime, timezone

received_at_str = "2026-06-21T14:30:00+00:00"
received_at = datetime.fromisoformat(received_at_str)
ttl = int(received_at.timestamp()) + (90 * 24 * 60 * 60)  # epoch + 90 days
```

**Sample Code — test with moto + reload:**

```python
import importlib, os, boto3
from moto import mock_aws

@mock_aws
def test_put_then_get_roundtrip():
    os.environ["DYNAMODB_TABLE_NAME"] = "EmailTriageResults-dev"

    # Create table under mock
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    dynamodb.create_table(
        TableName="EmailTriageResults-dev",
        KeySchema=[{"AttributeName": "email_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "email_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )

    # Reload so module-level `table` binds to moto
    import persist
    importlib.reload(persist)

    record = {"email_id": "msg-001", "received_at": "2026-06-21T10:00:00+00:00", ...}
    persist.put_triage_record(record)
    result = persist.get_existing_record("msg-001")
    assert result is not None
    assert result["email_id"] == "msg-001"
```

> **Context digest:** Uses `boto3.resource` (not client) — accepts/returns native Python types (no `{"S": "..."}` wrappers). `get_item` response has **no `"Item"` key** when not found (not `None`), so use `.get("Item")`. `processed_at` and `ttl` are computed at write time, not passed in.

<details><summary><b>Background & design decisions</b></summary>

- **Resource API vs. client API** — `persist.py` uses `boto3.resource("dynamodb", ...)`. The resource API accepts/returns native Python types directly; the client API requires DynamoDB's typed-attribute format for every field. Given 16 attributes of mixed types including a list and a nullable field, the resource API avoids marshalling bugs.
- `table.get_item(Key={"email_id": email_id})` → response **has no `"Item"` key at all** if not found. Must use `response.get("Item")`.
- `ttl` = `received_at` parsed via `datetime.fromisoformat()` → `.timestamp()` → epoch seconds (int) + 90 days.
- `processed_at` = `datetime.now(timezone.utc).isoformat()`, set at write time.
- Table name from `os.environ["DYNAMODB_TABLE_NAME"]`.
- **moto fully supports DynamoDB** — but module-level `table` requires `importlib.reload(persist)` inside `mock_aws()`.

</details>

<details><summary><b>Full test table + implementation</b></summary>

**Test** (`tests/lambda_triage/test_persist.py`)

| # | Test | Why it matters |
|---|------|----------------|
| 1 | `get_existing_record(email_id)` with no item → returns `None` | §4.6 idempotency "not found" path |
| 2 | `put_triage_record(record)` then `get_existing_record(email_id)` → returns same data | Round-trip correctness |
| 3 | `ttl` stored is `int(received_at.timestamp()) + 7_776_000` | Pins TTL derivation |
| 4 | `processed_at` is an ISO8601 string not present in input `record` | Computed at write time |
| 5 | `suggested_reply=None` and `feature_tags=[]` round-trip correctly | Resource API NULL/list handling |
| 6 | `urgency_override_applied=True`/`False` round-trips as Python `bool` | Resource API BOOL handling |
| 7 | **Boundary**: after put, get for same `email_id` returns non-`None` | Idempotency short-circuit works |

**Implementation**

`get_existing_record(email_id: str) -> dict | None`

1. `response = table.get_item(Key={"email_id": email_id})`.
2. Return `response.get("Item")`.

`put_triage_record(record: dict) -> None`

1. `received_at = datetime.fromisoformat(record["received_at"])`.
2. `ttl = int(received_at.timestamp()) + TTL_SECONDS`.
3. Build `item = {**record, "processed_at": datetime.now(timezone.utc).isoformat(), "ttl": ttl}`.
4. `table.put_item(Item=item)`.

</details>

---

### 4.5 `handler.py` — orchestration core (doc03 §2.1 steps 9-15)

**Goal:** Parse SQS message, run idempotency check, call `pii` → `classify` → `keyword_rules` → `persist`. Build the 15-field triage record.

**Prereqs:** 4.1–4.4 all green. Double-mocking: `mock_aws()` for DynamoDB (via `persist`) + `patch.object(pii.comprehend, ...)` + `patch.object(classify.bedrock, ...)`. Reload chain: reload `persist`, `pii`, `classify`, then `handler` inside the mock context.

**Signatures (build these):**

```
src/lambda_triage/handler.py

import json
import pii, classify, keyword_rules, persist
from aws_xray_sdk.core import xray_recorder

xray_recorder.configure(context_missing="LOG_ERROR")

def handler(event, context):
    # SQS event → idempotency check → pii → classify → keyword → persist
```

**TDD Order (Red → Green):**
1. test #1 (happy path, all 15 fields) → build full handler skeleton steps 1-8
2. test #2 (idempotency short-circuit) → add `get_existing_record` check + early return
3. test #7 (poison pill `KeyError`) → confirm no try/except
4. test #3 + #4 (review_status routing) → add `confidence`/`classification_failed` logic
5. test #5 (keyword override wins over model urgency) → wire `apply_keyword_override`
6. test #6 (`feature_tags` round-trip) → should pass via `classify` + `persist`
7. test #8 (`pii_entities_detected=0` present) → confirm field always included
8. test #9 (X-Ray annotation) → add `put_annotation` call

**External Docs:**
- [SQS event source mapping for Lambda](https://docs.aws.amazon.com/lambda/latest/dg/with-sqs.html)
- [Lambda event source mapping (batch size)](https://docs.aws.amazon.com/lambda/latest/dg/API_CreateEventSourceMapping.html)
- [SQS Lambda event format](https://docs.aws.amazon.com/lambda/latest/dg/with-sqs.html#example-standard-queue-message-event)
- [Python importlib.reload](https://docs.python.org/3/library/importlib.html#importlib.reload)

**Input/Output Shapes:**

```python
# INPUT — event (SQS trigger, batch_size=1):
event = {
    "Records": [{
        "body": '{"email_id":"msg-001","from_address":"jane@example.com","subject":"Help","body":"I need help with...","received_at":"2026-06-21T10:00:00+00:00","raw_s3_key":"raw-emails/msg-001"}'
    }]
}
# Note: body is a JSON STRING, not a dict — must json.loads() it
message = json.loads(event["Records"][0]["body"])

# INTERMEDIATE — message (after json.loads, these are the 6 keys from Lambda #1):
message = {
    "email_id": "msg-001",
    "from_address": "jane@example.com",
    "subject": "Help with billing",
    "body": "Hi, my name is John Doe. I was charged twice for my subscription.",
    "received_at": "2026-06-21T10:00:00+00:00",
    "raw_s3_key": "raw-emails/msg-001"
}

# INTERMEDIATE — pii_result (from pii.redact_pii(message["body"])):
pii_result = {
    "redacted_text": "Hi, my name is [NAME]. I was charged twice for my subscription.",
    "pii_entities_detected": 1
}

# INTERMEDIATE — classification (from classify.classify(pii_result["redacted_text"])):
classification = {
    "category": "billing", "urgency": "medium", "sentiment": "negative",
    "confidence": "high", "suggested_reply": "We'll investigate...",
    "feature_tags": [], "classification_failed": False
}

# INTERMEDIATE — override (from keyword_rules.apply_keyword_override(...)):
override = {"urgency": "high", "urgency_override_applied": True}

# OUTPUT — the 15-field record dict passed to persist.put_triage_record():
record = {
    "email_id": "msg-001",                          # from message
    "received_at": "2026-06-21T10:00:00+00:00",    # from message
    "from_address": "jane@example.com",             # from message
    "subject": "Help with billing",                 # from message
    "raw_s3_key": "raw-emails/msg-001",             # from message
    "category": "billing",                          # from classification
    "sentiment": "negative",                        # from classification
    "confidence": "high",                           # from classification
    "suggested_reply": "We'll investigate...",      # from classification
    "feature_tags": [],                             # from classification
    "urgency": "high",                              # from override (NOT classification)
    "urgency_override_applied": True,               # from override
    "review_status": "auto_processed",              # computed: confidence=high + not failed
    "pii_entities_detected": 1,                     # from pii_result
    "redacted_body": "Hi, my name is [NAME]. I was charged twice..."  # pii_result["redacted_text"]
}

# HANDLER RETURN VALUE:
# - Normal path: returns None (implicit) — SQS deletes the message on success
# - Idempotency short-circuit: returns None (explicit) — same effect
# - Poison-pill / failure: raises (KeyError, etc.) — SQS redelivers up to maxReceiveCount
# The handler has NO explicit return value — success = no exception raised

# review_status logic:
# "needs_review" if classification["confidence"] != "high" OR classification["classification_failed"]
# "auto_processed" otherwise
```

**Sample Code — double-mocking pattern (moto + patch.object):**

```python
import importlib, os, json, boto3
from unittest.mock import patch
from moto import mock_aws

@mock_aws
def test_happy_path():
    os.environ["DYNAMODB_TABLE_NAME"] = "EmailTriageResults-dev"
    os.environ["ALERT_TOPIC_ARN"] = "arn:aws:sns:us-east-1:123:alert-topic"

    # Create DynamoDB table (moto supports it)
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    dynamodb.create_table(
        TableName="EmailTriageResults-dev",
        KeySchema=[{"AttributeName": "email_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "email_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )

    # Reload modules inside mock context
    import persist, pii, classify, handler
    importlib.reload(persist)

    # Patch services moto doesn't support
    mock_pii_response = {"Entities": []}
    mock_classify_result = {
        "category": "billing", "urgency": "high", "sentiment": "negative",
        "confidence": "high", "suggested_reply": "...", "feature_tags": [],
        "classification_failed": False
    }

    with patch.object(pii.comprehend, "detect_pii_entities", return_value=mock_pii_response), \
         patch.object(classify.bedrock, "invoke_model", return_value=mock_bedrock_response(valid_json)):
        importlib.reload(handler)
        handler.handler(event, None)
        # Assert DynamoDB has the record
        result = persist.get_existing_record("msg-001")
        assert result is not None
```

**Sample Code — importing siblings as modules (for patchability):**

```python
# CORRECT — keeps pii.comprehend, classify.bedrock accessible for tests:
import pii
import classify
import keyword_rules
import persist

# WRONG — loses the reference path tests need to patch:
from pii import redact_pii
from classify import classify
```

> **Context digest:** `event["Records"][0]["body"]` is a JSON string (batch_size=1). Idempotency guard runs FIRST. No try/except — RAISE on Comprehend/DynamoDB failure. Bedrock failures don't raise (classify degrades internally). `keyword_input` = `subject + " " + redacted_text` (not raw body). Import siblings as modules (not `from X import Y`) to keep clients patchable.

<details><summary><b>Background & design decisions</b></summary>

- SQS message body is the JSON string Lambda #1 sent: `message = json.loads(event["Records"][0]["body"])`. Batch size is 1, so `event["Records"]` always has exactly one element.
- **Idempotency guard** (doc03 §4.6): `persist.get_existing_record(message["email_id"])` runs first. If non-`None`, return immediately.
- `handler.py` imports sibling modules (`pii`, `classify`, `keyword_rules`, `persist`) and calls their functions. Each sibling constructs its own client at import time.
- **Double-mocking**: tests combine `mock_aws()` (for DynamoDB) with `patch.object(pii.comprehend, ...)` and `patch.object(classify.bedrock, ...)`.
- **Poison-pill**: if Lambda #1 omitted `body`, `message["body"]` raises `KeyError` immediately — before any AWS calls.
- **`keyword_input`**: `message["subject"] + " " + pii_result["redacted_text"]` — matches against redacted text, not raw body.
- **X-Ray annotation**: `put_annotation("email_id", message["email_id"])` right after parsing, before idempotency check.

</details>

<details><summary><b>Full test table + implementation</b></summary>

**Test** (`tests/lambda_triage/test_handler.py`, part 1)

| # | Test | Why it matters |
|---|------|----------------|
| 1 | Happy path, `confidence="high"` → `put_triage_record` called with all 15 fields, `review_status="auto_processed"` | Core orchestration |
| 2 | `get_existing_record` returns existing item → handler returns early; Comprehend/Bedrock/put not called | §4.6 idempotency |
| 3 | `confidence="low"` → `review_status="needs_review"` | DR5 routing |
| 4 | `classification_failed=True` → `review_status="needs_review"` regardless of confidence | FR17/DR7 routing |
| 5 | Keyword match + Bedrock `urgency="medium"` → persisted `urgency="high"`, `override_applied=True` | Keyword override wins |
| 6 | `category="feature_request"` with non-empty `feature_tags` → persisted as-is | FR6 round-trip |
| 7 | **Boundary**: SQS message missing `body` key → `KeyError` raised, not caught | Poison-pill path |
| 8 | **Boundary**: Comprehend returns zero entities → `pii_entities_detected=0` (field present) | Metric always present |
| 9 | `xray_recorder.put_annotation` called with `("email_id", ...)` including on idempotency path | FR13 |

**Implementation**

`handler(event, context)` — steps 1-8:

1. `message = json.loads(event["Records"][0]["body"])`. Call `xray_recorder.put_annotation("email_id", message["email_id"])`.
2. Idempotency: `existing = persist.get_existing_record(message["email_id"])`. If not None, return.
3. `pii_result = pii.redact_pii(message["body"])`.
4. `classification = classify.classify(pii_result["redacted_text"])`.
5. `keyword_input = message["subject"] + " " + pii_result["redacted_text"]`; `override = keyword_rules.apply_keyword_override(keyword_input, classification["urgency"])`.
6. `review_status`: `"needs_review"` if `classification["confidence"] != "high"` or `classification["classification_failed"]`, else `"auto_processed"`.
7. Build `record` — 15 keys: `email_id`/`received_at`/`from_address`/`subject`/`raw_s3_key` (from message) + `category`/`sentiment`/`confidence`/`suggested_reply`/`feature_tags` (from classification) + `urgency`/`urgency_override_applied` (from override) + `review_status` + `pii_entities_detected`/`redacted_body` (from pii_result).
8. `persist.put_triage_record(record)`.

</details>

---

### 4.6 `handler.py` — alerting + EMF metrics (doc03 §2.1 steps 16-18)

**Goal:** After persist (step 8), determine alert type, publish to SNS (DEGRADE on failure), emit CloudWatch EMF metrics. Extends the same `handler()` function from 4.5.

**Prereqs:** 4.5 green. moto supports SNS (`create_topic` under `mock_aws()`). Adds `sns = boto3.client("sns", ...)` to module scope.

**Signatures (build these):**

```
# Added to src/lambda_triage/handler.py (after 4.5's code)

import os, boto3
from retry_config import GENERAL_CONFIG

sns = boto3.client("sns", config=GENERAL_CONFIG)

def _alert_type(record: dict) -> str: ...
def _build_alert_body(record: dict, alert_type: str) -> dict: ...
def _emit_emf(record: dict, classification_failed: bool, alert_publish_failed: bool) -> None: ...
# handler() steps 9-12 appended after step 8
```

**TDD Order (Red → Green):**
1. test #1 (urgent alert → SNS publish with correct MessageAttributes + body) → build `_alert_type` + `_build_alert_body` + SNS publish
2. test #2 + #3 (needs_review paths with review_reason) → extend `_build_alert_body`
3. test #4 (none → minimal body, data-minimization) → add `"none"` shape
4. test #5 (precedence: urgent wins over needs_review) → confirm `_alert_type` order
5. test #6 + #7 + #8 (EMF metrics) → build `_emit_emf`
6. test #9 (SNS failure → DEGRADE, no re-raise, `AlertPublishFailure` metric) → add try/except around publish

**External Docs:**
- [SNS Publish with MessageAttributes](https://docs.aws.amazon.com/sns/latest/api/API_Publish.html)
- [SNS subscription filter policies](https://docs.aws.amazon.com/sns/latest/dg/sns-subscription-filter-policies.html)
- [SNS MessageAttributes format](https://docs.aws.amazon.com/sns/latest/dg/sns-message-attributes.html)
- [CloudWatch Embedded Metric Format spec](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch_Embedded_Metric_Format_Specification.html)
- [EMF specification (JSON schema)](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch_Embedded_Metric_Format_Specification.html#CloudWatch_Embedded_Metric_Format_Specification_structure)
- [pytest capsys fixture](https://docs.pytest.org/en/stable/how-to/capture-warnings.html)
- [moto SNS support](https://docs.getmoto.org/en/latest/docs/services/sns.html)

**Input/Output Shapes:**

```python
# INPUT — record: the 15-field dict from step 8 (same as persist input):
record = {
    "email_id": "msg-001", "received_at": "2026-06-21T10:00:00+00:00",
    "from_address": "jane@example.com", "subject": "Help with billing",
    "raw_s3_key": "raw-emails/msg-001", "category": "billing",
    "urgency": "high", "sentiment": "negative", "confidence": "high",
    "suggested_reply": "We'll investigate...", "feature_tags": [],
    "urgency_override_applied": True, "review_status": "auto_processed",
    "pii_entities_detected": 1, "redacted_body": "Hi, my name is [NAME]..."
}

# _alert_type(record) → determines which alert path:
"urgent"       # when record["urgency"] == "high"
"needs_review" # when record["review_status"] == "needs_review" (and not urgent)
"none"         # otherwise

# _build_alert_body() — 3 shapes depending on alert_type:

# "urgent" shape (full context for immediate action):
{
    "email_id": "msg-001", "alert_type": "urgent",
    "received_at": "2026-06-21T10:00:00+00:00",
    "from_address": "jane@example.com", "subject": "Help with billing",
    "category": "billing", "urgency": "high", "urgency_override_applied": True,
    "sentiment": "negative", "confidence": "high",
    "suggested_reply": "We'll investigate..."
}

# "needs_review" shape (+ review_reason, - urgency_override_applied):
{
    "email_id": "msg-002", "alert_type": "needs_review",
    "received_at": "...", "from_address": "...", "subject": "...",
    "category": "general_inquiry", "urgency": "low", "sentiment": "constructive",
    "confidence": "low", "suggested_reply": "...",
    "review_reason": "low_confidence"  # or "classification_failed"
}

# "none" shape (minimal — data-minimization):
{
    "email_id": "msg-003", "alert_type": "none",
    "received_at": "...",
    "category": "praise", "urgency": "low", "sentiment": "positive", "confidence": "high"
}

# _emit_emf(record, classification_failed, alert_publish_failed) -> None
# INPUT:
#   record = the 15-field dict (uses record["sentiment"] and record["pii_entities_detected"])
#   classification_failed = True/False (from classification["classification_failed"])
#   alert_publish_failed = True/False (from the try/except around sns.publish)
# OUTPUT: prints ONE JSON line to stdout (captured by CloudWatch Logs → EMF processor):

# When classification_failed=False, alert_publish_failed=False:
'{"_aws":{"Timestamp":...,"CloudWatchMetrics":[{"Namespace":"ECHO","Dimensions":[["sentiment"]],"Metrics":[{"Name":"SentimentCount","Unit":"Count"},{"Name":"PiiEntitiesDetected","Unit":"Count"}]}]},"sentiment":"negative","SentimentCount":1,"PiiEntitiesDetected":2}'

# When classification_failed=True:
# Same as above + "ClassificationFailure": 1 in top-level keys and Metrics array

# When alert_publish_failed=True:
# Same as above + "AlertPublishFailure": 1 in top-level keys and Metrics array
```

**Sample Code — SNS publish with MessageAttributes:**

```python
sns.publish(
    TopicArn=os.environ["ALERT_TOPIC_ARN"],
    Message=json.dumps(alert_body),
    MessageAttributes={
        "alert_type": {
            "DataType": "String",
            "StringValue": "urgent"  # subscribers filter on this
        }
    }
)
```

**Sample Code — EMF document structure:**

```python
emf_document = {
    "_aws": {
        "Timestamp": 1719000000000,
        "CloudWatchMetrics": [{
            "Namespace": "ECHO",
            "Dimensions": [["sentiment"]],
            "Metrics": [
                {"Name": "SentimentCount", "Unit": "Count"},
                {"Name": "PiiEntitiesDetected", "Unit": "Count"},
                # Conditional — only included when True:
                # {"Name": "ClassificationFailure", "Unit": "Count"},
                # {"Name": "AlertPublishFailure", "Unit": "Count"},
            ]
        }]
    },
    "sentiment": "negative",       # dimension value
    "SentimentCount": 1,           # metric value
    "PiiEntitiesDetected": 3,      # metric value
    # "ClassificationFailure": 1,  # only if classification_failed
    # "AlertPublishFailure": 1,    # only if sns.publish raised
}
print(json.dumps(emf_document))  # CloudWatch parses this from stdout
```

**Sample Code — testing EMF output with capsys:**

```python
def test_emf_includes_sentiment_count(capsys):
    # ... invoke handler ...
    captured = capsys.readouterr()
    emf = json.loads(captured.out.strip())
    assert emf["_aws"]["CloudWatchMetrics"][0]["Namespace"] == "ECHO"
    assert emf["sentiment"] == "negative"
    assert emf["SentimentCount"] == 1
```

**Sample Code — DEGRADE pattern (try/except on SNS):**

```python
alert_publish_failed = False
try:
    sns.publish(TopicArn=os.environ["ALERT_TOPIC_ARN"],
                Message=json.dumps(alert_body),
                MessageAttributes={"alert_type": {"DataType": "String", "StringValue": alert_type}})
except Exception:
    alert_publish_failed = True
    # Do NOT re-raise — persist already succeeded, avoid re-running Bedrock/Comprehend
```

> **Context digest:** `_alert_type` precedence: `urgent` > `needs_review` > `none`. SNS publish is wrapped in try/except — DEGRADE, not RAISE (avoids re-running Bedrock/Comprehend on redelivery). One EMF document per invocation via `print(json.dumps(...))` — namespace `ECHO`, dimension `sentiment`. `ClassificationFailure` and `AlertPublishFailure` are conditional metrics.

<details><summary><b>Background & design decisions</b></summary>

- **EMF (CloudWatch Embedded Metric Format)**: a structured JSON doc printed to stdout via `print(json.dumps(...))`. Contains `_aws.CloudWatchMetrics` block (Namespace, Dimensions, Metrics) plus top-level keys for values. CloudWatch Logs' EMF processor parses this into custom metrics — no `cloudwatch:PutMetricData` IAM needed.
- **`_alert_type` precedence**: `"urgent"` if `urgency == "high"`; else `"needs_review"` if `review_status == "needs_review"`; else `"none"`.
- **3 alert body shapes** (doc03 §7.1):
  - `urgent`: full context including `urgency_override_applied`
  - `needs_review`: similar minus override, plus `review_reason`
  - `none`: minimal — data-minimization
- **SNS publish**: `MessageAttributes={"alert_type": {"DataType": "String", "StringValue": alert_type}}`. Subscriber filter policies match the MessageAttribute.
- **DEGRADE on SNS failure** (doc03 §4.5): try/except around publish; on exception, set flag, don't re-raise.
- **EMF metrics**: `SentimentCount` (dimension=sentiment), `PiiEntitiesDetected` (always), `ClassificationFailure` (conditional), `AlertPublishFailure` (conditional) — all in one document.

</details>

<details><summary><b>Full test table + implementation</b></summary>

**Test** (`tests/lambda_triage/test_handler.py`, part 2)

| # | Test | Why it matters |
|---|------|----------------|
| 1 | `urgency="high"` → `alert_type="urgent"`, correct SNS MessageAttributes + §7.1 urgent body shape | DR1/DR4 alert |
| 2 | `urgency != "high"`, `review_status="needs_review"`, `category != "unclassified"` → `review_reason="low_confidence"` | DR5 alert |
| 3 | `classification_failed=True` → `review_reason="classification_failed"` | DR7 alert |
| 4 | `urgency != "high"`, `review_status="auto_processed"` → `alert_type="none"`, minimal body | Data-minimization |
| 5 | **Boundary**: `urgency="high"` AND `review_status="needs_review"` → `alert_type="urgent"` | Precedence |
| 6 | EMF includes `SentimentCount` with dimension = record sentiment | FR11/FR15 |
| 7 | `pii_entities_detected=0` → EMF still includes `PiiEntitiesDetected: 0` | Always-emit metric |
| 8 | `classification_failed=True` → EMF includes `ClassificationFailure` | DR7 metric |
| 9 | `sns.publish` raises → no re-raise; EMF includes `AlertPublishFailure` | DEGRADE |

Helper: `capsys`-based assertion reads the single `print()`'d EMF JSON line.

**Implementation**

`_alert_type(record) -> str`: urgent > needs_review > none.

`_build_alert_body(record, alert_type) -> dict`:
- Common: `email_id`, `alert_type`, `received_at`.
- `urgent`: + `from_address`, `subject`, `category`, `urgency`, `urgency_override_applied`, `sentiment`, `confidence`, `suggested_reply`.
- `needs_review`: + same minus `urgency_override_applied`, plus `review_reason`.
- `none`: + only `category`, `urgency`, `sentiment`, `confidence`.

`_emit_emf(record, classification_failed, alert_publish_failed) -> None`:
- Build EMF doc with `Namespace: "ECHO"`, `Dimensions: [["sentiment"]]`.
- Keys: `sentiment`, `SentimentCount=1`, `PiiEntitiesDetected=record[...]`, conditionally `ClassificationFailure=1`, `AlertPublishFailure=1`.
- `print(json.dumps(emf_doc))`.

`handler()` steps 9-12 (after 4.5's step 8):
9. `alert_type = _alert_type(record)`.
10. `alert_body = _build_alert_body(record, alert_type)`.
11. `try: sns.publish(...)` — `except Exception: alert_publish_failed = True`.
12. `_emit_emf(record, classification["classification_failed"], alert_publish_failed)`.

</details>

---

## Phase 5 — Lambda #3 — Insights

Per doc03 §5.2, Lambda#3 has 3 files: `handler.py`, `query.py`, `synthesize.py`. Three stories in dependency order.

**Design change (2026-06-24):** Synthesize now uses **Bedrock tool use** instead of receiving pre-loaded records. The model decides what to query based on the user's natural-language question, calls a `query_triage_data` tool, and synthesizes an answer from the results. This enables filtered lookups ("show me negative billing emails"), record-level analysis ("what are customers saying about outages"), and multi-step comparisons ("compare billing vs bug report sentiment").

---

### 5.1 `query.py`

**Goal:** DynamoDB Scan with filter (`review_status="auto_processed"`) and projection, with pagination loop. Two functions: the original 5-field full scan (`get_auto_processed_records`) and a new parameterized 9-field query (`query_triage_data`) used by Bedrock tool use.

**Prereqs:** 2.1 (`GENERAL_CONFIG`). moto fully supports DynamoDB Scan. Module-level `table` requires `importlib.reload(query)` inside `mock_aws()`.

**Signatures (build these):**

```
src/lambda_insights/query.py

import os, boto3
from boto3.dynamodb.conditions import Attr
from retry_config import GENERAL_CONFIG

dynamodb = boto3.resource("dynamodb", config=GENERAL_CONFIG)
table = dynamodb.Table(os.environ["DYNAMODB_TABLE_NAME"])

def get_auto_processed_records() -> list[dict]: ...  # existing — 5 projected fields

def query_triage_data(
    *,
    category: str | None = None,
    sentiment: str | None = None,
    urgency: str | None = None,
    from_address: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict]: ...  # new — 9 projected fields, parameterized filters
```

**TDD Order (Red → Green):**

*Existing `get_auto_processed_records` (tests 1–5) — already DONE.*

*New `query_triage_data` (tests 6–15):*
1. test #6 (no filters → all auto_processed) → build basic `query_triage_data` with base filter
2. test #7 (category filter) → add category `Attr` chaining
3. test #8 (sentiment + category) → add multi-filter AND
4. test #9 (from_address filter) → add from_address filter
5. test #12 (9 projected fields) → set expanded ProjectionExpression
6. test #10 + #11 (date range filters) → add date_from/date_to with `gte`/`lte`
7. test #13 (needs_review excluded) → should pass already (base filter)
8. test #14 (no matches → `[]`) → should pass already
9. test #15 (pagination) → reuse `LastEvaluatedKey` loop pattern

**External Docs:**
- [DynamoDB Scan](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Scan.html)
- [boto3 DynamoDB conditions](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/customizations/dynamodb.html#ref-valid-dynamodb-conditions)
- [Table.scan](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/dynamodb/table/scan.html)
- [DynamoDB Scan pagination](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Scan.html#Scan.Pagination)
- [DynamoDB reserved words](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/ReservedWords.html)

**Input/Output Shapes:**

```python
# ─── get_auto_processed_records (existing, unchanged) ───

# INPUT — none (function takes no arguments)
# OUTPUT — list of dicts, each with EXACTLY these 5 projected fields:
[
    {"category": "billing", "urgency": "high", "sentiment": "negative",
     "feature_tags": [], "received_at": "2026-06-21T10:00:00+00:00"},
]

# ─── query_triage_data (new — used by Bedrock tool use) ───

# INPUT — all keyword-only, all optional:
query_triage_data()                                    # no filters — all auto_processed
query_triage_data(category="billing")                  # single filter
query_triage_data(sentiment="negative", urgency="high") # multiple filters AND'd
query_triage_data(from_address="jane@example.com")     # exact sender match
query_triage_data(date_from="2026-06-20T00:00:00+00:00")  # on/after date
query_triage_data(date_from="2026-06-20T00:00:00+00:00",
                  date_to="2026-06-21T23:59:59+00:00") # date window

# OUTPUT — list of dicts, each with EXACTLY these 9 projected fields:
[
    {
        "email_id": "msg-001",
        "from_address": "jane@example.com",
        "subject": "Charged twice for June",
        "redacted_body": "Hi, my name is [NAME]. I was charged twice...",
        "category": "billing",
        "urgency": "high",
        "sentiment": "negative",
        "feature_tags": [],
        "received_at": "2026-06-21T10:00:00+00:00"
    },
]

# OUTPUT — no matching records:
[]
```

**Sample Code — parameterized scan with Attr AND chaining:**

```python
def query_triage_data(*, category=None, sentiment=None, urgency=None,
                      from_address=None, date_from=None, date_to=None) -> list[dict]:
    filter_expr = Attr("review_status").eq("auto_processed")
    if category is not None:
        filter_expr = filter_expr & Attr("category").eq(category)
    if sentiment is not None:
        filter_expr = filter_expr & Attr("sentiment").eq(sentiment)
    if urgency is not None:
        filter_expr = filter_expr & Attr("urgency").eq(urgency)
    if from_address is not None:
        filter_expr = filter_expr & Attr("from_address").eq(from_address)
    if date_from is not None:
        filter_expr = filter_expr & Attr("received_at").gte(date_from)
    if date_to is not None:
        filter_expr = filter_expr & Attr("received_at").lte(date_to)

    records = []
    scan_kwargs = {
        "FilterExpression": filter_expr,
        "ProjectionExpression": "email_id, from_address, subject, redacted_body, "
                                "category, urgency, sentiment, feature_tags, received_at",
    }
    while True:
        response = table.scan(**scan_kwargs)
        records.extend(response["Items"])
        if "LastEvaluatedKey" not in response:
            break
        scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
    return records
```

> **Context digest:** `query_triage_data` is the tool Bedrock calls — parameterized filters layered with `&` (AND) on top of the `review_status="auto_processed"` base filter. Projects 9 fields (existing 5 + `email_id`, `from_address`, `subject`, `redacted_body`). Date filtering works because ISO 8601 strings are lexicographically ordered. `get_auto_processed_records` (5-field, no params) stays for backward compatibility.

<details><summary><b>Background & design decisions</b></summary>

- `table.scan(FilterExpression=..., ProjectionExpression=...)` — DynamoDB `Scan` reads the entire table and applies filter server-side. Fine at demo scale; would need a GSI at production scale.
- **Two functions**: `get_auto_processed_records()` (original, 5 fields, no params) kept for backward compat. `query_triage_data()` (new, 9 fields, parameterized) used by Bedrock tool use.
- **`Attr` AND chaining**: `filter_expr & Attr("category").eq(...)` — boto3 `Attr` objects support `&` for AND conditions. Each optional param adds a condition.
- **Date range**: ISO 8601 strings are lexicographically ordered, so `Attr("received_at").gte(date_from)` works as a date comparison. No need to parse to epoch.
- **Expanded projection**: adds `email_id`, `from_address`, `subject`, `redacted_body` so Bedrock can identify, attribute, and summarize specific emails.
- None of the 9 field names are DynamoDB reserved words, so no `ExpressionAttributeNames` needed.
- **Pagination**: `scan()` returns at most 1MB per call. Loop on `LastEvaluatedKey`.
- moto fully supports Scan with FilterExpression and ProjectionExpression.

</details>

<details><summary><b>Full test table + implementation</b></summary>

**Test** (`tests/lambda_insights/test_query.py`)

*Existing tests (1–5) — unchanged, cover `get_auto_processed_records`:*

| # | Test | Why it matters |
|---|------|----------------|
| 1 | Mix of `auto_processed` and `needs_review` items → only auto_processed returned | Core filter |
| 2 | Returned items contain **only** 5 projected fields | Data-minimization |
| 3 | Empty table → returns `[]` | Boundary |
| 4 | `feature_tags` list round-trips correctly through projection | FR6 into /insights |
| 5 | **Boundary**: mocked pagination (2 pages) → both pages concatenated | Pins pagination loop |

*New tests (6–15) — cover `query_triage_data`:*

| # | Test | Why it matters |
|---|------|----------------|
| 6 | No filters → returns all auto_processed records | Baseline — same records as `get_auto_processed_records` but with 9 fields |
| 7 | `category="billing"` → only billing records returned | Single filter correctness |
| 8 | `sentiment="negative"` + `category="billing"` → intersection only | Multiple filters AND correctly |
| 9 | `from_address="jane@example.com"` → only that sender | from_address filter |
| 10 | `date_from="2026-06-21T00:00:00+00:00"` → records on/after that date | Date lower bound |
| 11 | `date_from` + `date_to` → records within window only | Date range |
| 12 | Returned records have exactly 9 projected fields | Expanded projection |
| 13 | `needs_review` records excluded even when other filters match | Base filter always applies |
| 14 | No matching records → `[]` | Empty result |
| 15 | **Boundary**: mocked pagination (2 pages) → both pages concatenated | Pagination works with parameterized query |

**Implementation**

`get_auto_processed_records() -> list[dict]` — unchanged (see existing code).

`query_triage_data(*, category, sentiment, urgency, from_address, date_from, date_to) -> list[dict]`

1. Build `filter_expr = Attr("review_status").eq("auto_processed")`.
2. For each non-`None` param, chain with `& Attr("<field>").eq(<value>)` (or `.gte`/`.lte` for dates).
3. `scan_kwargs = {"FilterExpression": filter_expr, "ProjectionExpression": "email_id, from_address, subject, redacted_body, category, urgency, sentiment, feature_tags, received_at"}`.
4. Pagination loop: `table.scan(**scan_kwargs)`, extend `records`, check `LastEvaluatedKey`.
5. Return `records`.

</details>

---

### 5.2 `synthesize.py`

**Goal:** Multi-turn Bedrock tool use loop — model decides what to query based on the user's question, calls a `query_triage_data` tool (fulfilled by `query.py`), and synthesizes a natural-language answer from the results. Layer 2 retry on invalid final answer. Tightened Bedrock config.

**Prereqs:** 5.1 (`query_triage_data`). moto does NOT support `bedrock-runtime` — use `patch.object(synthesize.bedrock, "invoke_model", ...)`. `query_fn` is injected as a callable, so tests pass a mock instead of needing DynamoDB.

**Signatures (build these):**

```
src/lambda_insights/synthesize.py

import json, boto3
from botocore.config import Config

INSIGHTS_BEDROCK_CONFIG = Config(retries={"max_attempts": 2, "mode": "adaptive"},
                                 connect_timeout=3, read_timeout=5)
bedrock = boto3.client("bedrock-runtime", config=INSIGHTS_BEDROCK_CONFIG)
MODEL_ID = "anthropic.claude-3-haiku-20240307-v1:0"

QUERY_TOOL = {
    "name": "query_triage_data",
    "description": "Query the email triage database. Returns records matching filters. "
                   "All filters optional. Call multiple times with different filters to compare.",
    "input_schema": {
        "type": "object",
        "properties": {
            "category": {"type": "string", "enum": ["bug_report", "feature_request",
                         "general_inquiry", "billing", "complaint", "praise"]},
            "sentiment": {"type": "string", "enum": ["positive", "negative", "constructive"]},
            "urgency": {"type": "string", "enum": ["high", "medium", "low"]},
            "from_address": {"type": "string", "description": "Filter by sender (exact match)"},
            "date_from": {"type": "string", "description": "ISO 8601 — records on/after this date"},
            "date_to": {"type": "string", "description": "ISO 8601 — records on/before this date"},
        },
        "required": [],
    },
}
MAX_TOOL_TURNS = 3  # cap on tool call rounds to prevent runaway

SYSTEM_PROMPT = "..."   # instructs model to use query_triage_data tool
RETRY_SYSTEM_PROMPT = "..."  # corrective prompt for Layer 2 retry

def _invoke_with_tools(question: str, system_prompt: str, query_fn: callable) -> tuple[str | None, int]: ...
def _try_parse(raw_text: str) -> dict | None: ...
def _extract_tool_calls(content: list[dict]) -> list[dict]: ...
def _extract_text(content: list[dict]) -> str | None: ...
def synthesize(question: str, query_fn: callable) -> dict: ...
```

**TDD Order (Red → Green):**
1. test #1 (single tool call happy path) → build `_invoke_with_tools` + `_try_parse` + `synthesize` skeleton
2. test #8 (query_fn called with exact kwargs) → wire tool input → `query_fn(**input)` passthrough
3. test #3 (no tool use — direct answer) → add `stop_reason == "end_turn"` path
4. test #2 (two tool calls for comparison) → handle multiple rounds
5. test #4 (invalid answer → retry) → wire Layer 2 retry with `RETRY_SYSTEM_PROMPT`
6. test #5 (both fail → degraded) → add failure return path
7. test #6 (MAX_TOOL_TURNS exceeded) → add loop counter check
8. test #7 (records_considered accumulates) → track counter across calls
9. test #9 + #10 (request shape + message threading) → contract verification
10. test #11 + #12 (config + params) → regression boundaries

**External Docs:**
- [Bedrock InvokeModel API](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_InvokeModel.html)
- [Anthropic Messages format on Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/model-parameters-anthropic-claude-messages.html)
- [Anthropic tool use on Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/tool-use.html)
- [botocore Config reference](https://botocore.amazonaws.com/v1/documentation/api/latest/reference/config.html)

**Input/Output Shapes:**

```python
# INPUT — question: the user's natural-language question:
question = "Show me the negative sentiment billing emails"

# INPUT — query_fn: a callable matching query.query_triage_data's signature
#   injected by handler as query.query_triage_data
#   in tests, a unittest.mock.Mock returning canned records

# OUTPUT — synthesize() on SUCCESS:
{
    "answer": "There are 3 negative billing emails this week...",
    "records_considered": 3,        # total records across all tool calls
    "synthesis_failed": False
}

# OUTPUT — synthesize() on FAILURE (both attempts failed):
{
    "answer": None,
    "records_considered": 0,
    "synthesis_failed": True        # handler turns this into HTTP 503
}

# ─── BEDROCK TOOL USE RESPONSE SHAPES ───

# When model wants to call a tool (stop_reason="tool_use"):
{
    "content": [
        {"type": "text", "text": "I'll query for negative billing emails."},   # optional reasoning
        {"type": "tool_use", "id": "toolu_001", "name": "query_triage_data",
         "input": {"sentiment": "negative", "category": "billing"}}
    ],
    "stop_reason": "tool_use"
}

# When model gives final answer (stop_reason="end_turn"):
{
    "content": [
        {"type": "text", "text": "{\"answer\": \"There are 3 negative billing emails...\"}"}
    ],
    "stop_reason": "end_turn"
}

# Tool result sent back to model (appended to messages):
{"role": "user", "content": [
    {"type": "tool_result", "tool_use_id": "toolu_001",
     "content": "[{\"email_id\": \"msg-001\", \"category\": \"billing\", ...}]"}
]}

# ─── MULTI-TURN MESSAGE SEQUENCE (full conversation) ───

messages = [
    # Turn 1: user asks question
    {"role": "user", "content": "Show me negative billing emails"},
    # Turn 2: model requests tool use
    {"role": "assistant", "content": [
        {"type": "tool_use", "id": "toolu_001", "name": "query_triage_data",
         "input": {"sentiment": "negative", "category": "billing"}}
    ]},
    # Turn 3: we send tool results back
    {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "toolu_001",
         "content": json.dumps(records)}
    ]},
    # Turn 4: model gives final answer (via invoke_model response, not in messages)
]

# ─── INTERNAL HELPER SHAPES ───

# _invoke_with_tools(question, system_prompt, query_fn) -> (str | None, int)
# Returns (raw_final_text, records_considered) or (None, 0) on failure/timeout

# _try_parse(raw_text) -> dict | None
# Same as original: json.loads + validate "answer" key is str

# _extract_tool_calls(content) -> list[dict]
# Filters content blocks to type=="tool_use"

# _extract_text(content) -> str | None
# Finds first block with type=="text", returns its text value
```

**Sample Code — invoke_model with tools (Anthropic Messages format on Bedrock):**

```python
response = bedrock.invoke_model(
    modelId=MODEL_ID,
    contentType="application/json",
    accept="application/json",
    body=json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1024,
        "temperature": 0.3,
        "system": system_prompt,
        "tools": [QUERY_TOOL],
        "messages": messages,
    })
)
response_body = json.loads(response["body"].read())
# response_body has "content" (list of blocks) and "stop_reason"
```

**Sample Code — handling tool_use response + sending tool_result:**

```python
# After receiving a tool_use response:
tool_calls = [b for b in response_body["content"] if b["type"] == "tool_use"]
for tc in tool_calls:
    records = query_fn(**tc["input"])
    records_considered += len(records)

# Append assistant response + tool results to messages:
messages.append({"role": "assistant", "content": response_body["content"]})
messages.append({"role": "user", "content": [
    {"type": "tool_result", "tool_use_id": tc["id"], "content": json.dumps(records)}
    for tc in tool_calls
]})

# Then call invoke_model again with updated messages
```

**Sample Code — test mock helpers:**

```python
def mock_tool_use_response(tool_calls: list[dict]) -> dict:
    content = [{"type": "tool_use", "id": tc.get("id", "toolu_001"),
                "name": tc["name"], "input": tc["input"]} for tc in tool_calls]
    envelope = json.dumps({"content": content, "stop_reason": "tool_use"}).encode()
    return {"body": io.BytesIO(envelope)}

def mock_final_response(text: str) -> dict:
    envelope = json.dumps({"content": [{"type": "text", "text": text}],
                           "stop_reason": "end_turn"}).encode()
    return {"body": io.BytesIO(envelope)}
```

**Sample Code — test pattern (single tool call happy path):**

```python
def test_single_tool_call_happy_path():
    tool_resp = mock_tool_use_response([{
        "name": "query_triage_data", "input": {"sentiment": "negative"}, "id": "toolu_001"}])
    final_resp = mock_final_response(json.dumps({"answer": "3 negative emails found."}))
    mock_query = Mock(return_value=[{"email_id": "msg-001", "category": "billing", ...}])

    with patch.object(synthesize.bedrock, "invoke_model", side_effect=[tool_resp, final_resp]):
        result = synthesize.synthesize("Show me negative emails", mock_query)

    assert result["answer"] == "3 negative emails found."
    assert result["records_considered"] == 1
    assert result["synthesis_failed"] is False
    mock_query.assert_called_once_with(sentiment="negative")
```

**Sample Code — differences from 4.3's classify.py (side-by-side):**

```python
# classify.py (4.3):                    # synthesize.py (5.2):
# BEDROCK_CONFIG (from layer)           # INSIGHTS_BEDROCK_CONFIG (local)
#   max_attempts=3, read_timeout=10     #   max_attempts=2, read_timeout=5
# temperature=0.0                       # temperature=0.3
# max_tokens=512 / 768 (retry)         # max_tokens=1024 (tool use JSON is verbose)
# Single invoke → parse                # Multi-turn tool use loop
# Response: 6-field schema              # Response: {"answer": "<string>"}
# Returns: {..., classification_failed} # Returns: {answer, records_considered, synthesis_failed}
```

> **Context digest:** Uses Bedrock **tool use** — model receives a `query_triage_data` tool definition, decides what to query, calls the tool (possibly multiple times), then synthesizes an answer. `query_fn` is injected by handler (dependency injection for testability). Multi-turn message list builds up: user → assistant(tool_use) → user(tool_result) → ... → assistant(end_turn). `MAX_TOOL_TURNS=3` caps the loop. Layer 2 retry restarts the entire conversation if final answer is invalid. `records_considered` accumulates across all tool calls.

<details><summary><b>Background & design decisions</b></summary>

- **Bedrock tool use** on Anthropic Messages format: include `"tools": [...]` in the request body. Model can respond with `stop_reason: "tool_use"` and `content` blocks of type `"tool_use"`. We execute the tool, send back `"tool_result"` blocks, and the model continues.
- **Dependency injection**: `query_fn` parameter instead of importing `query` directly. Handler passes `query.query_triage_data`. Tests pass a `Mock`. Avoids circular imports and complex DynamoDB mocking in synthesize tests.
- **`INSIGHTS_BEDROCK_CONFIG`** (doc03 §7.3): `max_attempts=2`, `connect_timeout=3`, `read_timeout=5`. Defined locally, NOT imported from `retry_config.py`.
- `temperature=0.3` (synthesis produces prose), `max_tokens=1024` (tool use JSON is verbose).
- **Response schema** for final answer: just `{"answer": "<string>"}`. `records_considered` is tracked by the loop, not the model.
- **MAX_TOOL_TURNS=3**: prevents runaway tool call loops. Most real queries need 1-2 tool calls.
- **Layer 2 retry**: if final answer isn't valid `{"answer": "..."}` JSON, restart entire conversation with `RETRY_SYSTEM_PROMPT`. This is simpler than resuming mid-conversation.
- **Multiple tool calls in one response**: Bedrock can return multiple `tool_use` blocks. Handle all of them, send all `tool_result` blocks back in one message.
- moto doesn't support bedrock-runtime — `patch.object(synthesize.bedrock, "invoke_model", side_effect=[...])` with a sequence of mock responses.

</details>

<details><summary><b>Full test table + implementation</b></summary>

**Test** (`tests/lambda_insights/test_synthesize.py`)

| # | Test | Why it matters |
|---|------|----------------|
| 1 | Single tool call: model requests `query_triage_data(sentiment="negative")`, gets results, returns valid `{"answer": "..."}` | Happy path — one tool call, one answer |
| 2 | Two sequential tool calls (e.g., billing then bug_report), then valid answer | Multi-tool-call path |
| 3 | Model returns answer directly without tool use (`stop_reason="end_turn"` on first response) | No-tool-call path still works |
| 4 | Final answer is invalid JSON on attempt 1, valid on attempt 2 (Layer 2 retry) | Retry mechanism |
| 5 | Both attempts fail → `{"answer": None, "records_considered": 0, "synthesis_failed": True}` | DR8 fallback |
| 6 | Tool use loop exceeds `MAX_TOOL_TURNS` → treated as failure, triggers retry | Runaway protection |
| 7 | `records_considered` accumulates across multiple tool calls | Counter correctness |
| 8 | `query_fn` called with exact kwargs from tool input | Tool input passthrough |
| 9 | `invoke_model` request body includes `"tools"` key with `QUERY_TOOL` | Contract verification |
| 10 | Messages list correctly builds multi-turn conversation (user → assistant(tool_use) → user(tool_result) → assistant(end_turn)) | Message threading |
| 11 | **Boundary**: `INSIGHTS_BEDROCK_CONFIG` is different object from `BEDROCK_CONFIG` with `max_attempts=2`, `read_timeout=5` | Regression |
| 12 | `temperature=0.3` and `max_tokens=1024` in invoke request | Parameter verification |

Helpers: `mock_tool_use_response(tool_calls)` and `mock_final_response(text)` — two separate helpers for the two response shapes. `query_fn` is a `unittest.mock.Mock` returning canned records.

**Implementation**

`_extract_tool_calls(content: list[dict]) -> list[dict]`
- Filter blocks to `type == "tool_use"`. Return list.

`_extract_text(content: list[dict]) -> str | None`
- Find first block with `type == "text"`. Return its `"text"` value, or `None`.

`_try_parse(raw_text: str) -> dict | None`
1. `json.loads`, catch error → `None`.
2. Valid only if `"answer"` exists and is a `str`.
3. Return `{"answer": parsed["answer"]}` if valid, else `None`.

`_invoke_with_tools(question, system_prompt, query_fn) -> tuple[str | None, int]`
1. `messages = [{"role": "user", "content": question}]`.
2. `records_considered = 0`.
3. Loop up to `MAX_TOOL_TURNS`:
   a. `invoke_model(...)` with `tools=[QUERY_TOOL]`, `messages`, `temperature=0.3`, `max_tokens=1024`.
   b. `response_body = json.loads(response["body"].read())`.
   c. If `stop_reason == "end_turn"`: return `(_extract_text(content), records_considered)`.
   d. If `stop_reason == "tool_use"`: extract tool calls, execute each via `query_fn(**input)`, accumulate `records_considered`, append assistant + tool_result messages, continue loop.
4. Loop exhausted: return `(None, 0)`.

`synthesize(question, query_fn) -> dict`
1. Attempt 1: `_invoke_with_tools(question, SYSTEM_PROMPT, query_fn)` → `_try_parse(text)`.
2. If valid: `{"answer": ..., "records_considered": N, "synthesis_failed": False}`.
3. Attempt 2: `_invoke_with_tools(question, RETRY_SYSTEM_PROMPT, query_fn)` → `_try_parse(text)`.
4. If valid: same.
5. Both failed: `{"answer": None, "records_considered": 0, "synthesis_failed": True}`.

</details>

---

### 5.3 `handler.py`

**Goal:** API Gateway Lambda proxy handler — parse request, pass question + query function to synthesize, return 200 or 503 with correct response shape.

**Prereqs:** 5.2 green. **Simplified mocking:** handler delegates everything to `synthesize.synthesize()`, so tests only need to `patch.object(synthesize, "synthesize", ...)` — no DynamoDB or Bedrock mocking needed in handler tests.

**Signatures (build these):**

```
src/lambda_insights/handler.py

import json, time
import query, synthesize

def _emit_synthesis_failure_emf() -> None: ...
def handler(event, context): ...
```

**TDD Order (Red → Green):**
1. test #1 (happy path → 200 + correct body) → build handler skeleton
2. test #3 + #4 (API Gateway proxy shape: string body, correct return keys) → add `json.loads(event["body"])` + response shaping
3. test #5 (records_considered=0 on success → 200) → should pass already
4. test #2 (synthesis_failed → 503 + EMF) → add failure branch + `_emit_synthesis_failure_emf`
5. test #6 (no EMF on 200 path) → should pass already
6. test #7 (`query.query_triage_data` passed as query_fn) → verify wiring

**External Docs:**
- [API Gateway Lambda proxy integration](https://docs.aws.amazon.com/apigateway/latest/developerguide/set-up-lambda-proxy-integrations.html)
- [Lambda proxy response format](https://docs.aws.amazon.com/apigateway/latest/developerguide/set-up-lambda-proxy-integrations.html#api-gateway-simple-proxy-for-lambda-output-format)
- [API Gateway proxy event format](https://docs.aws.amazon.com/apigateway/latest/developerguide/set-up-lambda-proxy-integrations.html#api-gateway-simple-proxy-for-lambda-input-format)
- [HTTP status codes — 502 vs 503](https://developer.mozilla.org/en-US/docs/Web/HTTP/Status)

**Input/Output Shapes:**

```python
# INPUT — event (API Gateway Lambda proxy format):
event = {
    "body": '{"question": "What are the most common feature requests?"}',
    "httpMethod": "POST",
    "path": "/insights",
    "headers": {"Content-Type": "application/json"},
    # ... other API Gateway fields (not used by this handler)
}
# IMPORTANT: event["body"] is a STRING, not a dict!
request_body = json.loads(event["body"])
question = request_body["question"]

# HANDLER CALLS synthesize with query_fn (dependency injection):
result = synthesize.synthesize(question, query.query_triage_data)
# result = {"answer": "...", "records_considered": N, "synthesis_failed": False}

# OUTPUT — 200 response (synthesis succeeded):
{
    "statusCode": 200,
    "body": '{"answer": "The most common feature requests are dark-mode...", "records_considered": 12}',
    "headers": {"Content-Type": "application/json"}
}
# body decoded: {"answer": str, "records_considered": int}

# OUTPUT — 200 response (no data yet, records_considered=0):
{
    "statusCode": 200,
    "body": '{"answer": "No triage data is available yet.", "records_considered": 0}',
    "headers": {"Content-Type": "application/json"}
}

# OUTPUT — 503 response (synthesis failed after retries):
{
    "statusCode": 503,
    "body": '{"error": "synthesis_unavailable", "records_considered": 0}',
    "headers": {"Content-Type": "application/json"}
}

# OUTPUT — 502 (DynamoDB Scan raises inside synthesize → uncaught → API Gateway generic 502):
# NOT generated by this handler — it's what API Gateway returns when Lambda raises

# ─── INTERNAL HELPER SHAPES ───

# _emit_synthesis_failure_emf() -> None
# INPUT: none (takes no arguments)
# OUTPUT: prints ONE JSON line to stdout (only on the 503 path):
'{"_aws":{"Timestamp":...,"CloudWatchMetrics":[{"Namespace":"ECHO","Dimensions":[[]],"Metrics":[{"Name":"SynthesisFailure","Unit":"Count"}]}]},"SynthesisFailure":1}'
# Note: Dimensions is [[]] — no dimensions, unlike 4.6's [["sentiment"]]
```

**Sample Code — simplified handler (no direct query call):**

```python
def handler(event, context):
    request_body = json.loads(event["body"])
    question = request_body["question"]

    # Bedrock drives the queries via tool use — handler just passes the function
    result = synthesize.synthesize(question, query.query_triage_data)

    if not result["synthesis_failed"]:
        return {
            "statusCode": 200,
            "body": json.dumps({
                "answer": result["answer"],
                "records_considered": result["records_considered"],
            }),
            "headers": {"Content-Type": "application/json"},
        }
    else:
        _emit_synthesis_failure_emf()
        return {
            "statusCode": 503,
            "body": json.dumps({
                "error": "synthesis_unavailable",
                "records_considered": result["records_considered"],
            }),
            "headers": {"Content-Type": "application/json"},
        }
```

**Sample Code — SynthesisFailure EMF (no dimensions):**

```python
emf_document = {
    "_aws": {
        "Timestamp": int(time.time() * 1000),
        "CloudWatchMetrics": [{
            "Namespace": "ECHO",
            "Dimensions": [[]],  # empty — no dimensions for this metric
            "Metrics": [{"Name": "SynthesisFailure", "Unit": "Count"}]
        }]
    },
    "SynthesisFailure": 1
}
print(json.dumps(emf_document))
```

**Sample Code — test pattern (mock synthesize, not Bedrock):**

```python
from unittest.mock import patch
import synthesize, query

def test_happy_path():
    event = {"body": json.dumps({"question": "What are the trends?"})}
    with patch.object(synthesize, "synthesize", return_value={
        "answer": "Billing is the top category.",
        "records_considered": 5,
        "synthesis_failed": False,
    }) as mock_synth:
        result = handler.handler(event, None)
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["answer"] == "Billing is the top category."
        assert body["records_considered"] == 5
        # Verify query_fn wiring:
        mock_synth.assert_called_once_with("What are the trends?", query.query_triage_data)
```

> **Context digest:** Handler is simplified compared to original design — no longer calls `query` directly. Passes `query.query_triage_data` as a callable to `synthesize.synthesize()`. `records_considered` comes from synthesize's return value. Response shapes unchanged (200/503). DynamoDB errors propagate through synthesize uncaught → API Gateway 502. Tests only mock `synthesize.synthesize` — no DynamoDB or Bedrock mocking needed.

<details><summary><b>Background & design decisions</b></summary>

- **API Gateway Lambda proxy integration** (`AWS_PROXY`): `event["body"]` is a JSON string. Return value must be `{"statusCode": int, "body": <JSON string>, "headers": {...}}`.
- **Simplified orchestration**: handler passes `query.query_triage_data` as `query_fn` to `synthesize.synthesize()`. Bedrock drives the queries via tool use inside synthesize.
- **503 is not a catch-all** — specifically the outcome when `synthesis_failed=True`. DynamoDB Scan failure RAISEs through synthesize (→ API Gateway 502).
- No idempotency guard — synchronous, read-only request.
- `SynthesisFailure` EMF metric on 503 path only — no dimensions.
- **Testing is simpler than the original design**: only `patch.object(synthesize, "synthesize", ...)` needed. No `@mock_aws`, no Bedrock mocking. Handler tests verify orchestration wiring and response shaping.

</details>

<details><summary><b>Full test table + implementation</b></summary>

**Test** (`tests/lambda_insights/test_handler.py`)

| # | Test | Why it matters |
|---|------|----------------|
| 1 | Happy path → `statusCode=200`, body = `{"answer": "...", "records_considered": N}` | Core contract |
| 2 | `synthesis_failed=True` → `statusCode=503`, body = `{"error": "synthesis_unavailable", "records_considered": N}` + EMF | DR8 |
| 3 | `event["body"]` is a JSON string → handler json.loads it | Proxy integration shape |
| 4 | Response has exactly `statusCode`, `body` (str), `headers` | Return contract |
| 5 | `records_considered=0` on success → 200 (not failure) | "No data" ≠ "failed" |
| 6 | On 200 path, no `SynthesisFailure` EMF line printed | Conditional metric |
| 7 | `query.query_triage_data` is passed as the `query_fn` argument to `synthesize.synthesize` | Wiring check |

**Implementation**

`_emit_synthesis_failure_emf() -> None`
- EMF doc: `Namespace: "ECHO"`, no dimensions, `SynthesisFailure=1`.
- `print(json.dumps(emf_doc))`.

`handler(event, context)`
1. `request_body = json.loads(event["body"])`.
2. `question = request_body["question"]`.
3. `result = synthesize.synthesize(question, query.query_triage_data)`.
4. If not `synthesis_failed`: return 200 + `{"answer": result["answer"], "records_considered": result["records_considered"]}`.
5. Else: `_emit_synthesis_failure_emf()`, return 503 + `{"error": "synthesis_unavailable", "records_considered": result["records_considered"]}`.

</details>

---

## Phase 6 — Terraform Modules (12)

Built in doc04 §1.3's dependency order. Each module's resources are specified in doc04 — this phase adds build-order quirks, `checkov` expectations, and design questions.

**TDD-equivalent for Terraform:**
- **Red** = `terraform validate` fails or `checkov` flags an unaddressed finding
- **Green** = validate passes, plan shows expected resources, checkov passes/has documented suppressions
- **Refactor** = simplify without changing plan output

No `terraform apply` in Phase 6 — that's Phase 7.

**External Docs (all of Phase 6):**
- [Terraform AWS Provider docs](https://registry.terraform.io/providers/hashicorp/aws/latest/docs)
- [checkov AWS checks](https://www.checkov.io/5.Policy%20Index/terraform.html)
- [Terraform backend S3](https://developer.hashicorp.com/terraform/language/backend/s3)
- [Terraform `jsonencode` function](https://developer.hashicorp.com/terraform/language/functions/jsonencode)
- [Terraform `for_each` meta-argument](https://developer.hashicorp.com/terraform/language/meta-arguments/for_each)
- [Terraform `data` sources](https://developer.hashicorp.com/terraform/language/data-sources)
- [Terraform `depends_on`](https://developer.hashicorp.com/terraform/language/meta-arguments/depends_on)
- [checkov inline suppressions](https://www.checkov.io/2.Basics/Suppressing%20and%20Skipping%20Policies.html)

**Sample Code — checkov suppression pattern:**

```hcl
resource "aws_s3_bucket" "raw_emails" {
  bucket = "echo-raw-emails-${var.env}"
  #checkov:skip=CKV_AWS_18: No access logging — demo-scale cost tradeoff, doc03 §8.1
  #checkov:skip=CKV_AWS_21: Versioning intentionally disabled, doc03 §8.1
}
```

**Sample Code — data source for account ID:**

```hcl
data "aws_caller_identity" "current" {}

# Usage:
resource "aws_s3_bucket_policy" "raw_emails" {
  bucket = aws_s3_bucket.raw_emails.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ses.amazonaws.com" }
      Action    = "s3:PutObject"
      Resource  = "${aws_s3_bucket.raw_emails.arn}/*"
      Condition = {
        StringEquals = { "aws:SourceAccount" = data.aws_caller_identity.current.account_id }
      }
    }]
  })
}
```

**Sample Code — module structure (3-file convention):**

```hcl
# modules/s3/variables.tf
variable "env" { type = string }
variable "region" { type = string }

# modules/s3/outputs.tf
output "bucket_id"   { value = aws_s3_bucket.raw_emails.id }
output "bucket_arn"  { value = aws_s3_bucket.raw_emails.arn }
output "bucket_name" { value = aws_s3_bucket.raw_emails.bucket }

# modules/s3/main.tf
# (all resources live here)
```

---

### 6.1 `s3`

**Goal:** Create the `raw-emails` S3 bucket with SSE-S3, public access block, 90-day lifecycle, and SES PutObject bucket policy.

**Prereqs:** None — dependency root.

**What to build:** `aws_s3_bucket` + `_server_side_encryption_configuration` (AES256) + `_public_access_block` (all 4 on) + `_versioning` (disabled) + `_lifecycle_configuration` (90-day expiration) + `_policy` (SES PutObject, `aws:SourceAccount` condition).

**Inputs → Outputs:** `variables.tf` = `env`, `region`. `outputs.tf` = `bucket_id`, `bucket_arn`, `bucket_name`.

**Validation:**
- Suppress `CKV_AWS_18` (access logging) and `CKV_AWS_21` (versioning) — deliberate doc03 §8.1 decisions.
- First use of `data "aws_caller_identity" "current"` for account ID in the bucket policy.

**External Docs:**
- [aws_s3_bucket](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket)
- [aws_s3_bucket_server_side_encryption_configuration](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_server_side_encryption_configuration)
- [aws_s3_bucket_public_access_block](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_public_access_block)
- [aws_s3_bucket_lifecycle_configuration](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_lifecycle_configuration)
- [SES receiving email setup](https://docs.aws.amazon.com/ses/latest/dg/receiving-email-setting-up.html)

**Sample Code:**

```hcl
resource "aws_s3_bucket" "raw_emails" {
  bucket = "echo-raw-emails-${var.env}"
  #checkov:skip=CKV_AWS_18: No access logging — demo-scale, doc03 §8.1
  #checkov:skip=CKV_AWS_21: Versioning disabled by design, doc03 §8.1
}

resource "aws_s3_bucket_server_side_encryption_configuration" "raw_emails" {
  bucket = aws_s3_bucket.raw_emails.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "raw_emails" {
  bucket                  = aws_s3_bucket.raw_emails.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "raw_emails" {
  bucket = aws_s3_bucket.raw_emails.id
  versioning_configuration { status = "Disabled" }
}

resource "aws_s3_bucket_lifecycle_configuration" "raw_emails" {
  bucket = aws_s3_bucket.raw_emails.id
  rule {
    id     = "expire-90-days"
    status = "Enabled"
    expiration { days = 90 }
  }
}
```

<details><summary><b>Build order + design notes</b></summary>

**Build order**: dependency root — zero references to other modules' outputs. Bucket policy's `aws:SourceAccount` needs `data.aws_caller_identity.current.account_id`.

**Design notes**: first use of `data "aws_caller_identity" "current"` — every later module needing account ID reuses this pattern within its own `main.tf`.

</details>

---

### 6.2 `ses`

**Goal:** SES receipt rule set + receipt rule (S3 action → `raw-emails/` prefix, spam/virus scan enabled).

**Prereqs:** 6.1 (`bucket_name`).

**What to build:** `aws_ses_receipt_rule_set` + `aws_ses_active_receipt_rule_set` + `aws_ses_receipt_rule`.

**Inputs → Outputs:** `variables.tf` = `bucket_name`, `ses_recipient_address`. `outputs.tf` = none.

**Validation:** checkov has limited SES rules; nothing expected to fire.

> **Flag for Phase 7:** Domain verification (MX + TXT DNS records) is a manual step (7.1 step 2), not a Terraform resource in this module.

**External Docs:**
- [aws_ses_receipt_rule_set](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/ses_receipt_rule_set)
- [aws_ses_receipt_rule](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/ses_receipt_rule)
- [SES receiving email — S3 action](https://docs.aws.amazon.com/ses/latest/dg/receiving-email-action-s3.html)
- [SES email receiving concepts](https://docs.aws.amazon.com/ses/latest/dg/receiving-email-concepts.html)

**Sample Code:**

```hcl
resource "aws_ses_receipt_rule_set" "main" {
  rule_set_name = "echo-receipt-rules-${var.env}"
}

resource "aws_ses_active_receipt_rule_set" "main" {
  rule_set_name = aws_ses_receipt_rule_set.main.rule_set_name
}

resource "aws_ses_receipt_rule" "store_to_s3" {
  name          = "store-to-s3"
  rule_set_name = aws_ses_receipt_rule_set.main.rule_set_name
  recipients    = [var.ses_recipient_address]
  enabled       = true
  scan_enabled  = true  # spam/virus scanning

  s3_action {
    bucket_name       = var.bucket_name
    object_key_prefix = "raw-emails/"
    position          = 1
  }
}
```

<details><summary><b>Build order + design notes</b></summary>

**Build order**: rule_set → active_rule_set → receipt_rule. Terraform resolves from resource references (no explicit `depends_on`).

**Design notes**: SES inbound receiving requires the domain to be a verified identity — resolved as a manual runbook step alongside the MX record (7.1 step 2).

</details>

---

### 6.3 `sqs`

**Goal:** Triage queue with redrive to DLQ.

**Prereqs:** None.

**What to build:** `aws_sqs_queue` (main, SSE-SQS, redrive_policy → DLQ) + `aws_sqs_queue` (DLQ, 14-day retention) + `aws_sqs_queue_redrive_allow_policy`.

**Inputs → Outputs:** `variables.tf` = `env`, `sqs_visibility_timeout`, `sqs_max_receive_count`. `outputs.tf` = `queue_arn`, `queue_url`, `dlq_arn`.

**Validation:** `CKV_AWS_27` (encryption) should pass cleanly with `sqs_managed_sse_enabled=true`.

**External Docs:**
- [aws_sqs_queue](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/sqs_queue)
- [aws_sqs_queue_redrive_allow_policy](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/sqs_queue_redrive_allow_policy)
- [SQS dead-letter queues](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-dead-letter-queues.html)

**Sample Code:**

```hcl
resource "aws_sqs_queue" "dlq" {
  name                      = "echo-triage-dlq-${var.env}"
  message_retention_seconds = 1209600  # 14 days
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "main" {
  name                       = "echo-triage-queue-${var.env}"
  visibility_timeout_seconds = var.sqs_visibility_timeout
  sqs_managed_sse_enabled    = true
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = var.sqs_max_receive_count
  })
}

resource "aws_sqs_queue_redrive_allow_policy" "dlq" {
  queue_url = aws_sqs_queue.dlq.id
  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = [aws_sqs_queue.main.arn]
  })
}
```

<details><summary><b>Build order + design notes</b></summary>

**Build order**: main queue's `redrive_policy` → `dlq.arn`; DLQ's `redrive_allow_policy` → `main.arn` — two-way reference, Terraform resolves from its dependency graph.

**Design notes**: first module with two resources referencing each other's attributes.

</details>

---

### 6.4 `sns`

**Goal:** Two SNS topics: `alert-topic` (with filtered subscriptions for `urgent`/`needs_review`) and `ops-alarms` (unfiltered).

**Prereqs:** None.

**What to build:** 2× `aws_sns_topic` + 3× `aws_sns_topic_subscription` (2 filtered, 1 unfiltered).

**Inputs → Outputs:** `variables.tf` = `env`, `alert_email`. `outputs.tf` = `alert_topic_arn`, `ops_alarms_topic_arn`.

**Validation:** Suppress `CKV_AWS_26` (SNS KMS encryption) — no KMS per doc03 §6.

> **Phase 7 note:** Email subscriptions start as `PendingConfirmation` — must click the confirmation link.

**External Docs:**
- [aws_sns_topic](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/sns_topic)
- [aws_sns_topic_subscription](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/sns_topic_subscription)
- [SNS subscription filter policies](https://docs.aws.amazon.com/sns/latest/dg/sns-subscription-filter-policies.html)

**Sample Code:**

```hcl
resource "aws_sns_topic" "alert" {
  name = "echo-alert-topic-${var.env}"
  #checkov:skip=CKV_AWS_26: No KMS per doc03 §6, demo-scale
}

resource "aws_sns_topic_subscription" "alert_urgent" {
  topic_arn = aws_sns_topic.alert.arn
  protocol  = "email"
  endpoint  = var.alert_email
  filter_policy = jsonencode({
    alert_type = ["urgent"]
  })
}

resource "aws_sns_topic_subscription" "alert_needs_review" {
  topic_arn = aws_sns_topic.alert.arn
  protocol  = "email"
  endpoint  = var.alert_email
  filter_policy = jsonencode({
    alert_type = ["needs_review"]
  })
}
```

<details><summary><b>Build order + design notes</b></summary>

**Build order**: both topics and subscriptions are independent — 4 sibling resources, no ordering dependency.

**Design notes**: filter-policy JSON (`{"alert_type": ["urgent"]}` / `{"alert_type": ["needs_review"]}`) must match doc03 §7.1's values exactly — a typo silently prevents delivery.

</details>

---

### 6.5 `dynamodb`

**Goal:** `EmailTriageResults` table — PK `email_id`, PAY_PER_REQUEST, TTL on `ttl`.

**Prereqs:** None.

**What to build:** `aws_dynamodb_table`.

**Inputs → Outputs:** `variables.tf` = `env`. `outputs.tf` = `table_name`, `table_arn`.

**Validation:**
- `CKV_AWS_28` (point-in-time recovery) — **fix** with `point_in_time_recovery { enabled = true }` (one line, no cost at demo scale).

**External Docs:**
- [aws_dynamodb_table](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/dynamodb_table)
- [DynamoDB TTL](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/TTL.html)
- [DynamoDB billing modes](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/HowItWorks.ReadWriteCapacityMode.html)

**Sample Code:**

```hcl
resource "aws_dynamodb_table" "triage_results" {
  name         = "EmailTriageResults-${var.env}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "email_id"

  attribute {
    name = "email_id"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = true  # fixes CKV_AWS_28, no cost at PAY_PER_REQUEST
  }
}
```

<details><summary><b>Build order + design notes</b></summary>

**Build order**: single resource, simplest module.

**Design notes**: doc04 §1.3 lists `apigateway` as a consumer of this module's outputs, but `apigateway`'s variables have no DynamoDB inputs. Pass outputs only to `iam`, `lambda`, `demo-data`.

</details>

---

### 6.6 `iam`

**Goal:** 3 Lambda execution roles (inline policies from doc03 §6.1-6.3) + GitHub OIDC provider + `ECHOGitHubActionsRole`.

**Prereqs:** 6.1, 6.3, 6.4, 6.5 (need ARNs for policy resources).

**What to build:** 3× `aws_iam_role` + 3× `aws_iam_role_policy` + `data "tls_certificate"` + `aws_iam_openid_connect_provider` + OIDC role + deployer policy.

**Inputs → Outputs:** `variables.tf` = `s3_bucket_arn`, `sqs_queue_arn`, `dynamodb_table_arn`, `sns_alert_topic_arn`, `github_org`, `github_repo`, `env`, `region`. `outputs.tf` = `lambda1/2/3_role_arn`, `github_actions_role_arn`.

**Validation:**
- Suppress wildcard-resource findings on `comprehend:DetectPiiEntities` and `xray:Put*` — AWS-imposed, no resource-level scoping exists.
- Suppress broad deployer permissions — doc05 §5.4 rationale.
- `data.tls_certificate` requires live HTTPS to `token.actions.githubusercontent.com` at plan time.

**External Docs:**
- [aws_iam_role](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role)
- [aws_iam_role_policy](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy)
- [aws_iam_openid_connect_provider](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_openid_connect_provider)
- [GitHub OIDC with AWS](https://docs.github.com/en/actions/security-for-github-actions/security-hardening-your-deployments/configuring-openid-connect-in-amazon-web-services)
- [IAM policy elements reference](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_elements.html)
- [Lambda execution role](https://docs.aws.amazon.com/lambda/latest/dg/lambda-intro-execution-role.html)

**Sample Code — Lambda execution role + inline policy:**

```hcl
resource "aws_iam_role" "lambda_triage" {
  name = "echo-lambda-triage-${var.env}"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "lambda_triage" {
  name = "echo-lambda-triage-policy"
  role = aws_iam_role.lambda_triage.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
        Resource = var.sqs_queue_arn
      },
      {
        Effect   = "Allow"
        Action   = ["comprehend:DetectPiiEntities"]
        Resource = "*"  # AWS-imposed — no resource-level scoping
        #checkov:skip=CKV_AWS_111: comprehend has no resource-level permissions
      },
      {
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel"]
        Resource = "arn:aws:bedrock:${var.region}::foundation-model/anthropic.*"
      },
      # ... (DynamoDB, SNS, Logs, X-Ray statements from doc03 §6.2)
    ]
  })
}
```

**Sample Code — GitHub OIDC provider + trust policy:**

```hcl
data "tls_certificate" "github_oidc" {
  url = "https://token.actions.githubusercontent.com"
}

resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.github_oidc.certificates[0].sha1_fingerprint]
}

resource "aws_iam_role" "github_actions" {
  name = "ECHOGitHubActionsRole"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = aws_iam_openid_connect_provider.github.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
        }
        StringLike = {
          "token.actions.githubusercontent.com:sub" = "repo:${var.github_org}/${var.github_repo}:*"
        }
      }
    }]
  })
}
```

<details><summary><b>Build order + design notes</b></summary>

**Build order**: 3 execution roles (transcription of doc03 §6.1-6.3); OIDC chain: `data "tls_certificate"` → `openid_connect_provider` → role → policy.

**Design notes**: largest module by policy-statement count (~30 statements). `ECHOInsightsCaller` and invoke permissions live elsewhere (cycle-avoidance, doc04 §1.1).

</details>

---

### 6.7 `lambda`

**Goal:** Shared-utils layer + 3 Lambda functions + S3 notification trigger (Lambda#1) + SQS event source mapping (Lambda#2).

**Prereqs:** 6.6, 6.1, 6.3, 6.5, 6.4.

**What to build:** `aws_lambda_layer_version` + 3× `aws_lambda_function` + `aws_s3_bucket_notification` + `aws_lambda_permission` (S3 invoke) + `aws_lambda_event_source_mapping`.

**Inputs → Outputs:** `variables.tf` = role ARNs, bucket/queue/table/topic values, zip paths. `outputs.tf` = `layer_arn`, `lambda1/2/3_function_name`/`arn`/`invoke_arn`.

**Validation:**
- X-Ray tracing should pass cleanly. Suppress reserved-concurrency findings (demo-scale).
- Lambda#3 `timeout = 28` must be hardcoded (not a variable).
- S3 notification needs explicit `depends_on = [aws_lambda_permission.s3_invoke_ingest]`.

**External Docs:**
- [aws_lambda_function](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/lambda_function)
- [aws_lambda_layer_version](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/lambda_layer_version)
- [aws_lambda_permission](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/lambda_permission)
- [aws_lambda_event_source_mapping](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/lambda_event_source_mapping)
- [aws_s3_bucket_notification](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_notification)
- [Lambda X-Ray tracing](https://docs.aws.amazon.com/lambda/latest/dg/services-xray.html)

**Sample Code — Lambda function with layer + env vars:**

```hcl
resource "aws_lambda_layer_version" "shared_utils" {
  layer_name          = "echo-shared-utils-${var.env}"
  filename            = "${var.lambda_artifacts_dir}/shared_utils_layer.zip"
  source_code_hash    = filebase64sha256("${var.lambda_artifacts_dir}/shared_utils_layer.zip")
  compatible_runtimes = ["python3.13"]
}

resource "aws_lambda_function" "triage" {
  function_name    = "echo-triage-${var.env}"
  filename         = "${var.lambda_artifacts_dir}/lambda_triage.zip"
  source_code_hash = filebase64sha256("${var.lambda_artifacts_dir}/lambda_triage.zip")
  handler          = "handler.handler"
  runtime          = "python3.13"
  architectures    = ["arm64"]
  role             = var.lambda2_role_arn
  timeout          = var.lambda2_timeout
  layers           = [aws_lambda_layer_version.shared_utils.arn]

  tracing_config { mode = "Active" }

  environment {
    variables = {
      DYNAMODB_TABLE_NAME = var.dynamodb_table_name
      ALERT_TOPIC_ARN     = var.sns_alert_topic_arn
    }
  }
}
```

**Sample Code — S3 notification with depends_on:**

```hcl
resource "aws_lambda_permission" "s3_invoke_ingest" {
  statement_id   = "AllowS3Invoke"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.ingest.function_name
  principal      = "s3.amazonaws.com"
  source_arn     = var.s3_bucket_arn
  source_account = data.aws_caller_identity.current.account_id
}

resource "aws_s3_bucket_notification" "ingest_trigger" {
  bucket = var.s3_bucket_id

  lambda_function {
    lambda_function_arn = aws_lambda_function.ingest.arn
    events             = ["s3:ObjectCreated:*"]
    filter_prefix      = "raw-emails/"
  }

  depends_on = [aws_lambda_permission.s3_invoke_ingest]
}
```

<details><summary><b>Build order + design notes</b></summary>

**Build order**: layer first → 3 functions (all reference layer ARN) → Lambda#1 trigger resources → Lambda#2 event source mapping. Lambda#3 has no trigger here (lives in `apigateway`).

**Design notes**: most cross-module inputs of any module (6 modules feed in). S3 validates the Lambda's resource policy when configuring the notification — hence the explicit `depends_on`.

</details>

---

### 6.8 `apigateway`

**Goal:** REST API `/insights` endpoint (AWS_IAM auth, AWS_PROXY → Lambda#3) + `ECHOInsightsCaller` role + Lambda#3 invoke permission.

**Prereqs:** 6.7 (`lambda3_invoke_arn`/`arn`/`function_name`).

**What to build:** `aws_api_gateway_rest_api` + `_resource` + `_method` + `_integration` + `_deployment` + `_stage` + `aws_api_gateway_account` + `aws_lambda_permission` + `ECHOInsightsCaller` role + policy.

**Inputs → Outputs:** `variables.tf` = Lambda#3 values, `env`, `region`, `caller_iam_user_arn`. `outputs.tf` = `api_endpoint`, `insights_caller_role_arn`.

**Validation:**
- Suppress missing request validation / throttling — deferred per doc01.
- `execution_arn` is `(known after apply)` for new APIs — expected.
- Confirm `integration_http_method = "POST"` (required for Lambda proxy regardless of API method).

**External Docs:**
- [aws_api_gateway_rest_api](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/api_gateway_rest_api)
- [aws_api_gateway_integration](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/api_gateway_integration)
- [API Gateway IAM authorization](https://docs.aws.amazon.com/apigateway/latest/developerguide/permissions.html)
- [API Gateway Lambda proxy integration](https://docs.aws.amazon.com/apigateway/latest/developerguide/set-up-lambda-proxy-integrations.html)

**Sample Code — REST API → resource → method → integration chain:**

```hcl
resource "aws_api_gateway_rest_api" "insights" {
  name = "echo-insights-${var.env}"
}

resource "aws_api_gateway_resource" "insights" {
  rest_api_id = aws_api_gateway_rest_api.insights.id
  parent_id   = aws_api_gateway_rest_api.insights.root_resource_id
  path_part   = "insights"
}

resource "aws_api_gateway_method" "insights_post" {
  rest_api_id   = aws_api_gateway_rest_api.insights.id
  resource_id   = aws_api_gateway_resource.insights.id
  http_method   = "POST"
  authorization = "AWS_IAM"
}

resource "aws_api_gateway_integration" "insights_lambda" {
  rest_api_id             = aws_api_gateway_rest_api.insights.id
  resource_id             = aws_api_gateway_resource.insights.id
  http_method             = aws_api_gateway_method.insights_post.http_method
  integration_http_method = "POST"  # Always POST for Lambda proxy!
  type                    = "AWS_PROXY"
  uri                     = var.lambda3_invoke_arn
}
```

<details><summary><b>Build order + design notes</b></summary>

**Build order**: rest_api → resource → method → integration → deployment → stage. Permission + InsightsCaller reference the API's own `execution_arn`.

**Design notes**: `caller_iam_user_arn` is the one "personal" Terraform variable. This is where doc04 §1.1's cycle-avoidance pays off.

</details>

---

### 6.9 `cloudwatch`

**Goal:** Dashboard (FR14) + DLQ-depth alarm + sentiment anomaly detector + Lambda#1 on-failure destination.

**Prereqs:** 6.7, 6.3, 6.4.

**What to build:** `aws_cloudwatch_dashboard` + 2× `aws_cloudwatch_metric_alarm` + `aws_lambda_function_event_invoke_config`.

**Inputs → Outputs:** `variables.tf` = function names, `dlq_arn`, `ops_alarms_topic_arn`. `outputs.tf` = none.

**Validation:**
- `terraform validate` won't catch malformed dashboard JSON — only console/apply surfaces that.
- EMF-based alarms reference metrics that don't exist yet (`INSUFFICIENT_DATA` until Lambda runs) — expected.

**External Docs:**
- [aws_cloudwatch_dashboard](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_dashboard)
- [aws_cloudwatch_metric_alarm](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_metric_alarm)
- [CloudWatch anomaly detection](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch_Anomaly_Detection.html)
- [aws_lambda_function_event_invoke_config](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/lambda_function_event_invoke_config)
- [CloudWatch dashboard body syntax](https://docs.aws.amazon.com/AmazonCloudWatch/latest/APIReference/CloudWatch-Dashboard-Body-Structure.html)

**Sample Code — DLQ-depth alarm:**

```hcl
resource "aws_cloudwatch_metric_alarm" "dlq_depth" {
  alarm_name          = "echo-dlq-depth-${var.env}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Sum"
  threshold           = 0
  alarm_actions       = [var.ops_alarms_topic_arn]
  dimensions = {
    QueueName = "echo-triage-dlq-${var.env}"
  }
}
```

**Sample Code — anomaly detection alarm (different shape!):**

```hcl
resource "aws_cloudwatch_metric_alarm" "sentiment_anomaly" {
  alarm_name          = "echo-negative-sentiment-anomaly-${var.env}"
  comparison_operator = "LessThanLowerOrGreaterThanUpperThreshold"
  evaluation_periods  = 3
  threshold_metric_id = "ad1"
  alarm_actions       = [var.ops_alarms_topic_arn]

  metric_query {
    id          = "m1"
    return_data = true
    metric {
      metric_name = "SentimentCount"
      namespace   = "ECHO"
      period      = 300
      stat        = "Sum"
      dimensions  = { sentiment = "negative" }
    }
  }

  metric_query {
    id          = "ad1"
    expression  = "ANOMALY_DETECTION_BAND(m1, 2)"
    label       = "Negative sentiment anomaly band"
    return_data = true
  }
}
```

<details><summary><b>Build order + design notes</b></summary>

**Build order**: 4 largely-independent resources. Anomaly-detection alarm uses `ANOMALY_DETECTION_BAND` (different shape from DLQ alarm — don't copy-paste).

**Design notes**: verify EMF metric names/dimensions in Phases 4-5 match alarm references exactly — a mismatch silently produces a never-firing alarm.

</details>

---

### 6.10 `cloudtrail`

**Goal:** Trail (management + S3 data events on `raw-emails`) + dedicated `cloudtrail-logs` bucket.

**Prereqs:** 6.1 (`s3_bucket_arn`).

**What to build:** `aws_s3_bucket` (cloudtrail-logs) + `_policy` + `aws_cloudtrail`.

**Inputs → Outputs:** `variables.tf` = `s3_bucket_arn`, `env`, `region`. `outputs.tf` = `trail_arn`.

**Validation:**
- Suppress `CKV_AWS_18`/`CKV_AWS_21` on cloudtrail-logs bucket. Fix `CKV_AWS_36` (log file validation) with `enable_log_file_validation = true`.
- Data-event selector ARN must have trailing slash: `"${var.s3_bucket_arn}/"`.

<details><summary><b>Build order + design notes</b></summary>

**Build order**: logs bucket + policy → trail (trail's `s3_bucket_name` references the bucket).

**Design notes**: second module owning its own logging bucket. Trailing slash on data-event ARN is critical — wrong format silently logs zero events.

</details>

---

### 6.11 `security-baseline`

**Goal:** GuardDuty detector (S3 Protection) + Security Hub (CIS Benchmark) + AWS Config recorder + dedicated `config-logs` bucket.

**Prereqs:** None (terminal module).

**What to build:** `aws_guardduty_detector` + `aws_securityhub_account` + `aws_securityhub_standards_subscription` + `aws_config_configuration_recorder` + `_delivery_channel` + `_recorder_status` + config-logs bucket + policy.

**Inputs → Outputs:** `variables.tf` = `env`, `region`. `outputs.tf` = none.

**Validation:**
- Account/region singletons — `envs/prod` would conflict with `envs/dev` in same account+region.
- Suppress bucket findings same as 6.1/6.10.

> **Cost note:** GuardDuty + Security Hub have 30-day free trials. Disable after demo if keeping env beyond 30 days.

> **Open question:** Config recorder needs an IAM role (not in `iam` module scope). Create inline in this module.

<details><summary><b>Build order + design notes</b></summary>

**Build order**: config-logs bucket + policy → Config delivery channel + recorder.

**Design notes**: these are account/region-level singletons — the concrete reason `envs/prod` is documented-but-not-deployed.

</details>

---

### 6.12 `demo-data`

**Goal:** Seed ~10-15 synthetic DynamoDB items so `/insights` has data immediately after `apply`.

**Prereqs:** 6.5 (`dynamodb_table_name`).

**What to build:** `aws_dynamodb_table_item` resources (via `for_each` over a seed JSON file).

**Inputs → Outputs:** `variables.tf` = `dynamodb_table_name`. `outputs.tf` = none.

**Validation:**
- Items use DynamoDB's typed-attribute wire format (`{"S": "..."}`, `{"L": [...]}`). A missing type wrapper is a validate-time error.
- Use synthetic prefix (`demo-email-001`) for `email_id` values — avoids collision with real SES messageIds.

**External Docs:**
- [aws_dynamodb_table_item](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/dynamodb_table_item)
- [DynamoDB JSON format (typed attributes)](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/HowItWorks.NamingRulesDataTypes.html)
- [Terraform `for_each` with `jsondecode`](https://developer.hashicorp.com/terraform/language/meta-arguments/for_each)
- [Terraform `file` function](https://developer.hashicorp.com/terraform/language/functions/file)

**Sample Code — seed data JSON file (`seed-data/email_triage_results.json`):**

```json
[
  {
    "email_id": "demo-email-001",
    "category": "feature_request",
    "urgency": "medium",
    "sentiment": "constructive",
    "feature_tags": ["dark-mode", "mobile-app"],
    "review_status": "auto_processed",
    "received_at": "2026-06-20T09:00:00+00:00"
  },
  {
    "email_id": "demo-email-002",
    "category": "billing",
    "urgency": "high",
    "sentiment": "negative",
    "feature_tags": [],
    "review_status": "auto_processed",
    "received_at": "2026-06-20T10:30:00+00:00"
  }
]
```

**Sample Code — for_each with typed-attribute conversion:**

```hcl
locals {
  seed_records = jsondecode(file("${path.module}/seed-data/email_triage_results.json"))
}

resource "aws_dynamodb_table_item" "seed" {
  for_each   = { for r in local.seed_records : r.email_id => r }
  table_name = var.dynamodb_table_name
  hash_key   = "email_id"

  # DynamoDB wire format — every value needs a type wrapper:
  item = jsonencode({
    email_id      = { S = each.value.email_id }
    category      = { S = each.value.category }
    urgency       = { S = each.value.urgency }
    sentiment     = { S = each.value.sentiment }
    review_status = { S = each.value.review_status }
    received_at   = { S = each.value.received_at }
    feature_tags  = { L = [for tag in each.value.feature_tags : { S = tag }] }
  })
}
```

<details><summary><b>Build order + design notes</b></summary>

**Build order**: all items depend only on the table existing.

**Design notes**: first use of `for_each` in Phase 6. `jsondecode(file(var.demo_seed_data_file))` with `for_each` is likely cleaner than 10-15 hand-written resource blocks.

</details>

---

## Phase 7 — Bootstrap Deploy & Demo

Procedural — wires modules into `envs/dev`, runs the first `terraform apply`, and documents the demo + teardown.

---

### 7.1 One-Time Prerequisites (before any `terraform apply`)

1. **Domain DNS — MX record**: point domain's MX at `inbound-smtp.us-east-1.amazonaws.com` (priority 10).
2. **SES domain verification**: verify recipient domain as SES identity + DNS TXT record. Manual step alongside MX.
3. **Terraform state S3 bucket**: `aws s3 mb s3://echo-terraform-state-<ACCOUNT_ID> --region us-east-1`, enable versioning + SSE-S3.
4. **Local AWS credentials**: `aws configure` with sufficient permissions for first apply.
5. **`caller_iam_user_arn`**: `aws sts get-caller-identity` → copy ARN.
6. **`terraform.tfvars`**: copy from `.example`, fill all variables. Gitignored.
7. **Package Lambda artifacts locally**: doc05 §4.6 packaging steps run by hand for first apply.
8. **Demo seed data file**: create `infra/modules/demo-data/seed-data/email_triage_results.json`.

---

### 7.2 `envs/dev` Wiring

`infra/envs/dev/main.tf` instantiates all 12 modules in doc04 §1.3's dependency order, passing outputs as inputs.

Resolve:
- 6.2 `ses`: confirm domain verification stays manual (7.1 step 2).
- 6.11 `security-baseline`: confirm Config recorder IAM role is inline.

`outputs.tf` re-exports: `api_endpoint`, `insights_caller_role_arn`, `github_actions_role_arn`, `table_name`.

---

### 7.3 First `terraform apply` (bootstrap)

1. `cd infra/envs/dev && terraform init`.
2. `terraform plan` — review ~32-resource plan.
3. `terraform apply` — the only local apply for the project's lifetime.
4. **Confirm SNS email subscriptions** — click 3 confirmation links.
5. **Copy `github_actions_role_arn`** → GitHub secret `AWS_CI_ROLE_ARN`.

---

### 7.4 Post-Apply Smoke Tests

1. **Send a test email** to `ses_recipient_address`.
2. **S3**: confirm object under `raw-emails/`.
3. **DynamoDB**: scan for the new item with correct fields.
4. **SNS alert**: confirm delivery (send a second email with escalation language if needed).
5. **CloudWatch EMF**: confirm `ECHO/SentimentCount` + `ECHO/PiiEntitiesDetected` appear.
6. **X-Ray**: confirm trace with `email_id` annotation.
7. **CloudTrail**: confirm data event for `raw-emails` PutObject.
8. **`/insights`**: `sts assume-role` → `awscurl` SigV4 POST → 200 + answer.
9. **Unauthenticated `/insights`** → confirm 403.

---

### 7.5 CI/CD Handoff

Push a trivial change to confirm the GitHub Actions pipeline runs a real `terraform apply` via OIDC.

---

### 7.6 Demo Walkthrough

1. Architecture overview (doc03 §1 diagrams).
2. Send a live email — narrate SES → S3.
3. Show DynamoDB record (all classification fields).
4. Show SNS alert email.
5. PII redaction narrative — fake name/phone, show `pii_entities_detected > 0`.
6. Keyword override (DR4) — escalation language, show `urgency_override_applied=true`.
7. CloudWatch dashboard (FR14).
8. Anomaly detection (FR15) — explain the config.
9. X-Ray trace with `email_id` annotation (FR13).
10. `/insights` demo (FR12/FR16) — assume-role → SigV4 → answer.
11. Security posture — Security Hub, GuardDuty, Config.
12. Degraded-path narrative (optional) — FR17 + DR8.

---

### 7.7 Teardown / Cost Hygiene

- **GuardDuty + Security Hub**: disable after 30-day free trial if not in use.
- **Full teardown** (`terraform destroy`): safe with two notes — (1) `demo-data` items destroyed with table (expected); (2) `aws_api_gateway_account` is account-level singleton — confirm no other API Gateway resources exist.
- **State bucket** and **OIDC provider**: OIDC is managed by `envs/dev`, so full destroy removes CI's deploy ability.
