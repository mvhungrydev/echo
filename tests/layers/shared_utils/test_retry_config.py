from botocore.config import Config

from retry_config import GENERAL_CONFIG, BEDROCK_CONFIG


def test_general_config_is_config_instance():
    assert isinstance(GENERAL_CONFIG, Config)


def test_general_config_retries():
    # botocore resolves max_attempts=3 to total_max_attempts=4 (initial + 3 retries)
    assert GENERAL_CONFIG.retries["mode"] == "adaptive"
    assert GENERAL_CONFIG.retries["total_max_attempts"] == 4


def test_general_config_timeouts():
    assert GENERAL_CONFIG.connect_timeout == 3
    assert GENERAL_CONFIG.read_timeout == 5


def test_bedrock_config_is_config_instance():
    assert isinstance(BEDROCK_CONFIG, Config)


def test_bedrock_config_retries():
    # botocore resolves max_attempts=3 to total_max_attempts=4 (initial + 3 retries)
    assert BEDROCK_CONFIG.retries["mode"] == "adaptive"
    assert BEDROCK_CONFIG.retries["total_max_attempts"] == 4


def test_bedrock_config_timeouts():
    assert BEDROCK_CONFIG.connect_timeout == 3
    assert BEDROCK_CONFIG.read_timeout == 10


def test_general_and_bedrock_read_timeouts_differ():
    assert GENERAL_CONFIG.read_timeout != BEDROCK_CONFIG.read_timeout