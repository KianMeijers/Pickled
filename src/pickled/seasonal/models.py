from enum import StrEnum

from sqlalchemy import CheckConstraint, ForeignKey, SmallInteger, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pickled.db import Base, IdPk, pg_enum
from pickled.ingredients import Ingredient


class Freshness(StrEnum):
    """Fresh is harvested that month; stored was harvested earlier and sold from storage."""

    FRESH = "fresh"
    STORED = "stored"


class SeasonalProduce(Base):
    """An Ingredient in season in a month (1 to 12)."""

    __tablename__ = "seasonal_produce"
    __table_args__ = (
        UniqueConstraint("ingredient_id", "month"),
        CheckConstraint("month BETWEEN 1 AND 12", name="month"),
    )

    id: Mapped[IdPk]
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredient.id"))
    month: Mapped[int] = mapped_column(SmallInteger)
    freshness: Mapped[Freshness] = mapped_column(pg_enum(Freshness, "freshness"))

    ingredient: Mapped[Ingredient] = relationship()
