"""The plan summary: everything code calculates about a Meal Plan (ADR 0007, ADR 0008).

Every write tool returns it, and evals grade drafts with it, so it is the single source of every
number the agent states. Working it out also brings the stored Shopping List up to date.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from pickled.deals import deals_by_ingredient
from pickled.ingredients import Ingredient, ProductPicker
from pickled.planning.checks import GoalCheck, PlanWarning, check_goals, find_warnings
from pickled.planning.costs import (
    Amount,
    Bought,
    Need,
    PickedPrices,
    Prices,
    buy,
    line_amount,
    meal_factor,
    needs,
    offers,
    round_cents,
    used_cents,
)
from pickled.planning.models import ItemSource, Meal, MealPlan, PlanStatus, ShoppingListItem
from pickled.planning.shopping import regenerate
from pickled.planning.text import render
from pickled.stores import Store
from pickled.taste import active_food_goals


@dataclass(frozen=True)
class DaySummary:
    date: date
    kind: Literal["recipe", "leftovers", "empty", "unfilled"]
    title: str | None = None
    recipe_id: int | None = None
    servings: int | None = None
    leftovers_of: date | None = None
    # The meal cost at each store, in cents, for a filled day, and whether it is rough.
    meal_cents: dict[Store, int] | None = None
    meal_rough: dict[Store, bool] | None = None


@dataclass(frozen=True)
class StoreCosts:
    """What the plan costs at one store. Rough prices are counted, so the total reads
    "≈ €X, n items estimated"; unpriced items have no price at either store."""

    store: Store
    shopping_cents: int
    meal_cents: int
    rough: int
    unpriced: int
    meal_rough: bool


@dataclass(frozen=True)
class ShoppingLine:
    id: int
    name: str
    quantity: Decimal | None
    unit: str | None
    aisle: str
    store: Store | None
    pantry: bool
    manual: bool
    packs: int | None
    price_cents: int | None
    rough: bool
    deal: str | None
    checked: bool


@dataclass(frozen=True)
class PlanSummary:
    week_start: date
    status: PlanStatus
    store: Store | None
    people: int
    drafted: bool
    days: list[DaySummary]
    shopping_list: list[ShoppingLine]
    costs: dict[Store, StoreCosts]
    goals: list[GoalCheck]
    warnings: list[PlanWarning]

    @property
    def complete(self) -> bool:
        """Every day has a Meal or is deliberately left empty."""
        return all(day.kind != "unfilled" for day in self.days)

    @property
    def to_buy(self) -> dict[tuple[Store | None, str], list[ShoppingLine]]:
        """The Shopping List to buy, grouped by store and then aisle, in shop order."""
        groups: dict[tuple[Store | None, str], list[ShoppingLine]] = {}
        for line in self.shopping_list:
            if not line.pantry:
                groups.setdefault((line.store, line.aisle), []).append(line)
        return groups

    @property
    def check_you_have(self) -> list[ShoppingLine]:
        """The pantry Ingredients the Meals use, assumed in stock but worth checking."""
        return [line for line in self.shopping_list if line.pantry]

    def text(self) -> str:
        """The compact rendering tool results give the agent."""
        return render(self)


def plan_summary(session: Session, meal_plan: MealPlan, *, prices: Prices) -> PlanSummary:
    """Calculate the summary of `meal_plan`, bringing its stored Shopping List up to date."""
    session.flush()
    meals = _meals(session, meal_plan)
    needed = needs(meals)
    deals = _deals(session, meal_plan.week_start)
    bought = {
        store: {
            need: buy(
                need,
                offers(
                    prices.regular(need.ingredient, store), deals[store].get(need.ingredient, [])
                ),
            )
            for need in needed
        }
        for store in Store
    }
    items = regenerate(
        session, meal_plan, needed, bought[meal_plan.store] if meal_plan.store else None
    )
    costs = {store: _costs(store, meals, bought[store]) for store in Store}
    meal_plan.est_cost_cents = costs[meal_plan.store].shopping_cents if meal_plan.store else None
    # Before a store is chosen, the budget is checked at the cheaper one.
    shopping_cents = min(
        costs[store].shopping_cents for store in ([meal_plan.store] if meal_plan.store else Store)
    )
    by_date = {meal.date: meal for meal in meals}
    return PlanSummary(
        week_start=meal_plan.week_start,
        status=meal_plan.status,
        store=meal_plan.store,
        people=meal_plan.people,
        drafted=meal_plan.drafted_at is not None,
        days=[_day(day, by_date, bought) for day in meal_plan.week],
        shopping_list=[_line(item) for item in items],
        costs=costs,
        goals=check_goals(active_food_goals(session), meals, shopping_cents),
        warnings=find_warnings(session, meal_plan, meals, bought),
    )


def picked_prices(session: Session, meal_plan: MealPlan, picker: ProductPicker) -> Prices:
    """The prices the app plans with: each store's chosen Product on the plan's Shopping Day."""
    return PickedPrices(session, meal_plan.week_start, picker)


def _meals(session: Session, meal_plan: MealPlan) -> list[Meal]:
    return list(
        session.scalars(select(Meal).where(Meal.meal_plan_id == meal_plan.id).order_by(Meal.date))
    )


def _deals(session: Session, on: date) -> dict[Store, dict]:
    found: dict[Store, dict] = {store: {} for store in Store}
    for ingredient, deals in deals_by_ingredient(session, on).items():
        for deal in deals:
            found[deal.store].setdefault(ingredient, []).append(deal)
    return found


def _meal_cents(meal: Meal, bought: dict[Need, Bought]) -> tuple[Decimal, bool]:
    """A filled Meal's meal cost at a store, and whether any of it is rough."""
    recipe = meal.recipe or meal.leftovers_of.recipe
    total, rough = Decimal(0), False
    for line in recipe.lines:
        amount = line_amount(line, meal_factor(meal))
        found = _bought_for(line.ingredient, amount, bought)
        total += used_cents(amount, found)
        # A pinch or "to taste" costs nothing either way.
        rough = rough or (amount.quantity is not None and (found.rough or not found.priced))
    return total, rough


