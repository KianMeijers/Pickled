from decimal import Decimal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App settings, read from environment variables or the .env file."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = Field(
        "postgresql+psycopg://pickled:pickled@localhost:5432/pickled",
        validation_alias="DATABASE_URL",
    )

    runware_api_key: SecretStr = Field(SecretStr(""), validation_alias="RUNWARE_API_KEY")
    runware_base_url: str = Field("https://api.runware.ai", validation_alias="RUNWARE_BASE_URL")

    chat_model: str = Field("claude-sonnet-5-5", validation_alias="PICKLED_CHAT_MODEL")
    draft_model: str = Field("claude-sonnet-5-5", validation_alias="PICKLED_DRAFT_MODEL")
    match_model: str = Field("claude-sonnet-5-5", validation_alias="PICKLED_MATCH_MODEL")
    judge_model: str = Field("claude-sonnet-5-5", validation_alias="PICKLED_JUDGE_MODEL")
    llm_timeout_seconds: float = Field(120, validation_alias="PICKLED_LLM_TIMEOUT_SECONDS")
    llm_max_retries: int = Field(2, validation_alias="PICKLED_LLM_MAX_RETRIES")

    llm_monthly_cap_usd: Decimal = Field(
        Decimal("25"), validation_alias="PICKLED_LLM_MONTHLY_CAP_USD"
    )
    llm_min_balance_usd: Decimal = Field(
        Decimal("5"), validation_alias="PICKLED_LLM_MIN_BALANCE_USD"
    )


settings = Settings()
