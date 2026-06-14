# 05 - CI/CD Pipeline Spec

> **ECHO** (Email Classification & Handling Orchestrator) — an automated email triage, classification, and insights pipeline.

> Status: Sections 1-7 confirmed/locked. `docs/05-cicd-pipeline-spec.md` complete.

## 1. Overview

A single flow, triggered on every `push` to `main` — for this demo, commits land directly on `main` (no PR-based merge gate). The workflow runs 5 security/quality gates in parallel, then packages the Lambda artifacts — needed for `terraform apply`'s `source_code_hash` computation (doc04 §6's `lambda_artifacts_dir`) — then runs `terraform apply` against `envs/dev` (the only deployed environment per doc04 §1.3). `terraform apply` prints its plan inline before applying, so there's no separate plan stage.

### 1.1 Pipeline Flow (`push` → `main`)

```
Developer pushes commit → main
           │
           ▼
┌───────────────────────────────────────┐
│ Security & quality gates (parallel)     │
│  - gitleaks  (secret scan)               │
│  - bandit    (Python SAST)               │
│  - checkov   (IaC scan, Terraform)       │
│  - pip-audit (dependency CVE scan)       │
│  - pytest    (unit tests, src/)          │
└──────────────────┬──────────────────────┘
                    │ all pass
                    ▼
┌───────────────────────────────────────┐
│ Package Lambda artifacts                 │
│  - shared-utils layer .zip               │
│  - ingest / triage / insights .zip       │
└──────────────────┬──────────────────────┘
                    │
                    ▼
┌───────────────────────────────────────┐
│ terraform apply (envs/dev)               │
│  → AWS resources updated                  │
└───────────────────────────────────────┘
```

## 2. Tooling Decision

### 2.1 CI/CD Platform: GitHub Actions

| | GitHub Actions | GitLab CI | CircleCI | AWS CodePipeline + CodeBuild |
| --- | --- | --- | --- | --- |
| Cost | Free for public repos; 2,000 free min/mo private — negligible at this scale | Free tier exists, but ties you to GitLab-hosted repos | Free tier (6,000 min/mo) but a third platform separate from source hosting | Pay-per-build-minute; no comparably generous free tier |
| OIDC → AWS | Native `aws-actions/configure-aws-credentials` + GitHub OIDC provider — no stored long-lived credentials | Also supports OIDC to AWS, but only if hosted on GitLab | Supports OIDC to AWS | N/A — runs natively in AWS, uses IAM roles directly (no OIDC needed) |
| Fit | Source + CI in one platform; mandated by the global `.github/workflows/` convention; most interview-familiar tool | Fine if the org already standardizes on GitLab | Adds an unaffiliated third-party platform for no added benefit here | Tightly AWS-coupled — less portable, less common outside AWS-only shops |

**Decision**: GitHub Actions — to keep cost near $0 (NFR1): the free-tier minutes comfortably cover this project's CI usage, with no separate platform/account to pay for.

**When an alternative is better**: if source already lives on GitLab (self-hosted or GitLab.com), GitLab CI avoids running a second platform. AWS CodePipeline/CodeBuild fits orgs that want the entire toolchain inside the AWS account boundary with no external SaaS dependency (common in regulated environments) — at the cost of GitHub Actions' portability and PR-based review ergonomics.

## 3. Pipeline Triggers Table

| Event | Triggered by | Jobs run | AWS changes? |
| --- | --- | --- | --- |
| `push` to `main` | Direct commit (no PR) | gitleaks, bandit, checkov, pip-audit, pytest (parallel) → package Lambda `.zip`s/layer → `terraform apply` (envs/dev) | Yes — `terraform apply` updates `envs/dev` |

