# 08 - Pytest Guide

> Status: Draft.

## Overview

This is the testing companion to doc06. Every story in doc06 follows **Red → Green → Refactor**: doc06's "Test" table for a story IS the Red step's spec (write the tests, watch them fail), the "Implementation" section is the Green step (write just enough code to pass), and Refactor is cleanup with the tests still green.

This doc covers the infrastructure that makes that loop work locally and in CI (doc05 §4.5: `pip install -r src/layers/shared_utils/requirements.txt -r requirements-dev.txt && pytest tests/`):

> Tip: Windows users can run `./scripts/install-dev.ps1` and macOS/Linux users can run `./scripts/install-dev.sh` to create a `.venv` and install the required packages.

1. `pytest.ini` — entry point / config
2. `requirements-dev.txt`
3. `tests/` directory layout
4. `conftest.py` — fixture architecture, including a same-named-`handler.py` collision problem and its fix
5. Moto — what it covers, what it doesn't, and why activation order matters
6. The four mocking patterns (A-D) used across doc06's stories
7. The TDD workflow itself — running single tests, coverage, the threshold gate

## 1. Entry Point — `pytest.ini`

```ini
[pytest]
testpaths = tests
pythonpath =
    src/layers/shared_utils
addopts =
    -ra
    --cov=src
    --cov-report=term-missing
    --cov-fail-under=80
```

Line by line:

| Setting | Value | Why |
|---|---|---|
| `testpaths` | `tests` | Plain `pytest` (no args) from the repo root collects only `tests/` — not `infra/` or anything else. |
| `pythonpath` | `src/layers/shared_utils` | Puts `retry_config.py` on `sys.path` as a bare-importable module (`from retry_config import GENERAL_CONFIG`), mirroring its runtime location at `/opt/python/retry_config.py` (doc05 §4.6). This is the **only** directory added globally — see §4.4 for why each Lambda's own `src/lambda_*/` directory is handled per-fixture instead of here. |
| `addopts` `-ra` | — | Prints a short summary of every non-passing test (failed/error/skipped) at the end of the run — useful once the suite has 9-test files like `test_handler.py` (4.5/4.6) and a failure shouldn't get lost in the scroll. |
| `addopts` `--cov=src` | — | Enables `pytest-cov`, measuring coverage for every file under `src/` by **file path** — this works regardless of how a module is imported (bare name vs. dotted path), since `coverage.py` instruments via `sys.settrace`, not the import system. |
| `addopts` `--cov-report=term-missing` | — | Coverage summary printed to the terminal includes the **line numbers** of uncovered lines per file — directly actionable during the Refactor step. |
| `addopts` `--cov-fail-under=80` | — | **The coverage-threshold gate** doc05 §4.5 refers to ("any failing test (or coverage-threshold miss)"). Baked into `addopts` means it's enforced on *every* invocation — local `pytest`, CI's `pytest tests/`, even `pytest -k foo` — with no separate CI step. 80% is a starting point: Phase 2's first story (`retry_config.py`, pure data) hits 100% trivially; later stories with DEGRADE branches (e.g., 4.6's `sns.publish` try/except) need their failure-path tests (already specified in doc06's tables) to keep the overall number above 80%. |

Note what's **not** here: `src/lambda_ingest`, `src/lambda_triage`, `src/lambda_insights` are deliberately absent from `pythonpath`. All three contain a file named `handler.py` — if all three directories were on `sys.path` simultaneously, `import handler` would be ambiguous (Python resolves it to whichever is found first and caches that under `sys.modules["handler"]` for the rest of the process, so the *other two* Lambdas' tests would import the *wrong* `handler.py`). §4.4 below covers the per-fixture fix.

## 2. `requirements-dev.txt`

```
pytest>=8.0
pytest-cov>=5.0
moto>=5.0
```

| Package | Provides |
|---|---|
| `pytest` | Test runner, fixtures, `capsys`/`monkeypatch` builtins, `pytest.ini` config. |
| `pytest-cov` | The `--cov*` flags in `addopts` (wraps `coverage.py`, which is pulled in transitively — no separate `coverage` line needed). |
| `moto` | In-memory AWS service mocks (`mock_aws`) — see §5. |

`boto3`/`botocore`/`aws-xray-sdk` are **not** here — they come from `src/layers/shared_utils/requirements.txt` (doc05 §4.4), and CI installs both files together (doc05 §4.5). This mirrors the runtime split: the shared layer's dependencies live at `/opt/python`, test-only dependencies don't ship in any Lambda package.

