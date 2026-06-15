from botocore.config import Config

GENERAL_CONFIG = Config(
    retries={"max_attempts": 3, "mode": "adaptive"}, connect_timeout=3, read_timeout=5
)

BEDROCK_CONFIG = Config(
    retries={"max_attempts": 3, "mode": "adaptive"}, connect_timeout=3, read_timeout=10
)
