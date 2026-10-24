from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import CheckConstraint, ForeignKey, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pickled.db import Base, IdPk, pg_enum
from pickled.deals import Deal
from pickled.ingredients import Aisle, Ingredient
from pickled.stores.store import STORE_TYPE, Store


class PlanStatus(StrEnum):
    """One way: a draft is accepted, and an accepted Meal Plan never goes back to draft."""

    DRAFT = "draft"
    ACCEPTED = "accepted"


class Unit(StrEnum):
    """The units a Recipe line is stored in; kg and l are converted to g and ml on save."""

    G = "g"
    ML = "ml"
    PIECE = "piece"
    TBSP = "tbsp"
    TSP = "tsp"
    PINCH = "pinch"
    TO_TASTE = "to_taste"


class ItemSource(StrEnum):
    RECIPE = "recipe"
    MANUAL = "manual"


class MealPlan(Base):
    __tablename__ = "meal_plan"
    __table_args__ = (
        CheckConstraint("extract(isodow FROM week_start) = 6", name="week_starts_saturday"),
        CheckConstraint(
            "(status = 'accepted') = (accepted_at IS NOT NULL)", name="accepted_when_accepted"
        ),
    )

    id: Mapped[IdPk]
    week_start: Mapped[date] = mapped_column(unique=True)
    status: Mapped[PlanStatus] = mapped_column(
        pg_enum(PlanStatus, "plan_status"), default=PlanStatus.DRAFT
    )
    store: Mapped[Store | None] = mapped_column(STORE_TYPE)
    people: Mapped[int]
    # The shopping cost at the plan's store, kept up to date as its Meals change.
    est_cost_cents: Mapped[int | None]
    created_at: Mapped[datetime]
    # When the draft was finished; a draft without it is partial.
    drafted_at: Mapped[datetime | None]
    accepted_at: Mapped[datetime | None]

    meals: Mapped[list[Meal]] = relationship(
        back_populates="meal_plan", order_by="Meal.date", cascade="all, delete-orphan"
    )
    shopping_list: Mapped[list[ShoppingListItem]] = relationship(
        back_populates="meal_plan", order_by="ShoppingListItem.id", cascade="all, delete-orphan"
    )

    @property
    def week(self) -> list[date]:
        """The seven days from the Shopping Day to the Friday after it."""
        return [self.week_start + timedelta(days=i) for i in range(7)]


class Meal(Base):
    """One day's dinner: a Recipe for some servings, leftovers of an earlier Meal for some
    servings, or, with neither, a day deliberately left empty. A day with no row is unfilled."""

    __tablename__ = "meal"
    __table_args__ = (
        UniqueConstraint("meal_plan_id", "date"),
        CheckConstraint(
            "(recipe_id IS NULL OR leftovers_of_id IS NULL)"
            " AND ((recipe_id IS NULL AND leftovers_of_id IS NULL) = (servings IS NULL))"
            " AND servings > 0",
            name="filled_or_empty",
        ),
    )

    id: Mapped[IdPk]
    meal_plan_id: Mapped[int] = mapped_column(ForeignKey("meal_plan.id"))
    date: Mapped[date]
    recipe_id: Mapped[int | None] = mapped_column(ForeignKey("recipe.id"), index=True)
    leftovers_of_id: Mapped[int | None] = mapped_column(ForeignKey("meal.id"))
    servings: Mapped[int | None]

    meal_plan: Mapped[MealPlan] = relationship(back_populates="meals")
    recipe: Mapped[Recipe | None] = relationship()
    leftovers_of: Mapped[Meal | None] = relationship(remote_side="Meal.id")

    @property
    def empty(self) -> bool:
        return self.recipe_id is None and self.leftovers_of_id is None


class Recipe(Base):
    """A saved Recipe. It never changes: a variation is a new Recipe, `derived_from` this one."""

    __tablename__ = "recipe"
    __table_args__ = (CheckConstraint("servings > 0", name="servings_positive"),)

    id: Mapped[IdPk]
    title: Mapped[str]
    servings: Mapped[int]
    steps: Mapped[str]
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    # Estimated nutrition per serving.
    kcal: Mapped[Decimal]
    protein_g: Mapped[Decimal]
    carbs_g: Mapped[Decimal]
    fat_g: Mapped[Decimal]
    derived_from_id: Mapped[int | None] = mapped_column(ForeignKey("recipe.id"))
    created_at: Mapped[datetime]

    lines: Mapped[list[RecipeIngredient]] = relationship(
        back_populates="recipe", order_by="RecipeIngredient.id", cascade="all, delete-orphan"
    )


class RecipeIngredient(Base):
    __tablename__ = "recipe_ingredient"

    id: Mapped[IdPk]
    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipe.id"), index=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredient.id"), index=True)
    quantity: Mapped[Decimal | None]
    unit: Mapped[Unit] = mapped_column(pg_enum(Unit, "recipe_unit"))
    note: Mapped[str | None]

    recipe: Mapped[Recipe] = relationship(back_populates="lines")
    ingredient: Mapped[Ingredient] = relationship()


class ShoppingListItem(Base):
    """A line of a Meal Plan's Shopping List. The Recipe lines are regenerated whenever the
    Meals change; manual lines, and ticks matched by name, survive that."""

    __tablename__ = "shopping_list_item"

    id: Mapped[IdPk]
    meal_plan_id: Mapped[int] = mapped_column(ForeignKey("meal_plan.id"), index=True)
    name: Mapped[str]
    ingredient_id: Mapped[int | None] = mapped_column(ForeignKey("ingredient.id"))
    quantity: Mapped[Decimal | None]
    unit: Mapped[str | None]
    source: Mapped[ItemSource] = mapped_column(pg_enum(ItemSource, "shopping_item_source"))
    pantry: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    deal_id: Mapped[int | None] = mapped_column(ForeignKey("deal.id"))
    store: Mapped[Store | None] = mapped_column(STORE_TYPE)
    aisle: Mapped[Aisle] = mapped_column(pg_enum(Aisle, "aisle"))
    packs: Mapped[int | None]
    est_price_cents: Mapped[int | None]
    rough: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    checked: Mapped[bool] = mapped_column(default=False, server_default=text("false"))

    meal_plan: Mapped[MealPlan] = relationship(back_populates="shopping_list")
    deal: Mapped[Deal | None] = relationship()
