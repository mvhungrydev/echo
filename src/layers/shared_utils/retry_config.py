from botocore.config import Config

# doc03 §4.2 — shared retry config for all AWS SDK calls across all Lambdas.
# "adaptive" mode adds client-side rate limiting on top of standard exponential backoff.
# Hardcoded (not SSM) because the same values apply in every environment.

# S3, SQS, SNS, DynamoDB, Comprehend — 5s read timeout is sufficient for these APIs
GENERAL_CONFIG = Config(
    retries={"max_attempts": 3, "mode": "adaptive"}, connect_timeout=3, read_timeout=5
)

# Bedrock needs a longer read timeout (10s) because model inference takes more time
BEDROCK_CONFIG = Config(
    retries={"max_attempts": 3, "mode": "adaptive"}, connect_timeout=3, read_timeout=10
)
