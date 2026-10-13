"""`llm_context`: what started the model calls made inside it, for their `llm_call` rows."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class LlmContext:
    job: str | None = None
    meal_plan_id: int | None = None


NO_CONTEXT = LlmContext()

_current: ContextVar[LlmContext] = ContextVar("llm_context", default=NO_CONTEXT)


@contextmanager
def llm_context(*, job: str | None = None, meal_plan: int | None = None) -> Iterator[None]:
    """Label the calls made inside this block with the job or the Meal Plan that started them.

    Each entry point (a job, a chat request, the eval runner) wraps its work in one.
    """
    token = _current.set(LlmContext(job=job, meal_plan_id=meal_plan))
    try:
        yield
    finally:
        _current.reset(token)


def current_llm_context() -> LlmContext:
    return _current.get()
