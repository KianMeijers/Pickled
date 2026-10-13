"""`make_chat_model(role)`: the only place a model is built (ADR 0004, ADR 0009)."""

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models import BaseChatModel
from langchain_core.outputs import LLMResult
from sqlalchemy.orm import Session, sessionmaker

from pickled.config import Settings
from pickled.db import default_sessions
from pickled.llm.context import current_llm_context
from pickled.llm.models import LlmCall, Role
from pickled.llm.prices import TokenUsage, price_of

logger = logging.getLogger(__name__)

# Each role uses one of the four model settings.
ROLE_SETTINGS = {
    Role.CHAT: "chat_model",
    Role.DRAFT: "draft_model",
    Role.REFLECT: "draft_model",
    Role.TAG_DEALS: "match_model",
    Role.PICK_PRODUCT: "match_model",
    Role.EVAL_JUDGE: "judge_model",
}

MAX_TOKENS = 16_000


def runware_model(model: str, settings: Settings) -> ChatAnthropic:
    """Claude on Runware's Anthropic-format endpoint.

    Runware rejects LangChain's default `x-api-key` and accepts only a Bearer header.
    """
    key = settings.runware_api_key.get_secret_value()
    return ChatAnthropic(
        model=model,
        base_url=settings.runware_base_url,
        api_key=key,
        default_headers={"Authorization": f"Bearer {key}"},
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
        max_tokens=MAX_TOKENS,
    )


def make_chat_model(
    role: Role,
    *,
    sessions: sessionmaker[Session] | None = None,
    build: Callable[[str, Settings], BaseChatModel] = runware_model,
) -> BaseChatModel:
    """The model for `role`, which writes an `llm_call` row for every call it makes.

    `sessions` is where the rows go (the app's database by default), and `build` makes the
    model itself, so tests can pass a fake one.
    """
    settings = Settings()
    name = getattr(settings, ROLE_SETTINGS[role])
    model = build(name, settings)
    model.callbacks = [*(model.callbacks or []), LlmCallRecorder(role, name, sessions)]
    return model


class LlmCallRecorder(BaseCallbackHandler):
    """Writes one `llm_call` row per finished call. A failed write is logged, never raised."""

    def __init__(self, role: Role, model: str, sessions: sessionmaker[Session] | None):
        self.role = role
        self.model = model
        self.sessions = sessions

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        try:
            self._record(response)
        except Exception:
            logger.exception("Could not record a %s call to %s", self.role, self.model)

    def _record(self, response: LLMResult) -> None:
        metadata = getattr(response.generations[0][0], "message", None)
        metadata = getattr(metadata, "usage_metadata", None)
        if metadata is None:
            logger.warning("A %s call to %s reported no usage", self.role, self.model)
            return
        usage = TokenUsage.from_metadata(metadata)
        context = current_llm_context()
        call = LlmCall(
            called_at=datetime.now(UTC),
            role=self.role,
            model=self.model,
            job=context.job,
            meal_plan_id=context.meal_plan_id,
            input_tokens=usage.input,
            cache_write_tokens=usage.cache_write,
            cache_read_tokens=usage.cache_read,
            output_tokens=usage.output,
            cost_usd=price_of(self.model, usage),
        )
        with (self.sessions or default_sessions()).begin() as session:
            session.add(call)
