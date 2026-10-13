from decimal import Decimal

from pickled.config import Settings


def test_settings_reads_runware_key_and_database_url_from_env(monkeypatch):
    monkeypatch.setenv("RUNWARE_API_KEY", "test-key")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db:5432/x")

    settings = Settings(_env_file=None)

    assert settings.runware_api_key.get_secret_value() == "test-key"
    assert settings.database_url == "postgresql+psycopg://u:p@db:5432/x"


def test_settings_defaults_match_the_spec(monkeypatch):
    for name in ["DATABASE_URL", "RUNWARE_API_KEY", "RUNWARE_BASE_URL"]:
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=None)

    assert settings.chat_model == "claude-sonnet-5-5"
    assert settings.draft_model == "claude-sonnet-5-5"
    assert settings.match_model == "claude-sonnet-5-5"
    assert settings.judge_model == "claude-sonnet-5-5"
    assert settings.llm_timeout_seconds == 120
    assert settings.llm_max_retries == 2
    assert settings.llm_monthly_cap_usd == Decimal("25")
    assert settings.llm_min_balance_usd == Decimal("5")


def test_pickled_prefixed_settings_read_from_env(monkeypatch):
    monkeypatch.setenv("PICKLED_CHAT_MODEL", "claude-opus-5-5")
    monkeypatch.setenv("PICKLED_LLM_MONTHLY_CAP_USD", "40.50")

    settings = Settings(_env_file=None)

    assert settings.chat_model == "claude-opus-5-5"
    assert settings.llm_monthly_cap_usd == Decimal("40.50")