## 3. Test Layout — `tests/`

```
tests/
├── __init__.py                          # makes tests/ a package — see below
├── conftest.py                          # aws_credentials + per-Lambda fixtures (§4)
├── layers/
│   ├── __init__.py
│   └── shared_utils/
│       ├── __init__.py
│       └── test_retry_config.py         # Phase 2.1 — no AWS, no fixtures
├── lambda_ingest/
│   ├── __init__.py
│   ├── test_mime_parser.py              # Phase 3.1 — no AWS, no fixtures
│   └── test_handler.py                  # Phase 3.2 — Pattern A (S3 + SQS)
├── lambda_triage/
│   ├── __init__.py
│   ├── test_keyword_rules.py            # Phase 4.1 — no AWS, no fixtures
│   ├── test_pii.py                      # Phase 4.2 — Pattern B (Comprehend)
│   ├── test_classify.py                 # Phase 4.3 — Pattern B (Bedrock)
│   ├── test_persist.py                  # Phase 4.4 — Pattern A (DynamoDB)
│   └── test_handler.py                  # Phase 4.5/4.6 — Patterns C + D
└── lambda_insights/
    ├── __init__.py
    ├── test_query.py                    # Phase 5.1 — Pattern A + pagination side_effect
    ├── test_synthesize.py               # Phase 5.2 — Pattern B + BytesIO
    └── test_handler.py                  # Phase 5.3 — Patterns C + D
```

**Why every directory needs `__init__.py`**: three of these directories each contain a file named `test_handler.py`. With pytest's default import mode and no `__init__.py`, pytest imports each test file as a top-level module named after its filename — the second `test_handler.py` it collects would collide with the first in `sys.modules` and fail with an "import file mismatch" error. `__init__.py` files make `tests/` (and each subdirectory) a package, so pytest imports them by their full dotted path instead (`tests.lambda_ingest.test_handler`, `tests.lambda_triage.test_handler`, `tests.lambda_insights.test_handler`) — distinct names, no collision.

This is a *different* collision from the `src/lambda_*/handler.py` one mentioned in §1 — that one is about the **source** modules under test, not the test files themselves. Both need fixing; §4.4 covers the source-side one.

`tests/` mirrors `src/`'s structure but lives separately (doc06 §1.1) so test files aren't swept into the Lambda `.zip`/layer artifacts during packaging (doc05 §4.6).

## 4. `conftest.py` — Fixture Architecture

### 4.1 Why `aws_credentials` exists

```
aws_credentials  (function-scoped, no AWS calls)
   │
   ├── ingest_handler        → reload: handler                         (S3 + SQS)
   ├── triage_handler        → reload: persist, pii, classify,
   │                            keyword_rules, then handler             (DynamoDB + SNS,
   │                                                                       + patch Comprehend/Bedrock)
   └── insights_handler      → reload: query, synthesize, then handler  (DynamoDB,
                                                                            + patch Bedrock)
```

`test_retry_config.py`, `test_mime_parser.py`, and `test_keyword_rules.py` use **none** of these fixtures — they're pure-Python, self-contained (doc06 2.1/3.1/4.1).