def _bought_for(ingredient: Ingredient, amount: Amount, bought: dict[Need, Bought]) -> Bought:
    """How the Need a Recipe line adds to was bought: the one in the line's unit, if the
    Ingredient's amounts couldn't all be added up."""
    mine = [line for need, line in bought.items() if need.ingredient == ingredient]
    return next((line for line in mine if line.need.amount.unit == amount.unit), mine[0])


def _costs(store: Store, meals: list[Meal], bought: dict[Need, Bought]) -> StoreCosts:
    shopped = [line for line in bought.values() if not line.need.ingredient.pantry]
    per_meal = [_meal_cents(meal, bought) for meal in meals if not meal.empty]
    return StoreCosts(
        store=store,
        shopping_cents=sum(line.cents for line in shopped if line.priced),
        meal_cents=round_cents(sum((cents for cents, _ in per_meal), Decimal(0))),
        rough=sum(1 for line in shopped if line.priced and line.rough),
        unpriced=sum(1 for line in shopped if not line.priced),
        meal_rough=any(rough for _, rough in per_meal),
    )


def _day(day: date, meals: dict[date, Meal], bought: dict[Store, dict[Need, Bought]]) -> DaySummary:
    meal = meals.get(day)
    if meal is None:
        return DaySummary(day, "unfilled")
    if meal.empty:
        return DaySummary(day, "empty")
    costs = {store: _meal_cents(meal, bought[store]) for store in Store}
    cents = {store: round_cents(cost) for store, (cost, _) in costs.items()}
    rough = {store: is_rough for store, (_, is_rough) in costs.items()}
    if meal.recipe is not None:
        return DaySummary(
            day,
            "recipe",
            meal.recipe.title,
            meal.recipe.id,
            meal.servings,
            meal_cents=cents,
            meal_rough=rough,
        )
    source = meal.leftovers_of
    return DaySummary(
        day,
        "leftovers",
        source.recipe.title,
        source.recipe.id,
        meal.servings,
        leftovers_of=source.date,
        meal_cents=cents,
        meal_rough=rough,
    )


def _line(item: ShoppingListItem) -> ShoppingLine:
    return ShoppingLine(
        id=item.id,
        name=item.name,
        quantity=item.quantity,
        unit=item.unit,
        aisle=item.aisle.value,
        store=item.store,
        pantry=item.pantry,
        manual=item.source == ItemSource.MANUAL,
        packs=item.packs,
        price_cents=item.est_price_cents,
        rough=item.rough,
        deal=item.deal.discount_text if item.deal is not None else None,
        checked=item.checked,
    )
