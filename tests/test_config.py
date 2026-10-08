from pickled.config import Settings


def test_settings_reads_api_key_from_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    assert Settings(_env_file=None).anthropic_api_key.get_secret_value() == "test-key"
