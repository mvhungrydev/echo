# 04 - Infrastructure Spec

> **ECHO** (Email Classification & Handling Orchestrator) — an automated email triage, classification, and insights pipeline.

> Status: Sections 1-7 confirmed/locked. `docs/04-infrastructure-spec.md` complete.

## 1. Terraform Module Structure & `envs/` Pattern

### 1.1 Module Breakdown

Twelve modules, named after the AWS service (or tightly-coupled service pair) they own — mirrors doc02's "AWS service breadth" differentiation story and keeps the resource-inventory table close to a 1:1 module↔service mapping. `iam` holds the 3 **Lambda execution roles** plus the **GitHub OIDC provider and `ECHOGitHubActionsRole`** — the CI/CD deployer role that lets GitHub Actions run `terraform apply` (doc05 §5); resource-based permissions and `ECHOInsightsCaller` live with the module that "owns" the trigger relationship (see note below) to avoid a circular dependency.

| Module              | Covers (doc03 ref)                                                                                                                         |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `s3`                | Raw-emails bucket: SSE-S3, Block Public Access, 90-day lifecycle, SES bucket policy (§8.1)                                                 |
| `ses`               | Active receipt rule set + rule (§8.2)                                                                                                      |
| `sqs`               | `email-triage-queue` + `email-triage-dlq`, redrive policy (§8.3, §4.4)                                                                     |
| `sns`               | `alert-topic` (filter-policy subscriptions) + `ops-alarms` topic (§8.4)                                                                    |
| `dynamodb`          | `EmailTriageResults` table (§8.5)                                                                                                          |
| `iam`               | 3 Lambda execution roles, least-privilege (§6.1-6.3); GitHub OIDC provider + `ECHOGitHubActionsRole` CI/CD deployer role (doc05 §5)        |
| `lambda`            | Shared `shared-utils` layer + Lambda #1/#2/#3 functions, S3/SQS triggers (§5)                                                              |
| `apigateway`        | REST API `/insights`, `ECHOInsightsCaller` role + Lambda #3 invoke permission (§8.6, §6.5)                                                 |
| `cloudwatch`        | Dashboard, DLQ-depth alarm, anomaly detection, EMF namespace `ECHO`, Lambda #1 on-failure destination (§8.9, §5.5)                         |
| `cloudtrail`        | Single trail, S3 data-event logging scoped to raw-emails bucket (§8.9)                                                                     |
| `security-baseline` | GuardDuty, Security Hub, AWS Config (§8.9)                                                                                                 |
| `demo-data`         | Seeds synthetic `EmailTriageResults` records so `/insights` (FR12) has data immediately after `apply`, without waiting on real SES traffic |

Not included: `ecr` (Lambdas ship as `.zip`, python3.13/arm64 per doc03 §5 — no containers) and `ssm` (no SSM parameters in this design — see §4).

**Why `iam` only holds execution roles**: `ECHOInsightsCaller`'s permissions policy needs the API Gateway execution ARN, `apigateway` needs Lambda #3's ARN, and `lambda` needs execution-role ARNs from `iam`. If `iam` also owned `ECHOInsightsCaller` and the API→Lambda #3 invoke permission, that would create `iam → lambda → apigateway → iam`, a cycle. Instead: `iam` (execution roles only) → `lambda` → `apigateway` (creates `ECHOInsightsCaller` + the invoke permission itself, since its own `api_id` is available locally with no cross-module reference needed). Same logic applies to the S3→Lambda #1 invoke permission and event notification — both live in `lambda`, which has `s3`'s bucket id/arn as an input.

### 1.2 Directory Tree

Every module is exactly 3 files — `main.tf` (all resources for that module's scope), `variables.tf` (inputs), `outputs.tf` (exports, `# (none)` if there's nothing to export). No per-resource file splitting (e.g., no `lambda1-role.tf`, `dashboard.tf`, `logs-bucket.tf`) — multiple resource blocks for one module's scope all live together in its `main.tf`. All per-environment customization is values, not structure, and lives entirely in `envs/<env>/`.