`aws_credentials` sets dummy values for `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and `AWS_DEFAULT_REGION` via `monkeypatch.setenv` (auto-restored after each test).

**Why this is needed even under moto**: boto3 resolves credentials through a chain (env vars → shared config file → instance metadata/IMDS → ...) *before* a request is ever sent — and moto only intercepts the request once it's sent. If that chain finds nothing at all, boto3 raises `NoCredentialsError` (or, worse, the IMDS step can hang/timeout in a sandboxed CI runner) — both *before* moto gets a chance to respond. Dummy env-var credentials satisfy the chain at its very first, cheapest step, regardless of whether moto is even active for a given test.

### 4.2 The three per-Lambda fixtures

Each follows the same shape: enter `mock_aws()`, create the AWS resources that Lambda's module-level code depends on, set the matching environment variables, then bring the Lambda's modules into a state where their module-level clients/tables are bound to *this test's* mock backend — and finally `yield` the (re-imported) `handler` module for the test to call `handler.handler(event, context)` against.

**`ingest_handler`** (Phase 3.2)

1. Enter `mock_aws()`.
2. `boto3.client("s3").create_bucket(Bucket=<name>)`.
3. `queue_url = boto3.client("sqs").create_queue(QueueName=<name>)["QueueUrl"]`.
4. `monkeypatch.setenv("TRIAGE_QUEUE_URL", queue_url)`.
5. Bring `handler` into this test's state — see §4.4.
6. `yield handler`.

No sibling-module reload chain: `handler.py` (3.2) only does `from mime_parser import parse_email` and `from retry_config import GENERAL_CONFIG`, neither of which holds AWS state — only `handler.py` itself constructs `s3`/`sqs` clients.

**`triage_handler`** (Phase 4.5/4.6)

1. Enter `mock_aws()`.
2. `boto3.resource("dynamodb").create_table(TableName=<name>, KeySchema=[{"AttributeName": "email_id", "KeyType": "HASH"}], AttributeDefinitions=[{"AttributeName": "email_id", "AttributeType": "S"}], BillingMode="PAY_PER_REQUEST")`.
3. `topic_arn = boto3.client("sns").create_topic(Name=<name>)["TopicArn"]`.
4. `monkeypatch.setenv("DYNAMODB_TABLE_NAME", <name>)`, `monkeypatch.setenv("ALERT_TOPIC_ARN", topic_arn)`.
5. `importlib.reload(persist)`, `importlib.reload(pii)`, `importlib.reload(classify)`, `importlib.reload(keyword_rules)` — each of these modules' own `sys.modules` entry always points at the correct file (no name collisions among them), so a plain reload rebinds their module-level clients/tables (`persist.table`, `pii.comprehend`, `classify.bedrock`) to *this* test's `mock_aws()` backend.
6. Bring `handler` into this test's state — see §4.4. Its top-level `import persist` / `import pii` / `import classify` / `import keyword_rules` now pick up the just-reloaded (freshly-bound) sibling modules from step 5, and its own `sns = boto3.client("sns", ...)` is constructed while `mock_aws()` is active.
7. `yield handler`.

Individual tests then layer `patch.object(handler.pii.comprehend, "detect_pii_entities", return_value=...)` and/or `patch.object(handler.classify.bedrock, "invoke_model", return_value=...)` — per-test, since each test needs different Comprehend/Bedrock responses (this is Pattern D, §6.4).

**`insights_handler`** (Phase 5.1/5.3) — same shape as `triage_handler`, narrower:

1. Enter `mock_aws()`, create the same `EmailTriageResults`-shaped table, set `DYNAMODB_TABLE_NAME`.
2. `importlib.reload(query)`, `importlib.reload(synthesize)`.
3. Bring `handler` into this test's state (§4.4).
4. `yield handler`.

Tests layer `patch.object(handler.synthesize.bedrock, "invoke_model", ...)` per-test.

### 4.3 What goes in the test itself vs. the fixture

The fixture's job ends at "`handler` is wired to a fresh mock backend." Per-test `patch.object` calls (Comprehend/Bedrock return values, the pagination `side_effect` in 5.1, etc.) belong in the test body — they vary per test case, so baking a single return value into the fixture would defeat the point of having multiple test cases.

### 4.4 The `handler.py` name collision, and its fix

All three Lambdas name their entry-point module `handler.py` (doc03 §5.2 — this matches AWS Lambda's `<file>.<function>` handler-naming convention, e.g. `handler.handler`, independently per deployment package). Locally, all three `src/lambda_*/` directories exist side by side, and three different test files each want to `import handler`.

`importlib.reload(handler)` is **not** sufficient on its own here: `reload` re-executes the module using its *existing* `__spec__`, which still points at whichever `handler.py` was imported first — it can't redirect to a different Lambda's file.

The fix, inside each of the three fixtures' "bring `handler` into this test's state" step:

1. `sys.modules.pop("handler", None)` — evict whatever `handler` is currently cached, regardless of which Lambda it came from.
2. `monkeypatch.syspath_prepend(<absolute path to this Lambda's src/lambda_*/ directory>)` — puts *this* Lambda's directory at the front of `sys.path`.
3. `import handler` — a fresh import, now resolved against the just-prepended directory. Its top-level code runs under the active `mock_aws()` context and already-set env vars, and (for triage/insights) its `import persist`/`import pii`/... etc. pick up the siblings reloaded in the prior step.

Because step 1 evicts unconditionally and step 2 always prepends *this* Lambda's directory to the front, this sequence is correct on every test invocation, regardless of which Lambda's tests ran before it in the same session — there's no "first time vs. subsequent time" branching to get right.

This is also why `src/lambda_ingest`, `src/lambda_triage`, `src/lambda_insights` are **not** in `pytest.ini`'s global `pythonpath` (§1) — putting all three on `sys.path` permanently wouldn't fix the collision (Python would still resolve `import handler` to whichever is found first and cache it), it would just make the bug *latent* until two `test_handler.py` files run in the same session. Handling it per-fixture, scoped to each test, is what actually mirrors the real Lambda runtime: each Lambda's `/var/task` contains *only its own* `handler.py` — there is never an ambiguity at runtime, only in a shared local test process.

## 5. Moto

### 5.1 What it is, and `mock_aws()` scope

[moto](https://github.com/getmoto/moto) intercepts the HTTP calls boto3/botocore make and serves them from an in-memory, per-test virtual AWS account — no real AWS credentials or network access needed. `mock_aws()` is a context manager (used as `with mock_aws():` inside each fixture, §4.2): everything created or called *while the `with` block is open* — buckets, queues, tables, topics, and all `get_item`/`put_item`/`scan`/`publish`/etc. calls — is isolated to that one virtual account. When the `with` block exits (fixture teardown, since each fixture is function-scoped), that virtual account and everything in it disappears — the next test starts from nothing.

### 5.2 Supported vs. unsupported services

| Service | Operations used | moto support |
|---|---|---|
| S3 | `get_object`, `create_bucket` | Yes |
| SQS | `send_message`, `create_queue` | Yes |
| DynamoDB | `get_item`, `put_item`, `scan`, `create_table` | Yes |
| SNS | `publish`, `create_topic` | Yes |
| Comprehend | `detect_pii_entities` | **No** |
| Bedrock Runtime | `invoke_model` | **No** |

The first four are handled entirely by `mock_aws()` + Pattern A (§6.1). The last two need Pattern B (§6.2) instead — `mock_aws()` simply doesn't simulate these services, so calls to them would either error or (with no real credentials) fail outright if left unmocked.

### 5.3 Why activation order matters

Two distinct reasons module-level AWS objects need to be (re)built *while* `mock_aws()` is active and *after* the relevant env vars are set — both already touched on above, restated together here for clarity:

1. **Import-time `KeyError`**: `persist.py`/`query.py` read `os.environ["DYNAMODB_TABLE_NAME"]` *at module import time* to build `table = dynamodb.Table(...)`. If that env var isn't set yet when the module is first imported, the import itself raises `KeyError` — before any test logic, before moto is even relevant.
2. **Stale handles across tests**: each test gets a brand-new `mock_aws()` virtual account (§5.1). A module-level `table`/`comprehend`/`bedrock` object built during a *previous* test is bound to that *previous* (now torn-down) virtual account. `importlib.reload()` (§4.2) re-executes the module's top-level code against the *current* test's env vars and virtual account, producing fresh, correctly-bound objects.

## 6. Mocking Patterns

doc06 flags four numbered patterns across its stories. All four are really refinements of "make sure module-level AWS state is built at the right time, against the right backend" (§5.3) — but each has a distinct trigger and fix.

### 6.1 Pattern A — moto-backed, reload after activation

**When**: a module builds a boto3 client/resource/table at import time, for a service moto *does* support (S3, SQS, DynamoDB, SNS).

**Fix**: inside `mock_aws()`, after creating the resource and setting its env var, `importlib.reload(<module>)`.

**Used by**: 3.2 (S3 + SQS), 4.4 (DynamoDB), 5.1 (DynamoDB).

### 6.2 Pattern B — moto doesn't cover this service

**When**: Comprehend (`detect_pii_entities`, 4.2) or Bedrock Runtime (`invoke_model`, 4.3/5.2) — no virtual backend exists for these in moto.

**Fix**: `patch.object(<module>.<client_attr>, "<method>", return_value=... | side_effect=...)` directly on the already-constructed client object. No `mock_aws()`, no reload — the call never reaches moto at all; it's intercepted by the patch before botocore sends anything.

**Used by**: 4.2 (`pii.comprehend`), 4.3 (`classify.bedrock`), 5.2 (`synthesize.bedrock`).

### 6.3 Pattern C — reload chain

**When**: `handler.py` imports several Pattern-A siblings as modules (`import persist`, `import pii`, `import classify`, `import keyword_rules` for 4.5/4.6; `import query`, `import synthesize` for 5.3).

**Fix**: reload every affected sibling *first* (each is a same-file reload, no collision — §4.2 step 5), *then* bring `handler` into this test's state (§4.4) — so `handler`'s own top-level `import <sibling>` statements pick up the already-reloaded, freshly-bound sibling modules.

**Used by**: 4.5/4.6, 5.3.

### 6.4 Pattern D — double-mocking

**When**: a single test exercises both a Pattern-A dependency (DynamoDB via `persist`/`query`, SNS via `handler`'s own `sns` client) *and* a Pattern-B dependency (Comprehend via `pii`, Bedrock via `classify`/`synthesize`) in the same call.

**Fix**: combine — the fixture's `mock_aws()` context (still open) covers the Pattern-A side; the test body adds `patch.object(...)` calls (often as a `with` block wrapping the `handler.handler(event, context)` call, or via `monkeypatch.setattr`) for the Pattern-B side.

**Used by**: 4.5/4.6, 5.3.

### 6.5 Special-case techniques (not full patterns, but reused)

- **Pagination via `side_effect`** (5.1 test #5): `patch.object(query.table, "scan", side_effect=[<page 1 dict with "LastEvaluatedKey">, <page 2 dict without it>])` — each call to `.scan()` consumes the next item in the list. This is the only way to exercise `query.py`'s `LastEvaluatedKey` loop, since a demo-scale moto table never naturally produces a second page.
- **`io.BytesIO`-backed Bedrock response** (4.3, 5.2): `{"body": io.BytesIO(json.dumps({"content": [{"type": "text", "text": <model output>}]}).encode())}`. `response["body"]` is normally a `StreamingBody` (`.read()`-once); `io.BytesIO` has the same `.read()` interface without needing botocore's actual class. Shared helper: `mock_bedrock_response(text: str) -> dict`.
- **`capsys` for EMF assertions** (4.6): `handler.py`'s `_emit_emf` does a single `print(json.dumps(...))`. Tests call `capsys.readouterr().out`, take the one line, and `json.loads()` it to assert on the EMF document's keys/values.

## 7. TDD Workflow

### 7.1 Red → Green → Refactor, per story

For each doc06 story:

1. **Red** — write the test file (or test function) from doc06's "Test" table. Run it; it fails (the implementation doesn't exist yet, or doesn't yet satisfy this case).
2. **Green** — write just enough of doc06's "Implementation" to make that test pass, without breaking previously-green tests.
3. **Refactor** — with all tests green, clean up (naming, duplication) using `--cov-report=term-missing` (§1) to confirm the refactor didn't silently drop coverage of a branch.

Multi-test stories (4.5/4.6 each have 9 cases) don't need to go test-by-test in strict 1-9 order — but each new test added should be run alone first (next section) to confirm it's actually exercising the intended code path before running the full file.

### 7.2 Running a single test

```bash
pytest tests/lambda_triage/test_classify.py::test_valid_json_on_first_attempt -v
```

`-v` prints each test's name and PASS/FAIL individually — useful during Red, when you want to see *just* the new test's result without the rest of the (already-green) file's output.

To run every test whose name contains a substring (e.g., everything about the retry-escalation behavior across `classify`/`synthesize`):

```bash
pytest -k retry -v
```

To stop at the first failure (useful when a multi-test file like 4.6 has several failing at once and you want to fix them one at a time):

```bash
pytest tests/lambda_triage/test_handler.py -x
```

### 7.3 Coverage

Because `--cov=src --cov-report=term-missing --cov-fail-under=80` are baked into `pytest.ini`'s `addopts` (§1), **every** invocation — `pytest`, `pytest tests/lambda_triage/`, even the single-test command above — runs with coverage on and the 80% gate enforced. There's no separate `--cov` flag to remember, and no separate CI coverage step: a coverage-threshold miss fails the same `pytest tests/` command doc05 §4.5 runs.

`--cov-report=term-missing` output looks like:

```
Name                              Stmts   Miss  Cover   Missing
----------------------------------------------------------------
src/lambda_triage/handler.py         42      3    93%   58-60
```

`58-60` are the uncovered line numbers — during Refactor, this is the first place to look if the threshold is close to failing.

To temporarily run *without* the coverage gate (e.g., quickly checking one test's pass/fail without a coverage report cluttering the output) — but note the threshold check still runs against whatever subset of `src/` the selected tests cover, so a single-test invocation will almost always report well under 80% by itself:

```bash
pytest tests/lambda_triage/test_classify.py::test_valid_json_on_first_attempt -v --no-cov
```

`--no-cov` overrides the `addopts`-level coverage flags for that one invocation.