Pushes to branches other than `main` do **not** trigger the workflow — keeps CI minutes low (§2.1's cost rationale). The exact `on:` trigger config appears in §7's full workflow YAML.

## 4. Stage Documentation

The 5 gates below run as independent parallel jobs on every `push` to `main` (§3). All paths reference doc03 §5.2's `src/` layout (`src/lambda_ingest/`, `src/lambda_triage/`, `src/lambda_insights/`, `src/layers/shared_utils/`) and `infra/` (doc04 §1.2).

### 4.1 Secret Scanning — gitleaks

**Purpose**: scans the full git history + working tree for hardcoded secrets (AWS access keys, private keys, API tokens) before they land in `main`. Given NFR4 (no AWS credentials stored anywhere — GitHub OIDC only), any hit here means that guarantee has already been violated — highest-severity possible finding.

**Failure behavior**: any finding → non-zero exit → fails the workflow run, blocking `terraform apply` (§4.7). No baseline/allowlist — greenfield repo, nothing to grandfather in.

```yaml
  gitleaks:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0   # full history, so gitleaks scans every commit
      - uses: gitleaks/gitleaks-action@v2
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

### 4.2 Python SAST — bandit

**Purpose**: static analysis of `src/` (all 3 Lambda handlers + shared-utils layer) for common Python security anti-patterns — unsafe deserialization, `subprocess(shell=True)`, weak crypto, etc. Particularly relevant for Lambda#2/#3, which build Bedrock prompts from user-controlled email content and parse Bedrock's JSON responses.

**Failure behavior**: `bandit -r src/ -ll` — `-ll` reports MEDIUM and HIGH severity only (suppresses LOW-severity informational noise). Any MEDIUM+ finding → non-zero exit → fails the workflow run, blocking `terraform apply` (§4.7).

```yaml
  bandit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
      - run: pip install bandit
      - run: bandit -r src/ -ll
```

### 4.3 IaC Security Scan — checkov

**Purpose**: static analysis of `infra/modules/` and `infra/envs/` against Terraform security/best-practice benchmarks — catches issues like a bucket missing Block Public Access, or an IAM policy with an unintentional `Resource: "*"`.

**Failure behavior**: `checkov -d infra/` fails on any FAILED check by default. doc03 §6 documents 2 AWS-imposed wildcards (Comprehend `DetectPiiEntities`, X-Ray `Put*`) — the corresponding checkov IAM-wildcard checks will need inline `#checkov:skip=<CHECK_ID>` comments citing that doc03 §6 justification (exact check IDs determined once checkov runs against the real policy JSON during implementation). No other suppressions expected.

```yaml
  checkov:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: bridgecrewio/checkov-action@master
        with:
          directory: infra/
          framework: terraform
```

### 4.4 Dependency Scan — pip-audit

**Purpose**: scans the shared-utils layer's pinned dependencies (`src/layers/shared_utils/requirements.txt` — boto3/botocore per doc03 §5.1) against the PyPA Advisory Database + OSV for known CVEs before they're packaged into the Lambda layer.

**Failure behavior**: `pip-audit -r src/layers/shared_utils/requirements.txt` — any known vulnerability → non-zero exit → fails the workflow run, blocking `terraform apply` (§4.7). No `--ignore-vuln` suppressions expected for a layer with only one or two pinned dependencies.

```yaml
  pip-audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
      - run: pip install pip-audit
      - run: pip-audit -r src/layers/shared_utils/requirements.txt
```

### 4.5 Unit Tests — pytest

**Purpose**: runs the TDD test suite for all 3 Lambda handlers + shared-utils layer — tests live in a top-level `tests/` tree mirroring `src/` (doc06 Phase 1), so test files aren't bundled into the Lambda `.zip`/layer artifacts by §4.6's packaging step. This is the same suite Mike runs locally during Red → Green → Refactor (doc08). AWS calls are mocked via moto (`@mock_aws`), so no real AWS credentials or resources are needed in CI. This is the gate that verifies handler logic (PII-redaction branching, retry/backoff, idempotency guard, DynamoDB writes, SNS filter attributes, etc.) before that code is packaged and deployed.

**Failure behavior**: `pytest tests/` — any failing test (or coverage-threshold miss, per doc08's pytest guide) → non-zero exit → fails the workflow run, blocking `terraform apply` (§4.7). No skips/xfails expected in a greenfield repo.

```yaml
  pytest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
      - run: pip install -r src/layers/shared_utils/requirements.txt -r requirements-dev.txt
      - run: pytest tests/
```

`requirements-dev.txt` (pytest, moto, coverage, etc.) is defined in doc08.

### 4.6 Package Lambda Artifacts

**Purpose**: builds the `.zip` files that `infra/envs/dev`'s `lambda` module reads from `lambda_artifacts_dir` (doc04 §6, `= "../../build"` — i.e. `<repo-root>/build/`): `shared_utils_layer.zip` plus one zip per function (`lambda_ingest.zip`, `lambda_triage.zip`, `lambda_insights.zip`, per doc03 §5.2's `src/` layout). `terraform apply` (§4.7) needs these files on disk to compute each function's `source_code_hash` via `filebase64sha256()`.

The shared-utils layer follows the Lambda Python layer convention: dependencies and shared modules are placed under a top-level `python/` directory in the zip, which Lambda extracts to `/opt/python` (added to `sys.path`) — so `retry_config.py` becomes importable as `import retry_config` from any function that attaches the layer.

**Failure behavior**: depends on `gitleaks`, `bandit`, `checkov`, `pip-audit`, `pytest` all passing (§1). Any packaging step failing (e.g. `pip install` error) blocks the downstream `terraform apply` job (§4.7) — no partial artifact set is uploaded.

```yaml
  package:
    runs-on: ubuntu-latest
    needs: [gitleaks, bandit, checkov, pip-audit, pytest]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"

      - name: Package shared-utils layer
        run: |
          mkdir -p build/layer/python
          pip install -r src/layers/shared_utils/requirements.txt -t build/layer/python
          cp src/layers/shared_utils/*.py build/layer/python/
          cd build/layer && zip -r ../shared_utils_layer.zip python

      - name: Package Lambda function code
        run: |
          for fn in lambda_ingest lambda_triage lambda_insights; do
            (cd src/$fn && zip -r ../../build/${fn}.zip .)
          done

      - uses: actions/upload-artifact@v4
        with:
          name: lambda-build
          path: build/
          retention-days: 1
```

### 4.7 Terraform Apply

**Purpose**: applies `infra/envs/dev` against AWS using the S3 backend with native `use_lockfile` locking (doc04 §7.1) and the GitHub OIDC role (§5) — the only step that actually changes AWS resources. Runs on every `push` to `main` (§3). `terraform apply` prints its plan inline before applying, so the workflow log itself is the audit trail — no separate plan stage or PR comment needed.

**Failure behavior**: any `terraform init`/`apply` error → non-zero exit → failed workflow run. Because the S3 backend uses `use_lockfile = true` (doc04 §7.1), a concurrent run holding the lock causes this step to wait/fail rather than corrupt state — acceptable at demo scale (single contributor, low concurrency).

```yaml
  terraform-apply:
    runs-on: ubuntu-latest
    needs: package
    permissions:
      id-token: write       # required for GitHub OIDC -> AWS (§5)
      contents: read
    steps:
      - uses: actions/checkout@v4
      - uses: actions/download-artifact@v4
        with:
          name: lambda-build
          path: build/

      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_CI_ROLE_ARN }}   # §5
          aws-region: us-east-1

      - uses: hashicorp/setup-terraform@v3
        with:
          terraform_version: "1.10.x"   # required for use_lockfile (doc04 §7)

      - name: terraform init
        working-directory: infra/envs/dev
        run: terraform init

      - name: terraform apply
        working-directory: infra/envs/dev
        run: terraform apply -auto-approve
```

## 5. GitHub OIDC Authentication

### 5.1 How It Works

`aws-actions/configure-aws-credentials@v4` (used in §4.7) requests a short-lived JWT from GitHub's own OIDC provider (`token.actions.githubusercontent.com`), scoped to the running workflow/job. It exchanges that JWT for temporary AWS credentials via `sts:AssumeRoleWithWebIdentity`, against an IAM role (`ECHOGitHubActionsRole`) whose trust policy (§5.3) only accepts tokens issued for this repo. STS validates the JWT's signature against an **IAM OIDC Identity Provider** (§5.2) registered for `token.actions.githubusercontent.com` — no AWS access key/secret is ever stored as a GitHub secret (NFR4). The resulting credentials are short-lived (default 1 hour) and scoped to `ECHOGitHubActionsRole`'s permissions policy (§5.4).

`secrets.AWS_CI_ROLE_ARN` (§4.7) holds only the role's ARN — not a credential — kept as a repo secret purely so the account ID isn't hardcoded into committed YAML.

### 5.2 IAM OIDC Identity Provider

```hcl
data "tls_certificate" "github_oidc" {
  url = "https://token.actions.githubusercontent.com"
}

resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.github_oidc.certificates[0].sha1_fingerprint]
}
```

Using `data.tls_certificate` to derive the thumbprint (rather than hardcoding GitHub's current cert fingerprint) avoids the provider silently breaking when GitHub rotates its TLS certificate.

### 5.3 Trust Policy — `ECHOGitHubActionsRole`

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::<ACCOUNT_ID>:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
          "token.actions.githubusercontent.com:sub": "repo:<GH_ORG>/<GH_REPO>:ref:refs/heads/main"
        }
      }
    }
  ]
}
```

A `push` to `main` (§4.7's terraform-apply, the only trigger per §3) produces a `sub` claim of `repo:<GH_ORG>/<GH_REPO>:ref:refs/heads/main` — the exact, single value this trust policy accepts. No other branch, fork, PR, or ref can assume this role.

### 5.4 Permissions Policy — `ECHOGitHubActionsRole`

This is the **Terraform deployer** role — broader than any of doc03 §6's Lambda execution-role policies, since it must create/update/delete every resource across all 12 modules (doc04 §1.1). Scoped by literal resource names where doc04 §2 fixes them (SQS/SNS/Lambda use the `email-*` naming from doc03 §6), or by the `echo-*`/`ECHO*` naming convention (S3 buckets, IAM roles) wherever AWS supports resource-level ARNs; account/region-level singletons (CloudTrail, Config, GuardDuty, Security Hub — doc04 §1.3) can't be name-scoped and are necessarily broader.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "TerraformState",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"],
      "Resource": [
        "arn:aws:s3:::echo-terraform-state-<ACCOUNT_ID>",
        "arn:aws:s3:::echo-terraform-state-<ACCOUNT_ID>/*"
      ]
      // doc04 §7: read/write the state object + the use_lockfile lockfile, both under this one bucket
    },
    {
      "Sid": "ProjectS3Buckets",
      "Effect": "Allow",
      "Action": "s3:*",
      "Resource": ["arn:aws:s3:::echo-*", "arn:aws:s3:::echo-*/*"]
      // raw-emails, cloudtrail-logs, config-logs (doc04 §2) - s3:* is broad, but confined to echo-* bucket names only
    },
    {
      "Sid": "DynamoDBTable",
      "Effect": "Allow",
      "Action": "dynamodb:*",
      "Resource": "arn:aws:dynamodb:us-east-1:<ACCOUNT_ID>:table/EmailTriageResults-${var.env}"
      // single named table - full table-management + the demo-data module's seed-item writes
    },
    {
      "Sid": "LambdaAndLayers",
      "Effect": "Allow",
      "Action": "lambda:*",
      "Resource": [
        "arn:aws:lambda:us-east-1:<ACCOUNT_ID>:function:email-ingest",
        "arn:aws:lambda:us-east-1:<ACCOUNT_ID>:function:email-triage",
        "arn:aws:lambda:us-east-1:<ACCOUNT_ID>:function:email-insights",
        "arn:aws:lambda:us-east-1:<ACCOUNT_ID>:layer:shared-utils",
        "arn:aws:lambda:us-east-1:<ACCOUNT_ID>:layer:shared-utils:*"
      ]
      // 3 function names per doc03 §6.1-6.3; single shared-utils layer (doc04 §2 row 13)
    },
    {
      "Sid": "SQSAndSNS",
      "Effect": "Allow",
      "Action": ["sqs:*", "sns:*"],
      "Resource": [
        "arn:aws:sqs:us-east-1:<ACCOUNT_ID>:email-triage-queue",
        "arn:aws:sqs:us-east-1:<ACCOUNT_ID>:email-triage-dlq",
        "arn:aws:sns:us-east-1:<ACCOUNT_ID>:alert-topic",
        "arn:aws:sns:us-east-1:<ACCOUNT_ID>:ops-alarms"
      ]
      // main queue + DLQ, alert + ops-alarms topics - literal names per doc04 §2 rows 3-4
    },
    {
      "Sid": "SES",
      "Effect": "Allow",
      "Action": "ses:*",
      "Resource": "*"
      // SES receipt rules/rule sets aren't individually ARN-addressable for IAM purposes - account/region-scoped only
    },
    {
      "Sid": "APIGateway",
      "Effect": "Allow",
      "Action": "apigateway:*",
      "Resource": "arn:aws:apigateway:us-east-1::/restapis/*"
      // API ID is generated at create time, so it can't be pre-scoped by name - bounded to this region's REST APIs
    },
    {
      "Sid": "CloudWatchAndLogs",
      "Effect": "Allow",
      "Action": ["cloudwatch:*", "logs:*"],
      "Resource": "*"
      // dashboards/alarms/anomaly detectors + the 3 Lambdas' log groups and EMF metrics - CloudWatch sub-services have inconsistent ARN support, so scoped only by account/region
    },
    {
      "Sid": "CloudTrailAndConfig",
      "Effect": "Allow",
      "Action": ["cloudtrail:*", "config:*"],
      "Resource": "*"
      // account/region-level singletons (NFR4) - not name-addressable
    },
    {
      "Sid": "SecurityBaseline",
      "Effect": "Allow",
      "Action": ["guardduty:*", "securityhub:*"],
      "Resource": "*"
      // GuardDuty detector + Security Hub subscription are account/region singletons - one reason envs/prod can't be applied alongside envs/dev (doc04 §1.3)
    },
    {
      "Sid": "IAMForEchoRoles",
      "Effect": "Allow",
      "Action": "iam:*",
      "Resource": [
        "arn:aws:iam::<ACCOUNT_ID>:role/ECHO*",
        "arn:aws:iam::<ACCOUNT_ID>:policy/ECHO*",
        "arn:aws:iam::<ACCOUNT_ID>:oidc-provider/token.actions.githubusercontent.com"
      ]
      // manages the 3 Lambda execution roles + ECHOInsightsCaller + this role itself + the OIDC provider (§5.2) - all under the ECHO* naming convention
    },
    {
      "Sid": "PassRoleToLambda",
      "Effect": "Allow",
      "Action": "iam:PassRole",
      "Resource": "arn:aws:iam::<ACCOUNT_ID>:role/ECHO*",
      "Condition": {
        "StringEquals": { "iam:PassedToService": "lambda.amazonaws.com" }
      }
      // required for Terraform to attach an execution role to a Lambda function
    }
  ]
}
```

