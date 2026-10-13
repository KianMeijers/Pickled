"""Model calls: the one factory that builds models, and the record of what each call cost.

`make_chat_model(role)` is the only place a model is built (ADR 0004). Every call it makes is
written to `llm_call` with its cost from `price_of` (ADR 0009), labelled with what started it
through `llm_context`.
"""

from pickled.llm.context import llm_context
from pickled.llm.errors import out_of_credit
from pickled.llm.factory import make_chat_model
from pickled.llm.models import LlmCall, Role
from pickled.llm.prices import TokenUsage, price_of

__all__ = [
    "LlmCall",
    "Role",
    "TokenUsage",
    "llm_context",
    "make_chat_model",
    "out_of_credit",
    "price_of",
]
