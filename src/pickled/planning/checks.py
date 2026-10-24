"""The plan summary's Food Goal checks and warnings: what evals grade and the agent acts on."""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from pickled.planning.costs import Bought, Need
from pickled.planning.models import Meal, MealPlan, Recipe
from pickled.stores import Store
from pickled.taste import FoodGoal, FoodGoalKind

# A Meal Plan covers dinners only, so a daily nutrition goal is checked against this share.
DINNER_SHARE = Decimal("0.4")
VEGETARIAN_TAG = "vegetarisch"
# The other store is worth a split trip when its Deals save at least this much.
SPLIT_SAVING_CENTS = 300
# A Recipe isn't cooked again until this long after it was last cooked.
REPEAT_AFTER = timedelta(weeks=3)

NUTRITION = {FoodGoalKind.KCAL_PER_DAY: "kcal", FoodGoalKind.PROTEIN_G_PER_DAY: "protein_g"}


@dataclass(frozen=True)
class GoalCheck:
    """A Food Goal against the plan. Nutrition targets are the dinner share of the goal; `met`
    is None where code can't judge it (no Meals yet, or an `other` goal)."""

    kind: FoodGoalKind
    min: Decimal | None
    max: Decimal | None
    target_min: Decimal | None
    target_max: Decimal | None
    actual: Decimal | int | None
    met: bool | None
    text: str | None = None


class WarningKind(StrEnum):
    PERISHABLE = "perishable"
    SPLIT = "split"
    ROUGH = "rough"
    REPEAT = "repeat"


@dataclass(frozen=True)
class PlanWarning:
    kind: WarningKind
    message: str
    date: date | None = None
    ingredient: str | None = None
    cents: int | None = None


def check_goals(
    goals: list[FoodGoal], meals: list[Meal], shopping_cents: int | None
) -> list[GoalCheck]:
    """Each active Food Goal checked against the filled `meals`, and the budget against
    `shopping_cents` at the plan's store."""
    eaten = [_recipe(meal) for meal in meals if not meal.empty]
    return [_check(goal, eaten, shopping_cents) for goal in goals]


def _check(goal: FoodGoal, eaten: list[Recipe], shopping_cents: int | None) -> GoalCheck:
    if goal.kind in NUTRITION:
        target_min, target_max = (
            bound * DINNER_SHARE if bound is not None else None for bound in (goal.min, goal.max)
        )
        field = NUTRITION[goal.kind]
        actual = (
            sum((getattr(recipe, field) for recipe in eaten), Decimal(0)) / len(eaten)
            if eaten
            else None
        )
        return GoalCheck(
            goal.kind,
            goal.min,
            goal.max,
            target_min,
            target_max,
            actual,
            _within(actual, target_min, target_max),
        )
    if goal.kind == FoodGoalKind.VEGETARIAN_DAYS_PER_WEEK:
        actual = sum(1 for recipe in eaten if VEGETARIAN_TAG in recipe.tags)
        return GoalCheck(
            goal.kind,
            goal.min,
            goal.max,
            goal.min,
            goal.max,
            actual,
            _within(actual, goal.min, goal.max),
        )
    if goal.kind == FoodGoalKind.BUDGET_CENTS_PER_WEEK:
        return GoalCheck(
            goal.kind,
            goal.min,
            goal.max,
            goal.min,
            goal.max,
            shopping_cents,
            _within(shopping_cents, goal.min, goal.max),
        )
    return GoalCheck(goal.kind, None, None, None, None, None, None, goal.text)


def _within(actual, low, high) -> bool | None:
    if actual is None:
        return None
    return (low is None or actual >= low) and (high is None or actual <= high)


def _recipe(meal: Meal) -> Recipe:
    recipe = meal.recipe or meal.leftovers_of.recipe
    assert recipe is not None
    return recipe


def find_warnings(
    session: Session,
    meal_plan: MealPlan,
    meals: list[Meal],
    bought: dict[Store, dict[Need, Bought]],
) -> list[PlanWarning]:
    """Advice for the agent: none of it blocks a change."""
    found = _perishable(meal_plan, meals) + _repeats(session, meals)
    if meal_plan.store is not None:
        found += _rough(bought[meal_plan.store])
        other = next(store for store in Store if store != meal_plan.store)
        found += _split(bought[meal_plan.store], bought[other], other)
    return found


def cooked_within(session: Session, recipe: Recipe, day: date) -> date | None:
    """Another day `recipe` is cooked on, less than 3 weeks from `day`, if there is one."""
    return session.scalars(
        select(Meal.date)
        .where(
            Meal.recipe_id == recipe.id,
            Meal.date != day,
            Meal.date > day - REPEAT_AFTER,
            Meal.date < day + REPEAT_AFTER,
        )
        .order_by(Meal.date)
    ).first()


def _perishable(meal_plan: MealPlan, meals: list[Meal]) -> list[PlanWarning]:
    """Ingredients a cooked Meal uses after they keep from the Shopping Day."""
    found = []
    for meal in meals:
        if meal.recipe is None:
            continue
        after = (meal.date - meal_plan.week_start).days
        for line in meal.recipe.lines:
            ingredient = line.ingredient
            if ingredient.pantry or ingredient.keeps_days is None or after <= ingredient.keeps_days:
                continue
            found.append(
                PlanWarning(
                    WarningKind.PERISHABLE,
                    f"{ingredient.name} keeps {ingredient.keeps_days} days from the Shopping Day, "
                    f"but {meal.recipe.title} on {meal.date} is {after} days after it: "
                    "cook it earlier in the week.",
                    date=meal.date,
                    ingredient=ingredient.name,
                )
            )
    return found


def _repeats(session: Session, meals: list[Meal]) -> list[PlanWarning]:
    found = []
    for meal in meals:
        if meal.recipe is None:
            continue
        other = cooked_within(session, meal.recipe, meal.date)
        if other is not None:
            found.append(
                PlanWarning(
                    WarningKind.REPEAT,
                    f"{meal.recipe.title} on {meal.date} is also cooked on {other}, within "
                    "3 weeks.",
                    date=meal.date,
                )
            )
    return found


def _rough(bought: dict[Need, Bought]) -> list[PlanWarning]:
    return [
        PlanWarning(
            WarningKind.ROUGH,
            f"{line.need.ingredient.name}'s price is estimated.",
            ingredient=line.need.ingredient.name,
        )
        for line in bought.values()
        if line.priced and line.rough and not line.need.ingredient.pantry
    ]


def _split(here: dict[Need, Bought], there: dict[Need, Bought], other: Store) -> list[PlanWarning]:
    """One warning for the lines the other store's Deals make cheaper, if together they save
    enough to be worth a second shop."""
    savings = {}
    for need, line in here.items():
        elsewhere = there[need]
        if need.ingredient.pantry or not (line.priced and elsewhere.priced):
            continue
        if elsewhere.offer.deal is not None and elsewhere.cents < line.cents:
            savings[need.ingredient.name] = line.cents - elsewhere.cents
    total = sum(savings.values())
    if total < SPLIT_SAVING_CENTS:
        return []
    names = ", ".join(sorted(savings))
    return [
        PlanWarning(
            WarningKind.SPLIT,
            f"Buying {names} on a Deal at {other} saves €{total / 100:.2f}: consider a split.",
            ingredient=names,
            cents=total,
        )
    ]