### 5.5 Bootstrapping

The OIDC provider and `ECHOGitHubActionsRole` are themselves Terraform-managed (in the `iam` module, alongside the 3 Lambda execution roles — doc04 §1.1). This creates the same chicken-and-egg problem as doc04 §7's state bucket: the **first** `terraform apply` that creates this role can't yet authenticate *as* this role.

Resolution: the first `terraform apply` for `envs/dev` runs with Mike's local AWS credentials (`aws configure`), not CI. This is bootstrap prerequisite #2, alongside doc04 §7's S3 state bucket (#1) — both documented as one-time setup steps in `06-development-plan.md`'s runbook, alongside the SES MX record. After that first apply:

- `ECHOGitHubActionsRole`'s ARN (an `envs/dev` output) is copied into the `AWS_CI_ROLE_ARN` GitHub repo secret
- All subsequent `terraform apply` runs — from CI (§4.7) or locally — can proceed normally, including future changes to the `iam` module itself

**Caveat**: because `ECHOGitHubActionsRole` can modify its own trust/permissions policy (§5.4's `IAMForEchoRoles` statement), a change that accidentally removes its `sts:AssumeRoleWithWebIdentity` trust (§5.3) would lock CI out — recovery would require re-running the bootstrap apply locally. Low risk at demo scale (single contributor, infrequent `iam` module changes), but worth noting as the trade-off for a fully Terraform-managed CI identity.

---

## 6. Branch Protection Rules

### 6.1 What Branch Protection Can (and Can't) Do Here

Since commits land directly on `main` (§1 — no PR-based merge gate), the traditional "required status checks before merging" branch-protection model doesn't apply: status checks are computed *after* a commit already exists, so they can't block a direct push from landing. The real deploy gate is CI's `needs:` dependency graph (§4) — `terraform apply` (§4.7) only runs once all 5 gates (§4.1-4.5) and packaging (§4.6) succeed; a failing commit can still land on `main`, it just won't be deployed.

What branch protection *can* do here is protect `main`'s history and existence — which matters because `infra/envs/dev`'s remote state (doc04 §7.1) and every `terraform apply` run are tied to whatever commit is currently HEAD on `main`.

### 6.2 Configured Settings

| Setting | Value | Why |
| --- | --- | --- |
| Require a pull request before merging | Off | This demo commits directly to `main` (§1) |
| Require status checks to pass before merging | N/A | No merge step to gate — CI's `needs:` graph (§4) is the real per-push gate (§6.1) |
| Restrict force pushes | On | Rewriting `main`'s history would desync it from the S3-backed Terraform state (doc04 §7.1) and CI's run history |
| Restrict deletions | On | Prevents accidental deletion of `main` |
| Require signed commits | Off | Out of scope for a demo (NFR1) |
| Include administrators | Off | Solo project — Mike can bypass force-push/deletion protection in a genuine emergency; the rules still guard against an accidental `git push --force` from a misconfigured local setup |

### 6.3 Setup

Configured once via the repo's **Settings → Rules → Rulesets** (or classic **Settings → Branches → Branch protection rules**) — a one-time manual GitHub repo setting, documented in `06-development-plan.md`'s runbook alongside the AWS bootstrap steps (doc04 §7, §5.5). Not Terraform-managed — branch protection is a GitHub repo setting, outside `infra/`'s AWS-focused scope.

## 7. Full Workflow YAML

`.github/workflows/deploy.yml` — assembles every job from §4 into one workflow, triggered by §3's single `push`-to-`main` event. Two additions beyond a literal copy-paste of §4/§5's snippets:

- **Top-level `permissions: contents: read`** — least-privilege default for the `GITHUB_TOKEN` (NFR4); `terraform-apply` overrides this with `id-token: write` where it needs OIDC (§5).
- **`concurrency:` group** — §4.7 notes that a concurrent run holding the S3 lock causes `terraform apply` to wait/fail. Grouping by `${{ github.workflow }}-${{ github.ref }}` with `cancel-in-progress: false` queues back-to-back pushes to `main` instead of letting them race for the lock.

```yaml
name: ECHO CI/CD

on:
  push:
    branches: [main]

permissions:
  contents: read

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: false   # queue runs rather than racing for the S3 state lock (doc04 §7.1)

jobs:
  gitleaks:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0   # full history, so gitleaks scans every commit
      - uses: gitleaks/gitleaks-action@v2
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}

  bandit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
      - run: pip install bandit
      - run: bandit -r src/ -ll

  checkov:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: bridgecrewio/checkov-action@master
        with:
          directory: infra/
          framework: terraform

  pip-audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
      - run: pip install pip-audit
      - run: pip-audit -r src/layers/shared_utils/requirements.txt

  pytest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
      - run: pip install -r src/layers/shared_utils/requirements.txt -r requirements-dev.txt
      - run: pytest tests/

  package:
    runs-on: ubuntu-latest
    needs: [gitleaks, bandit, checkov, pip-audit, pytest]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"

      - name: Package shared-utils layer
        run: |
          mkdir -p build/layer/python
          pip install -r src/layers/shared_utils/requirements.txt -t build/layer/python
          cp src/layers/shared_utils/*.py build/layer/python/
          cd build/layer && zip -r ../shared_utils_layer.zip python

      - name: Package Lambda function code
        run: |
          for fn in lambda_ingest lambda_triage lambda_insights; do
            (cd src/$fn && zip -r ../../build/${fn}.zip .)
          done

      - uses: actions/upload-artifact@v4
        with:
          name: lambda-build
          path: build/
          retention-days: 1

  terraform-apply:
    runs-on: ubuntu-latest
    needs: package
    permissions:
      id-token: write       # required for GitHub OIDC -> AWS (§5)
      contents: read
    steps:
      - uses: actions/checkout@v4
      - uses: actions/download-artifact@v4
        with:
          name: lambda-build
          path: build/

      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_CI_ROLE_ARN }}   # §5
          aws-region: us-east-1

      - uses: hashicorp/setup-terraform@v3
        with:
          terraform_version: "1.10.x"   # required for use_lockfile (doc04 §7)

      - name: terraform init
        working-directory: infra/envs/dev
        run: terraform init

      - name: terraform apply
        working-directory: infra/envs/dev
        run: terraform apply -auto-approve
```
