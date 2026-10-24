"""The plan operations: the choices the agent and the Household make on a Meal Plan.

Each one checks the rules code enforces (spec §7), then returns the plan summary, which brings
the Shopping List up to date with the Meals.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from pickled.planning.checks import cooked_within
from pickled.planning.errors import PlanRefused
from pickled.planning.models import Meal, MealPlan, PlanStatus, Recipe
from pickled.planning.shopping import add_item
from pickled.planning.summary import PlanSummary, Prices, plan_summary
from pickled.stores import Store
from pickled.taste import household

SATURDAY = 5  # date.weekday()


def start_meal_plan(session: Session, week_start: date, *, now: datetime) -> MealPlan:
    """A new draft for the week from Shopping Day `week_start`, for the Household's size now."""
    if week_start.weekday() != SATURDAY:
        raise PlanRefused(f"A Meal Plan's week starts on a Saturday, and {week_start} isn't one.")
    if meal_plan_for(session, week_start) is not None:
        raise PlanRefused(f"The week of {week_start} already has a Meal Plan.")
    found = household(session)
    if found is None:
        raise PlanRefused("Set the Household's size before planning.")
    meal_plan = MealPlan(week_start=week_start, people=found.people, created_at=now)
    session.add(meal_plan)
    session.flush()
    return meal_plan


def next_shopping_day(today: date) -> date:
    """The first Shopping Day after `today`: the start of the next Meal Plan's week."""
    return today + timedelta(days=(SATURDAY - today.weekday() - 1) % 7 + 1)


def meal_plan_for(session: Session, week_start: date) -> MealPlan | None:
    return session.scalars(select(MealPlan).where(MealPlan.week_start == week_start)).first()


def set_store(
    session: Session, meal_plan: MealPlan, store: Store, *, today: date, prices: Prices
) -> PlanSummary:
    """Choose the store the Shopping List is bought at."""
    if meal_plan.week[-1] < today:
        raise PlanRefused("This Meal Plan's week has passed.")
    meal_plan.store = store
    return plan_summary(session, meal_plan, prices=prices)


def set_meal(
    session: Session,
    meal_plan: MealPlan,
    day: date,
    recipe: Recipe,
    servings: int,
    *,
    today: date,
    prices: Prices,
) -> PlanSummary:
    """Cook `recipe` for `servings` on `day`, replacing that day's Meal."""
    _check_day(meal_plan, day, today)
    if servings < 1:
        raise PlanRefused("A Meal is for at least one serving.")
    _check_not_repeated(session, recipe, day)
    meal = _meal(session, meal_plan, day)
    meal.recipe, meal.leftovers_of, meal.servings = recipe, None, servings
    return plan_summary(session, meal_plan, prices=prices)


def set_leftovers(
    session: Session,
    meal_plan: MealPlan,
    day: date,
    of_day: date,
    *,
    servings: int | None = None,
    today: date,
    prices: Prices,
) -> PlanSummary:
    """Eat the leftovers of `of_day`'s Meal on `day`, for `servings` (the Household's size by
    default). The Meal that was cooked grows by these servings."""
    _check_day(meal_plan, day, today)
    if not of_day < day:
        raise PlanRefused("Leftovers are of an earlier day's Meal.")
    if servings is not None and servings < 1:
        raise PlanRefused("A Meal is for at least one serving.")
    source = _existing_meal(session, meal_plan, of_day)
    if source is not None and source.leftovers_of is not None:
        source = source.leftovers_of
    if source is None or source.recipe is None:
        raise PlanRefused(f"{of_day} has no Meal cooked from a Recipe to have leftovers of.")
    meal = _meal(session, meal_plan, day)
    meal.recipe, meal.leftovers_of = None, source
    meal.servings = servings or meal_plan.people
    return plan_summary(session, meal_plan, prices=prices)


def clear_meal(
    session: Session, meal_plan: MealPlan, day: date, *, today: date, prices: Prices
) -> PlanSummary:
    """Leave `day` deliberately empty. Days eating its leftovers become unfilled."""
    _check_day(meal_plan, day, today)
    meal = _meal(session, meal_plan, day)
    session.flush()
    for eater in session.scalars(select(Meal).where(Meal.leftovers_of_id == meal.id)).all():
        session.delete(eater)
    meal.recipe, meal.leftovers_of, meal.servings = None, None, None
    session.flush()
    return plan_summary(session, meal_plan, prices=prices)


def add_shopping_item(
    session: Session,
    meal_plan: MealPlan,
    name: str,
    quantity: Decimal | int | None = None,
    unit: str | None = None,
    *,
    prices: Prices,
) -> PlanSummary:
    """Add an item of the Household's own to the Shopping List. It stays when the Meals change."""
    add_item(session, meal_plan, name, quantity, unit)
    return plan_summary(session, meal_plan, prices=prices)


def finish_draft(
    session: Session, meal_plan: MealPlan, *, now: datetime, prices: Prices
) -> PlanSummary:
    """End the draft: every day must have a Meal or be deliberately left empty."""
    if meal_plan.status != PlanStatus.DRAFT:
        raise PlanRefused("This Meal Plan is already accepted.")
    _check_complete(session, meal_plan)
    meal_plan.drafted_at = now
    return plan_summary(session, meal_plan, prices=prices)


def accept_meal_plan(
    session: Session, meal_plan: MealPlan, *, now: datetime, prices: Prices
) -> PlanSummary:
    """Accept the Meal Plan. It never goes back to draft, but the days ahead can still change."""
    if meal_plan.status == PlanStatus.ACCEPTED:
        raise PlanRefused("This Meal Plan is already accepted.")
    _check_complete(session, meal_plan)
    meal_plan.status, meal_plan.accepted_at = PlanStatus.ACCEPTED, now
    return plan_summary(session, meal_plan, prices=prices)


def _check_day(meal_plan: MealPlan, day: date, today: date) -> None:
    if day not in meal_plan.week:
        raise PlanRefused(f"{day} isn't in the week of {meal_plan.week_start}.")
    if day < today:
        raise PlanRefused(f"{day} has passed, and days that have passed never change.")


def _check_complete(session: Session, meal_plan: MealPlan) -> None:
    filled = {meal.date for meal in _meals(session, meal_plan)}
    unfilled = [day for day in meal_plan.week if day not in filled]
    if unfilled:
        days = ", ".join(str(day) for day in unfilled)
        raise PlanRefused(f"Fill these days, or leave them deliberately empty, first: {days}.")


def _check_not_repeated(session: Session, recipe: Recipe, day: date) -> None:
    cooked_on = cooked_within(session, recipe, day)
    if cooked_on is not None:
        raise PlanRefused(
            f"{recipe.title} is cooked on {cooked_on}, and a Recipe may not repeat within "
            "3 weeks: choose another, or use leftovers."
        )


def _meals(session: Session, meal_plan: MealPlan) -> list[Meal]:
    session.flush()
    return list(
        session.scalars(select(Meal).where(Meal.meal_plan_id == meal_plan.id).order_by(Meal.date))
    )


def _existing_meal(session: Session, meal_plan: MealPlan, day: date) -> Meal | None:
    return next((meal for meal in _meals(session, meal_plan) if meal.date == day), None)


def _meal(session: Session, meal_plan: MealPlan, day: date) -> Meal:
    meal = _existing_meal(session, meal_plan, day)
    if meal is None:
        meal = Meal(meal_plan=meal_plan, date=day)
        session.add(meal)
    return meal