```
infra/
├── modules/
│   │
│   ├── s3/
│   │   ├── main.tf          # raw-emails bucket: SSE-S3 (AES256), Block Public
│   │   │                       Access (all 4), versioning disabled, 90-day
│   │   │                       lifecycle expiration, bucket policy
│   │   │                       (ses.amazonaws.com PutObject, aws:SourceAccount)
│   │   ├── variables.tf     # env, region
│   │   └── outputs.tf        # bucket_id, bucket_arn, bucket_name
│   │
│   ├── ses/
│   │   ├── main.tf           # active receipt rule set + rule
│   │   │                       (recipient, S3 action → raw-emails/)
│   │   ├── variables.tf      # bucket_name (from s3), recipient_address
│   │   └── outputs.tf         # (none)
│   │
│   ├── sqs/
│   │   ├── main.tf            # email-triage-queue (100s visibility, SSE-SQS)
│   │   │                       + email-triage-dlq (14d retention),
│   │   │                       redrive policy maxReceiveCount=2
│   │   ├── variables.tf       # env, sqs_visibility_timeout, sqs_max_receive_count
│   │   └── outputs.tf          # queue_arn, queue_url, dlq_arn, dlq_url
│   │
│   ├── sns/
│   │   ├── main.tf             # alert-topic (urgent/needs_review filter-policy
│   │   │                       email subscriptions) + ops-alarms topic
│   │   │                       (single unfiltered subscription)
│   │   ├── variables.tf        # env, alert_email
│   │   └── outputs.tf           # alert_topic_arn, ops_alarms_topic_arn
│   │
│   ├── dynamodb/
│   │   ├── main.tf              # EmailTriageResults table: PK email_id,
│   │   │                       on-demand billing, TTL enabled
│   │   ├── variables.tf         # env
│   │   └── outputs.tf            # table_name, table_arn
│   │
│   ├── iam/
│   │   ├── main.tf              # 3 Lambda execution roles, least-privilege
│   │   │                       (doc03 §6.1-6.3): Lambda#1 ingest (S3
│   │   │                       GetObject raw-emails, SQS SendMessage
│   │   │                       triage-queue, X-Ray, Logs); Lambda#2 triage
│   │   │                       (SQS Receive/Delete/GetAttrs, DynamoDB
│   │   │                       GetItem/PutItem, SNS Publish alert-topic,
│   │   │                       Comprehend, Bedrock pinned, X-Ray, Logs);
│   │   │                       Lambda#3 insights (DynamoDB Scan, Bedrock
│   │   │                       pinned, X-Ray, Logs); GitHub OIDC provider
│   │   │                       (data.tls_certificate-derived thumbprint) +
│   │   │                       ECHOGitHubActionsRole, the CI/CD deployer
│   │   │                       role (trust scoped to repo:<GH_ORG>/<GH_REPO>
│   │   │                       :ref:refs/heads/main; 12-statement
│   │   │                       permissions policy — doc05 §5.2-5.4)
│   │   ├── variables.tf         # s3_bucket_arn, sqs_queue_arn,
│   │   │                       dynamodb_table_arn, sns_alert_topic_arn,
│   │   │                       github_org, github_repo, env, region
│   │   └── outputs.tf            # lambda1/2/3_role_arn,
│   │                              github_actions_role_arn
│   │
│   ├── lambda/
│   │   ├── main.tf               # shared-utils layer (retry_config.py only —
│   │   │                       GENERAL_CONFIG/BEDROCK_CONFIG, doc03 §5.2;
│   │   │                       MIME-parsing/PII-redaction/Bedrock-client code
│   │   │                       live per-function, not in this layer);
│   │   │                       Lambda#1 ingest (S3 event notification +
│   │   │                       invoke permission, uses s3 bucket_id/arn);
│   │   │                       Lambda#2 triage (SQS event source mapping,
│   │   │                       batch size 1); Lambda#3 insights (28s
│   │   │                       timeout, tightened Bedrock client config,
│   │   │                       §7.3)
│   │   ├── variables.tf          # lambda{1,2,3}_role_arn (from iam),
│   │   │                       s3_bucket_id/arn, sqs_queue_arn,
│   │   │                       dynamodb_table_name, sns_alert_topic_arn,
│   │   │                       env, region, lambda2_timeout, *_zip_path
│   │   └── outputs.tf             # layer_arn, lambda{1,2,3}_function_name/
│   │                              arn/invoke_arn
│   │
│   ├── apigateway/
│   │   ├── main.tf                # REST API v1, POST /insights, AWS_IAM
│   │   │                       auth, AWS_PROXY integration → lambda3, stage
│   │   │                       (X-Ray, access logging); apigateway → lambda3
│   │   │                       invoke permission; ECHOInsightsCaller role
│   │   │                       (trust = Mike's IAM user, permissions =
│   │   │                       execute-api:Invoke on this API's /insights
│   │   │                       only)
│   │   ├── variables.tf           # lambda3_invoke_arn/arn/function_name
│   │   │                       (from lambda), env, region, caller_iam_user_arn
│   │   └── outputs.tf              # api_endpoint, insights_caller_role_arn
│   │
│   ├── cloudwatch/
│   │   ├── main.tf                 # dashboard (FR14: pipeline-health +
│   │   │                       triage-metrics widget groups); DLQ-depth
│   │   │                       alarm; anomaly detector on EMF
│   │   │                       ECHO/SentimentCount{sentiment=negative}
│   │   │                       (FR15); Lambda#1 on-failure destination →
│   │   │                       ops-alarms topic (§5.5)
│   │   ├── variables.tf            # lambda{1,2,3}_function_name, dlq_arn,
│   │   │                       ops_alarms_topic_arn, env, region
│   │   └── outputs.tf               # (none)
│   │
│   ├── cloudtrail/
│   │   ├── main.tf                  # single trail (management events + S3
│   │   │                       data events scoped to raw-emails bucket) +
│   │   │                       dedicated cloudtrail-logs S3 bucket + bucket
│   │   │                       policy for cloudtrail.amazonaws.com
│   │   ├── variables.tf             # s3_bucket_arn (raw-emails, for data
│   │   │                       events), env, region
│   │   └── outputs.tf                # trail_arn
│   │
│   ├── security-baseline/
│   │   ├── main.tf                   # GuardDuty detector (S3 Protection);
│   │   │                       Security Hub subscription + CIS benchmark
│   │   │                       standard; AWS Config recorder + delivery
│   │   │                       channel; dedicated config-logs S3 bucket +
│   │   │                       bucket policy for config.amazonaws.com
│   │   ├── variables.tf              # env, region
│   │   └── outputs.tf                 # (none)
│   │
│   └── demo-data/
│       ├── main.tf                    # seeds ~10-15 synthetic
│       │                       EmailTriageResults items (review_status=
│       │                       auto_processed, varied category/urgency/
│       │                       sentiment/feature_tags) for /insights demo
│       ├── variables.tf               # dynamodb_table_name
│       └── outputs.tf                  # (none)
│
└── envs/
    ├── dev/
    │   ├── main.tf            # instantiates all 12 modules in dependency
    │   │                       order, wires outputs → inputs
    │   ├── backend.tf          # S3 backend, native locking (key=dev/terraform.tfstate)
    │   ├── variables.tf
    │   ├── terraform.tfvars.example
    │   └── outputs.tf           # api_endpoint, insights_caller_role_arn, etc.
    │
    └── prod/
        ├── main.tf            # same module calls as dev, prod-specific tfvars
        ├── backend.tf          # S3 backend, same bucket as dev, key=prod/terraform.tfstate
        ├── variables.tf
        ├── terraform.tfvars.example
        └── outputs.tf
```

