from botocore.config import Config

from retry_config import GENERAL_CONFIG, BEDROCK_CONFIG


def test_general_config_is_config_instance():
    assert isinstance(GENERAL_CONFIG, Config)


def test_general_config_retries():
    assert GENERAL_CONFIG.retries == {"max_attempts": 3, "mode": "adaptive"}


def test_general_config_timeouts():
    assert GENERAL_CONFIG.connect_timeout == 3
    assert GENERAL_CONFIG.read_timeout == 5


def test_bedrock_config_is_config_instance():
    assert isinstance(BEDROCK_CONFIG, Config)


def test_bedrock_config_retries():
    assert BEDROCK_CONFIG.retries == {"max_attempts": 3, "mode": "adaptive"}


def test_bedrock_config_timeouts():
    assert BEDROCK_CONFIG.connect_timeout == 3
    assert BEDROCK_CONFIG.read_timeout == 10


def test_general_and_bedrock_read_timeouts_differ():
    assert GENERAL_CONFIG.read_timeout != BEDROCK_CONFIG.read_timeout