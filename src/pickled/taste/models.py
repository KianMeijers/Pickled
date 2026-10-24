from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import CheckConstraint, Index, text
from sqlalchemy.orm import Mapped, mapped_column

from pickled.db import Base, IdPk, pg_enum


class Author(StrEnum):
    AGENT = "agent"
    USER = "user"


class FoodGoalKind(StrEnum):
    """Nutrition goals are per person per day; the budget is for the Household per week."""

    KCAL_PER_DAY = "kcal_per_day"
    PROTEIN_G_PER_DAY = "protein_g_per_day"
    VEGETARIAN_DAYS_PER_WEEK = "vegetarian_days_per_week"
    BUDGET_CENTS_PER_WEEK = "budget_cents_per_week"
    OTHER = "other"


class Household(Base):
    """The one Household Pickled plans for. Nothing refers to it by key."""

    __tablename__ = "household"
    __table_args__ = (
        # A single row: every row would have the same value for this index.
        Index("uq_household_single", text("(true)"), unique=True),
        CheckConstraint("people > 0", name="people_positive"),
    )

    id: Mapped[IdPk]
    people: Mapped[int]
    name: Mapped[str | None]


class TasteNote(Base):
    """One short note of the Taste Profile. An archived note is kept, but no longer used."""

    __tablename__ = "taste_note"
    __table_args__ = (CheckConstraint("char_length(text) <= 200", name="text_short"),)

    id: Mapped[IdPk]
    text: Mapped[str]
    author: Mapped[Author] = mapped_column(pg_enum(Author, "taste_note_author"))
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]
    archived_at: Mapped[datetime | None]


class FoodGoal(Base):
    """A Food Goal. A changed or cleared goal is kept inactive, for its history."""

    __tablename__ = "food_goal"
    __table_args__ = (
        CheckConstraint("min IS NOT NULL OR max IS NOT NULL OR kind = 'other'", name="has_bound"),
        CheckConstraint("kind <> 'other' OR text IS NOT NULL", name="other_has_text"),
    )

    id: Mapped[IdPk]
    kind: Mapped[FoodGoalKind] = mapped_column(pg_enum(FoodGoalKind, "food_goal_kind"))
    min: Mapped[Decimal | None]
    max: Mapped[Decimal | None]
    text: Mapped[str | None]
    active: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    set_at: Mapped[datetime]