### 1.3 Module Dependency Order & Key Outputs

`envs/dev/main.tf` instantiates modules in this order; each row's outputs feed the "consumed by" modules' inputs.

| #   | Module              | Key outputs                                             | Consumed by                                                                                                         |
| --- | ------------------- | ------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| 1   | `s3`                | `bucket_id`, `bucket_arn`, `bucket_name`                | `ses`, `iam`, `lambda`, `cloudtrail`                                                                                |
| 2   | `ses`               | —                                                       | (terminal)                                                                                                          |
| 3   | `sqs`               | `queue_arn`, `queue_url`, `dlq_arn`                     | `iam`, `lambda`, `cloudwatch`                                                                                       |
| 4   | `sns`               | `alert_topic_arn`, `ops_alarms_topic_arn`               | `iam` + `lambda` (alert_topic_arn only), `cloudwatch` (ops_alarms_topic_arn)                                        |
| 5   | `dynamodb`          | `table_name`, `table_arn`                               | `iam`, `lambda`, `apigateway`, `demo-data`                                                                          |
| 6   | `iam`               | `lambda1/2/3_role_arn`, `github_actions_role_arn`       | `lambda` (role ARNs); `github_actions_role_arn` is surfaced as an `envs/dev` output for doc05 §5.5's bootstrap step |
| 7   | `lambda`            | `layer_arn`, `lambda1/2/3_function_name/arn/invoke_arn` | `apigateway`, `cloudwatch`                                                                                          |
| 8   | `apigateway`        | `api_endpoint`, `insights_caller_role_arn`              | `cloudwatch` (optional, for dashboard)                                                                              |
| 9   | `cloudwatch`        | —                                                       | (terminal)                                                                                                          |
| 10  | `cloudtrail`        | —                                                       | (terminal)                                                                                                          |
| 11  | `security-baseline` | —                                                       | (terminal, independent)                                                                                             |
| 12  | `demo-data`         | —                                                       | (terminal)                                                                                                          |

