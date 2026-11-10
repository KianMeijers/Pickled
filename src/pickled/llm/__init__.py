"""Model calls: the one factory that builds models, and the record of what each call cost.

`make_chat_model(role)` is the only place a model is built (ADR 0004). Every call it makes is
written to `llm_call` with its cost from `price_of` (ADR 0009), labelled with what started it
through `llm_context`.
"""

from pickled.llm.balance import (
    BalanceComparison,
    compare_balance,
    latest_balance,
    read_runware_balance,
)
from pickled.llm.context import llm_context
from pickled.llm.errors import out_of_credit
from pickled.llm.factory import make_chat_model, runware_model
from pickled.llm.models import LlmBalance, LlmCall, Role
from pickled.llm.prices import TokenUsage, price_of
from pickled.llm.spend import (
    SpendCap,
    last_month_start,
    month_start,
    spend_by_role,
    spend_cap,
    spend_per_meal_plan,
)

__all__ = [
    "BalanceComparison",
    "LlmBalance",
    "LlmCall",
    "Role",
    "SpendCap",
    "TokenUsage",
    "compare_balance",
    "last_month_start",
    "latest_balance",
    "llm_context",
    "make_chat_model",
    "month_start",
    "out_of_credit",
    "price_of",
    "read_runware_balance",
    "runware_model",
    "spend_by_role",
    "spend_cap",
    "spend_per_meal_plan",
]
