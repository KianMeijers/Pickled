from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy.orm import Mapped, mapped_column

from pickled.db import Base, IdPk, pg_enum


class Role(StrEnum):
    """What a model call is for. Spend is split by role; roles share the model settings."""

    CHAT = "chat"
    DRAFT = "draft"
    REFLECT = "reflect"
    TAG_DEALS = "tag_deals"
    PICK_PRODUCT = "pick_product"
    EVAL_JUDGE = "eval_judge"


class LlmCall(Base):
    """One model call and what it cost. Kept forever."""

    __tablename__ = "llm_call"

    id: Mapped[IdPk]
    called_at: Mapped[datetime] = mapped_column(index=True)
    role: Mapped[Role] = mapped_column(pg_enum(Role, "llm_role"))
    model: Mapped[str]
    job: Mapped[str | None]
    meal_plan_id: Mapped[int | None]
    input_tokens: Mapped[int]
    cache_write_tokens: Mapped[int]
    cache_read_tokens: Mapped[int]
    output_tokens: Mapped[int]
    # Null when the model has no price in the table: unknown, never zero.
    cost_usd: Mapped[Decimal | None]