**`modules/` vs `envs/` split**: every module is fully parameterized — no hardcoded bucket names, ARNs, account IDs, or environment names inside `modules/`. Each `envs/<env>/main.tf` is the only place that instantiates modules and supplies environment-specific values (region, retention periods, alarm email, etc.).

**Multi-env promotion**: for this project, **only `envs/dev` is actually deployed** for the interview demo — `us-east-1`, single AWS account, near-$0 budget (NFR1/NFR6). `envs/prod` exists to satisfy the standing `envs/` convention and demonstrate the pattern (e.g., what would change for a real prod env: `sqs_visibility_timeout=450` per the 6x guidance in doc03 §4.4, longer CloudWatch retention, an isolated state key — §7). It is **not deployed** — `security-baseline`'s resources (GuardDuty detector, Security Hub subscription, Config recorder) are account/region-level singletons, so applying both `envs/dev` and `envs/prod` to the same account would conflict on those resources. This caveat is noted directly in `envs/prod/main.tf` as a comment.

## 2. Resource Inventory Table

Every distinct AWS resource, grouped by owning module (§1.3 order). Where a single logical resource is backed by several Terraform resource blocks (e.g., an S3 bucket's encryption/versioning/lifecycle/policy sub-resources), the "+" notation lists the primary type plus supporting types.

| Resource                         | Terraform type(s)                                                                                                                           | Module              | Notable config                                                                                                                                                                          |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- | ------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `raw-emails` bucket              | `aws_s3_bucket` + `_server_side_encryption_configuration` + `_public_access_block` + `_versioning` + `_lifecycle_configuration` + `_policy` | `s3`                | SSE-S3 (AES256); Block Public Access all 4 on; versioning disabled; 90-day expiration; policy allows `ses.amazonaws.com` `PutObject` conditioned on `aws:SourceAccount`                 |
| Receipt rule set                 | `aws_ses_receipt_rule_set` + `aws_ses_active_receipt_rule_set`                                                                              | `ses`               | single active rule set                                                                                                                                                                  |
| Receipt rule                     | `aws_ses_receipt_rule`                                                                                                                      | `ses`               | recipient = address on Mike's domain; S3 action → `raw-emails/` prefix; spam/virus scan enabled                                                                                         |
| `email-triage-queue`             | `aws_sqs_queue`                                                                                                                             | `sqs`               | `visibility_timeout_seconds=100`; `sqs_managed_sse_enabled=true`; `redrive_policy` → DLQ, `maxReceiveCount=2`                                                                           |
| `email-triage-dlq`               | `aws_sqs_queue` + `aws_sqs_queue_redrive_allow_policy`                                                                                      | `sqs`               | `message_retention_seconds=1209600` (14d); `sqs_managed_sse_enabled=true`                                                                                                               |
| `alert-topic`                    | `aws_sns_topic` + `aws_sns_topic_subscription` ×2                                                                                           | `sns`               | filter policies: `alert_type=urgent`, `alert_type=needs_review` (doc03 §7.1)                                                                                                            |
| `ops-alarms` topic               | `aws_sns_topic` + `aws_sns_topic_subscription` ×1                                                                                           | `sns`               | single unfiltered email subscription                                                                                                                                                    |
| `EmailTriageResults` table       | `aws_dynamodb_table`                                                                                                                        | `dynamodb`          | PK `email_id` (S, no SK); `PAY_PER_REQUEST`; TTL enabled on `ttl` attribute                                                                                                             |
| Lambda #1 execution role         | `aws_iam_role` + `aws_iam_role_policy`                                                                                                      | `iam`               | S3 `GetObject` (raw-emails), SQS `SendMessage` (triage-queue), X-Ray `Put*`, Logs                                                                                                       |
| Lambda #2 execution role         | `aws_iam_role` + `aws_iam_role_policy`                                                                                                      | `iam`               | SQS `Receive/Delete/GetQueueAttributes`, DynamoDB `GetItem/PutItem`, SNS `Publish` (alert-topic), Comprehend `DetectPiiEntities` (`*`), Bedrock `InvokeModel` (pinned ARN), X-Ray, Logs |
| Lambda #3 execution role         | `aws_iam_role` + `aws_iam_role_policy`                                                                                                      | `iam`               | DynamoDB `Scan`, Bedrock `InvokeModel` (pinned ARN), X-Ray, Logs                                                                                                                        |
| GitHub OIDC provider             | `aws_iam_openid_connect_provider` + `data.tls_certificate`                                                                                  | `iam`               | provider for `token.actions.githubusercontent.com`; thumbprint derived via `data.tls_certificate` rather than hardcoded (doc05 §5.2)                                                    |
| `ECHOGitHubActionsRole`          | `aws_iam_role` + `aws_iam_role_policy`                                                                                                      | `iam`               | CI/CD deployer role; trust scoped to `repo:<GH_ORG>/<GH_REPO>:ref:refs/heads/main` (doc05 §5.3); 12-statement permissions policy spanning all 12 modules (doc05 §5.4)                   |
| `shared-utils` layer             | `aws_lambda_layer_version`                                                                                                                  | `lambda`            | `retry_config.py` only — `GENERAL_CONFIG`/`BEDROCK_CONFIG` (doc03 §5.2); MIME-parsing/PII-redaction/Bedrock-client code live per-function (doc03 §5.2); python3.13/arm64                |
| Lambda #1 (ingest)               | `aws_lambda_function` + `aws_s3_bucket_notification` + `aws_lambda_permission`                                                              | `lambda`            | S3 `ObjectCreated` trigger on raw-emails bucket; on-failure destination wired in `cloudwatch` (§5.5)                                                                                    |
| Lambda #2 (triage)               | `aws_lambda_function` + `aws_lambda_event_source_mapping`                                                                                   | `lambda`            | SQS trigger, batch size 1; timeout=75s                                                                                                                                                  |
| Lambda #3 (insights)             | `aws_lambda_function`                                                                                                                       | `lambda`            | timeout=28s (API Gateway 29s ceiling); tightened Bedrock client (§7.3)                                                                                                                  |
| REST API `/insights`             | `aws_api_gateway_rest_api` + `_resource` + `_method` + `_integration` + `_deployment` + `_stage`                                            | `apigateway`        | `AWS_IAM` auth; `AWS_PROXY` → Lambda #3; X-Ray + access logging on stage                                                                                                                |
| API Gateway account settings     | `aws_api_gateway_account`                                                                                                                   | `apigateway`        | sets CloudWatch Logs role ARN for access logging — **account/region-level singleton** (same caveat as `security-baseline`, see below)                                                   |
| Lambda #3 invoke permission      | `aws_lambda_permission`                                                                                                                     | `apigateway`        | `source_arn` scoped to this API's `/*/POST/insights`                                                                                                                                    |
| `ECHOInsightsCaller` role        | `aws_iam_role` + `aws_iam_role_policy`                                                                                                      | `apigateway`        | trust = Mike's IAM user (`sts:AssumeRole`); permissions = `execute-api:Invoke` on `/insights` only                                                                                      |
| Dashboard                        | `aws_cloudwatch_dashboard`                                                                                                                  | `cloudwatch`        | FR14, two widget groups (pipeline health + triage metrics)                                                                                                                              |
| DLQ-depth alarm                  | `aws_cloudwatch_metric_alarm`                                                                                                               | `cloudwatch`        | `ApproximateNumberOfMessagesVisible` on DLQ `> 0` → `ops-alarms`                                                                                                                        |
| Sentiment anomaly detector       | `aws_cloudwatch_metric_alarm` (anomaly detection band)                                                                                      | `cloudwatch`        | EMF `ECHO/SentimentCount{sentiment=negative}` (FR15) → `ops-alarms`                                                                                                                     |
| Lambda #1 on-failure destination | `aws_lambda_function_event_invoke_config`                                                                                                   | `cloudwatch`        | `destination_config.on_failure` → `ops-alarms` topic (§5.5)                                                                                                                             |
| CloudTrail trail                 | `aws_cloudtrail`                                                                                                                            | `cloudtrail`        | management events (all); S3 data-event logging scoped to raw-emails bucket only                                                                                                         |
| `cloudtrail-logs` bucket         | `aws_s3_bucket` + `_policy`                                                                                                                 | `cloudtrail`        | dedicated trail-log destination; policy grants `cloudtrail.amazonaws.com`                                                                                                               |
| GuardDuty detector               | `aws_guardduty_detector`                                                                                                                    | `security-baseline` | S3 Protection enabled                                                                                                                                                                   |
| Security Hub                     | `aws_securityhub_account` + `aws_securityhub_standards_subscription`                                                                        | `security-baseline` | CIS AWS Foundations Benchmark                                                                                                                                                           |
| AWS Config recorder              | `aws_config_configuration_recorder` + `_delivery_channel` + `_configuration_recorder_status`                                                | `security-baseline` | records all supported resource types                                                                                                                                                    |
| `config-logs` bucket             | `aws_s3_bucket` + `_policy`                                                                                                                 | `security-baseline` | dedicated Config delivery-channel destination; policy grants `config.amazonaws.com`                                                                                                     |
| Demo seed records                | `aws_dynamodb_table_item` ×~10-15                                                                                                           | `demo-data`         | synthetic `EmailTriageResults` rows, `review_status=auto_processed`, varied category/urgency/sentiment/feature_tags                                                                     |

### 2.1 New Findings From This Inventory Pass

Building this table surfaced a few items not previously decided in doc03 — flagging them here rather than burying them in the table:

1. **Two new S3 buckets** — `cloudtrail-logs` and `config-logs` — beyond the `raw-emails` bucket covered in doc03 §8.1. CloudTrail and AWS Config both require their own log-delivery bucket; doc03 §8.1 only specified the application-data bucket. **Decision**: each of `cloudtrail` and `security-baseline` creates its own small bucket (self-contained modules, no new cross-module dependency) rather than sharing one "audit-logs" bucket — the storage cost difference is negligible at demo scale.
2. **`aws_api_gateway_account`** is an account/region-level singleton (sets the CloudWatch Logs role for _all_ REST APIs in the account), same category as `security-baseline`'s resources. Reinforces the existing "`envs/prod` not deployed" decision from §1.3 — applying it twice in one account would conflict.
3. **SES MX record is a manual prerequisite, not a Terraform resource** — SES inbound receiving requires the domain's MX record to point at `inbound-smtp.us-east-1.amazonaws.com` (priority 10) at Mike's domain registrar. Since the registrar isn't necessarily Route53, this isn't modeled in Terraform; it's a one-time manual step to be documented as a runbook prerequisite in `06-development-plan.md`.

**Total**: ~32 distinct AWS resources (collapsing sub-resources) across 12 modules.

## 3. DynamoDB Schema

### 3.1 Table Definition (Terraform-facing)

DynamoDB is schemaless beyond its key — the `aws_dynamodb_table` resource in the `dynamodb` module only declares the partition key. All other attributes (§3.2) are written/read by application code (Lambda #2/#3) and never appear in Terraform.

```hcl
resource "aws_dynamodb_table" "email_triage_results" {
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
}
```

No sort key, no GSI/LSI — see §3.3 for why.

### 3.2 Application Schema (full attribute reference)

For reference when implementing Lambda #2 (writer) and Lambda #3 (reader) — restated from doc03 §8.5:

| Attribute                  | Type      | Written by | Notes                                          |
| -------------------------- | --------- | ---------- | ---------------------------------------------- |
| `email_id`                 | S (PK)    | Lambda #2  | SES `messageId`                                |
| `received_at`              | S         | Lambda #2  | ISO 8601                                       |
| `from_address`             | S         | Lambda #2  |                                                |
| `subject`                  | S         | Lambda #2  |                                                |
| `raw_s3_key`               | S         | Lambda #2  | passed through from Lambda #1 via SQS          |
| `category`                 | S         | Lambda #2  | `unclassified` on FR17 degraded record         |
| `urgency`                  | S         | Lambda #2  |                                                |
| `urgency_override_applied` | BOOL      | Lambda #2  | FR7 keyword override fired                     |
| `sentiment`                | S         | Lambda #2  | `unknown` on FR17 degraded record              |
| `confidence`               | S         | Lambda #2  | `low` on FR17 degraded record                  |
| `review_status`            | S         | Lambda #2  | `auto_processed` \| `needs_review`             |
| `suggested_reply`          | S \| NULL | Lambda #2  | `NULL` on FR17 degraded record                 |
| `feature_tags`             | L of S    | Lambda #2  | populated only when `category=feature_request` |
| `redacted_body`            | S         | Lambda #2  | email body after PII redaction; `NAME`/`EMAIL`/`PHONE` not redacted (see `PII_TYPES_TO_SKIP`) |
| `pii_entities_detected`    | N         | Lambda #2  | Comprehend redaction count                     |
| `processed_at`             | S         | Lambda #2  | ISO 8601                                       |
| `ttl`                      | N         | Lambda #2  | epoch seconds, `received_at + 90d`             |

### 3.3 Access Patterns

| #   | Pattern                     | Operation                                            | Used by           | Key / filter / projection                                                                                                                                                                            |
| --- | --------------------------- | ---------------------------------------------------- | ----------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Idempotency check           | `GetItem`                                            | Lambda #2 (start) | `email_id` = incoming SQS message's id — if found, short-circuit (§4 idempotency guard)                                                                                                              |
| 2   | Write classification result | `PutItem`                                            | Lambda #2 (end)   | full item, all attributes in §3.2                                                                                                                                                                    |
| 3   | `/insights` aggregate query | `Scan` + `FilterExpression` + `ProjectionExpression` | Lambda #3         | filter `review_status = auto_processed`; project only `category`, `urgency`, `sentiment`, `feature_tags`, `received_at` (data minimization — excludes `from_address`/`suggested_reply`/`raw_s3_key`) |

**Why no GSI**: pattern #1 is a PK lookup (no index needed). Pattern #3 is a single un-pre-filtered `Scan` — sufficient at demo scale (doc02 tooling decision #4) and explicitly out of scope to optimize with a GSI (doc01 §6, "Out of Scope"). A GSI on `review_status` would speed up #3 at higher record counts, but isn't justified here.

### 3.4 TTL

`ttl` (epoch seconds) = `received_at + 90 days`, computed by Lambda #2 at write time — mirrors the `raw-emails` S3 bucket's 90-day lifecycle expiration (doc03 §8.1), so the DynamoDB record and its corresponding raw `.eml` age out together.

## 4. SSM Parameter Store

**N/A** — no SSM parameters in this design.

- `retry_config.py` values stay hardcoded in the `shared-utils` layer (doc03 §4 decision) — not env-tunable knobs, so no parameter to store.
- Cross-resource values Lambdas need at runtime (DynamoDB table name, SNS topic ARN, SQS queue URL, Bedrock model ARN, layer ARN) are wired directly as Lambda environment variables by Terraform at deploy time (`lambda` module — see §1.2/§2) — no runtime lookup needed.
- Demo-facing values (API endpoint, `ECHOInsightsCaller` role ARN, DynamoDB table name) are exposed via `envs/dev/outputs.tf` (`terraform output`), which is sufficient since Mike runs the demo from the same Terraform working directory.

## 5. ECR Config

**N/A** — no ECR repositories in this design.

## 6. Key Terraform Variables

Declared in `envs/<env>/variables.tf`, supplied per-environment via `terraform.tfvars` (gitignored — `terraform.tfvars.example` is the committed template, per the global key rules).

| Variable                 | Type     | Default                                    | Description                                                                                                                                                         |
| ------------------------ | -------- | ------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `env`                    | `string` | `"dev"`                                    | Environment name; used in resource naming/tags across all 12 modules                                                                                                |
| `region`                 | `string` | `"us-east-1"`                              | AWS region — fixed per NFR6 (SES inbound + Bedrock availability); still a variable for explicitness                                                                 |
| `alert_email`            | `string` | — (required)                               | Email address subscribed to `alert-topic` (urgent + needs_review filter policies) and `ops-alarms`                                                                  |
| `ses_recipient_address`  | `string` | — (required)                               | Inbound address on Mike's domain that the SES receipt rule matches (doc03 §8.2)                                                                                     |
| `caller_iam_user_arn`    | `string` | — (required)                               | ARN of Mike's IAM user — trust-policy principal for `ECHOInsightsCaller` (doc03 §6.5)                                                                               |
| `github_org`             | `string` | — (required)                               | GitHub org/user owning the ECHO repo — used in `ECHOGitHubActionsRole`'s trust policy `sub` condition (doc05 §5.3)                                                  |
| `github_repo`            | `string` | — (required)                               | GitHub repo name — used alongside `github_org` in the same trust policy condition (doc05 §5.3)                                                                      |
| `sqs_visibility_timeout` | `number` | `100`                                      | SQS visibility timeout (seconds); demo=100, documented prod value=450 (doc03 §4.4)                                                                                  |
| `sqs_max_receive_count`  | `number` | `2`                                        | `maxReceiveCount` before DLQ redrive (doc03 §4.4)                                                                                                                   |
| `lambda2_timeout`        | `number` | `75`                                       | Lambda #2 function timeout (seconds); kept alongside `sqs_visibility_timeout` so the "visibility ≥ function timeout" relationship (doc03 §4.4) is adjusted together |
| `bedrock_model_id`       | `string` | `"anthropic.claude-3-haiku-20240307-v1:0"` | Pinned Bedrock model — builds both the `iam` module's resource ARN and the `lambda` module's env vars from one source, keeping them in sync                         |
| `lambda_artifacts_dir`   | `string` | `"../../build"`                            | Path to built `.zip` artifacts (`ingest.zip`, `triage.zip`, `insights.zip`, `shared_utils_layer.zip`) — produced by doc05's CI/CD packaging stage                   |
| `demo_seed_data_file`    | `string` | `"./seed-data/email_triage_results.json"`  | Path to synthetic `EmailTriageResults` records loaded by the `demo-data` module                                                                                     |

**Everything else is hardcoded**, per the parameter-location decisions already made in doc03 §4: Lambda memory sizes (256/512/256 MB) and Lambda #1/#3 timeouts (45s/28s — §3.1's table), DLQ retention (14 days), DLQ-depth alarm threshold (`>0`), and all `retry_config.py` values. None of these have meaningful per-env variance, and `lambda3_timeout=28` in particular is deliberately _not_ tunable — it's mathematically derived from API Gateway's fixed 29s integration ceiling (doc03 §5.4), and exposing it as a variable would invite a value that breaks that guarantee.

## 7. Terraform State Strategy

Backend config is a top-level `terraform { backend ... }` block in each `envs/<env>/backend.tf` — separate from the resources in `modules/`.

Both `envs/dev` and `envs/prod` use the **S3 backend with Terraform's native state locking** (`use_lockfile = true`, Terraform ≥1.10 — locking via S3 conditional writes, no DynamoDB table needed). Same bucket, different state key per env.

### 7.1 `envs/dev` — S3 Backend (actually used)

```hcl
# envs/dev/backend.tf
terraform {
  backend "s3" {
    bucket       = "echo-terraform-state-<ACCOUNT_ID>"
    key          = "dev/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}
```

A remote backend is required here, not just convention: GitHub Actions runners (doc05) are ephemeral, so `terraform apply` in CI can't persist a local `terraform.tfstate` between runs. S3 is the shared state store between CI and Mike's local machine.

`.terraform/` is gitignored (per the global Python/Terraform `.gitignore`). `.terraform.lock.hcl` **is** committed, per the standing convention. With a remote backend, no `terraform.tfstate*` files exist locally — there's nothing state-related left to gitignore beyond `.terraform/`.

### 7.2 `envs/prod` — S3 Backend (documented, not deployed)

```hcl
# envs/prod/backend.tf
terraform {
  backend "s3" {
    bucket       = "echo-terraform-state-<ACCOUNT_ID>"
    key          = "prod/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}
```

Identical to §7.1 except the state `key` — same bucket, isolated state file. Consistent with §1.3's "`envs/prod` exists to demonstrate the pattern, not deployed" decision.

**Bootstrapping note**: the S3 bucket must exist _before_ `terraform init` can use it as a backend — it can't be created by the same Terraform run that depends on it. This is a one-time manual/CLI step (`aws s3 mb`, enable versioning + default encryption) and is a real prerequisite for `envs/dev` (since it's the env that's actually deployed) — documented as a setup step in `06-development-plan.md` alongside the SES MX record (doc04 §2.1, item 3).
