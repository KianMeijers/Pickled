"""The agent's prompts, rendered from the Jinja templates in `prompts/`. Prompts are English and
tell the agent to write to the Household in Dutch."""

from datetime import date
from decimal import Decimal

from jinja2 import Environment, PackageLoader, StrictUndefined
from sqlalchemy.orm import Session

from pickled.deals import Deal, deals_by_ingredient
from pickled.planning import MealPlan
from pickled.seasonal import month_of_week, seasonal_for
from pickled.stores import Store
from pickled.taste import FoodGoal, FoodGoalKind, active_food_goals, active_taste_notes

templates = Environment(
    loader=PackageLoader("pickled.agent", "prompts"),
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
    undefined=StrictUndefined,
)

# The Deal table holds the Ingredients with the best discounts, about 100 lines (spec §7).
DEAL_TABLE_LINES = 100
STORE_NAMES = {Store.AH: "AH", Store.JUMBO: "Jumbo"}
GOAL_NAMES = {
    FoodGoalKind.KCAL_PER_DAY: "kcal per person per day",
    FoodGoalKind.PROTEIN_G_PER_DAY: "protein g per person per day",
    FoodGoalKind.VEGETARIAN_DAYS_PER_WEEK: "vegetarian days per week",
    FoodGoalKind.BUDGET_CENTS_PER_WEEK: "shopping budget per week",
}


def system_prompt(session: Session, meal_plan: MealPlan, *, today: date) -> str:
    """What the agent knows of the Household and the Meal Plan's week."""
    month = month_of_week(meal_plan.week_start)
    return templates.get_template("system.jinja").render(
        people=meal_plan.people,
        notes=active_taste_notes(session),
        goals=[_goal(goal) for goal in active_food_goals(session)],
        week=meal_plan.week,
        today=today,
        month=date(today.year, month, 1).strftime("%B"),
        seasonal=[
            f"{produce.ingredient.name} ({produce.freshness})"
            for produce in seasonal_for(session, month)
        ],
        deals=deal_table(session, meal_plan.week_start),
    )


def deal_table(session: Session, on: date) -> list[str]:
    """One line per Ingredient on a Deal on `on`, with each store's best discount on it,
    best discounts first."""
    rows = []
    for ingredient, deals in deals_by_ingredient(session, on).items():
        best: dict[Store, Deal] = {}
        for deal in deals:
            if deal.store not in best or _off(deal) > _off(best[deal.store]):
                best[deal.store] = deal
        offers = "; ".join(_offer(best[store]) for store in Store if store in best)
        rows.append((max(_off(deal) for deal in best.values()), f"{ingredient.name}: {offers}"))
    rows.sort(key=lambda row: -row[0])
    return [line for _, line in rows[:DEAL_TABLE_LINES]]


def describe_off(deal: Deal) -> str:
    """The Deal's text, with the share off the regular price where it is known."""
    if deal.effective_fraction is None:
        return deal.discount_text
    return f"{deal.discount_text} ({deal.effective_fraction:.0%} off)"


def _offer(deal: Deal) -> str:
    return f"{STORE_NAMES[deal.store]} {describe_off(deal)}"


def _off(deal: Deal) -> Decimal:
    """The share off, for ordering; a Deal whose share isn't known comes last."""
    return deal.effective_fraction if deal.effective_fraction is not None else Decimal(-1)


def _goal(goal: FoodGoal) -> str:
    if goal.kind == FoodGoalKind.OTHER:
        return f"other: {goal.text}"
    money = goal.kind == FoodGoalKind.BUDGET_CENTS_PER_WEEK
    bounds = [
        f"{word} {_money(value) if money else _number(value)}"
        for word, value in (("min", goal.min), ("max", goal.max))
        if value is not None
    ]
    return f"{GOAL_NAMES[goal.kind]} {', '.join(bounds)}"


def _money(cents: Decimal) -> str:
    return f"€{cents / 100:.2f}"


def _number(value: Decimal) -> str:
    return f"{value.normalize():f}"
