"""The plan summary's Food Goal checks and warnings."""

from datetime import timedelta
from decimal import Decimal

import pytest
from planning_helpers import (
    NOW,
    SATURDAY,
    TODAY,
    WEEK,
    FakePrices,
    cents,
    deal,
    ingredient,
    plan,
    recipe,
)

from pickled.ingredients import Aisle
from pickled.planning import (
    Meal,
    Nutrition,
    WarningKind,
    clear_meal,
    plan_summary,
    set_leftovers,
    set_meal,
    set_store,
    start_meal_plan,
)
from pickled.stores import Store
from pickled.taste import FoodGoalKind, set_food_goal

PRICES = FakePrices()


@pytest.fixture
def rijst(db_session):
    return ingredient(db_session, "rijst", Aisle.VOORRAAD)


def dish(session, title, kcal=600, protein_g=30, tags=()):
    nutrition = Nutrition(kcal=kcal, protein_g=protein_g, carbs_g=60, fat_g=20)
    return recipe(session, title, ("rijst", 100, "g"), nutrition=nutrition, tags=tags)


def goal(summary, kind):
    return next(check for check in summary.goals if check.kind == kind)


def test_nutrition_is_checked_against_the_dinner_share_of_the_daily_goal(db_session, rijst):
    set_food_goal(db_session, FoodGoalKind.KCAL_PER_DAY, min=1800, max=2200, now=NOW)
    set_food_goal(db_session, FoodGoalKind.PROTEIN_G_PER_DAY, min=100, now=NOW)
    meal_plan = plan(db_session)
    set_meal(
        db_session,
        meal_plan,
        WEEK[0],
        dish(db_session, "A", 700, 30),
        2,
        today=TODAY,
        prices=PRICES,
    )
    set_meal(
        db_session,
        meal_plan,
        WEEK[1],
        dish(db_session, "B", 900, 40),
        2,
        today=TODAY,
        prices=PRICES,
    )
    clear_meal(db_session, meal_plan, WEEK[2], today=TODAY, prices=PRICES)

    summary = set_leftovers(db_session, meal_plan, WEEK[3], WEEK[1], today=TODAY, prices=PRICES)

    # A dinner is 40% of the day: 720 to 880 kcal, and at least 40 g protein. The three
    # filled days average 833 kcal and 36.7 g protein; the empty day doesn't count.
    kcal = goal(summary, FoodGoalKind.KCAL_PER_DAY)
    assert (kcal.target_min, kcal.target_max, kcal.met) == (Decimal(720), Decimal(880), True)
    assert round(kcal.actual) == 833
    protein = goal(summary, FoodGoalKind.PROTEIN_G_PER_DAY)
    assert (protein.target_min, protein.target_max, protein.met) == (Decimal(40), None, False)


def test_a_nutrition_goal_with_no_meals_yet_is_not_judged(db_session):
    set_food_goal(db_session, FoodGoalKind.KCAL_PER_DAY, max=2000, now=NOW)

    summary = plan_summary(db_session, plan(db_session), prices=PRICES)

    assert (
        goal(summary, FoodGoalKind.KCAL_PER_DAY).actual,
        goal(summary, FoodGoalKind.KCAL_PER_DAY).met,
    ) == (None, None)


def test_vegetarian_days_are_counted_exactly_with_their_leftovers(db_session, rijst):
    set_food_goal(db_session, FoodGoalKind.VEGETARIAN_DAYS_PER_WEEK, min=3, now=NOW)
    meal_plan = plan(db_session)
    veggie = dish(db_session, "Curry", tags=["vegetarisch"])
    set_meal(db_session, meal_plan, WEEK[0], veggie, 2, today=TODAY, prices=PRICES)
    set_meal(db_session, meal_plan, WEEK[1], dish(db_session, "Kip"), 2, today=TODAY, prices=PRICES)
    summary = set_leftovers(db_session, meal_plan, WEEK[2], WEEK[0], today=TODAY, prices=PRICES)

    check = goal(summary, FoodGoalKind.VEGETARIAN_DAYS_PER_WEEK)
    assert (check.actual, check.met) == (2, False)

    other = dish(db_session, "Linzensoep", tags=["vegetarisch", "soep"])
    summary = set_meal(db_session, meal_plan, WEEK[3], other, 2, today=TODAY, prices=PRICES)
    check = goal(summary, FoodGoalKind.VEGETARIAN_DAYS_PER_WEEK)
    assert (check.actual, check.met) == (3, True)


def test_the_budget_is_checked_exactly_against_the_shopping_cost_at_the_plans_store(
    db_session, rijst
):
    set_food_goal(db_session, FoodGoalKind.BUDGET_CENTS_PER_WEEK, max=cents("2.00"), now=NOW)
    prices = FakePrices().set("rijst", Store.AH, cents("2.00"), "1 kg")
    prices.set("rijst", Store.JUMBO, cents("2.01"), "1 kg")
    meal_plan = plan(db_session)
    set_meal(db_session, meal_plan, WEEK[0], dish(db_session, "A"), 2, today=TODAY, prices=prices)

    on_ah = set_store(db_session, meal_plan, Store.AH, today=TODAY, prices=prices)
    on_jumbo = set_store(db_session, meal_plan, Store.JUMBO, today=TODAY, prices=prices)

    assert goal(on_ah, FoodGoalKind.BUDGET_CENTS_PER_WEEK).met is True
    assert goal(on_jumbo, FoodGoalKind.BUDGET_CENTS_PER_WEEK).met is False
    assert goal(on_jumbo, FoodGoalKind.BUDGET_CENTS_PER_WEEK).actual == cents("2.01")


def test_an_other_goal_is_listed_for_the_agent_but_not_judged(db_session):
    set_food_goal(db_session, FoodGoalKind.OTHER, text="Weinig zout", now=NOW)

    summary = plan_summary(db_session, plan(db_session), prices=PRICES)

    check = goal(summary, FoodGoalKind.OTHER)
    assert (check.text, check.met) == ("Weinig zout", None)


def warnings(summary, kind):
    return [(w.date, w.ingredient, w.cents) for w in summary.warnings if w.kind == kind]


def test_a_meal_using_an_ingredient_after_it_keeps_is_warned_about(db_session, rijst):
    ingredient(db_session, "kipfilet", Aisle.VLEES_VIS_VEGA, keeps_days=2)
    ingredient(db_session, "basilicum", Aisle.GROENTE_FRUIT, keeps_days=1, pantry=True)
    meal_plan = plan(db_session)
    for day in (WEEK[2], WEEK[3]):
        chicken = recipe(db_session, f"Kip {day}", ("kipfilet", 300, "g"), ("basilicum", 5, "g"))
        set_meal(db_session, meal_plan, day, chicken, 2, today=TODAY, prices=PRICES)

    summary = set_leftovers(db_session, meal_plan, WEEK[5], WEEK[3], today=TODAY, prices=PRICES)

    # Monday is 2 days after the Shopping Day, Tuesday 3. Pantry items and leftovers aren't
    # bought fresh for the day.
    assert warnings(summary, WarningKind.PERISHABLE) == [(WEEK[3], "kipfilet", None)]


@pytest.mark.parametrize(("jumbo_deal", "warned"), [("voor 2.50", True), ("voor 3.50", False)])
def test_a_split_is_suggested_when_the_other_stores_deals_save_three_euros(
    db_session, rijst, jumbo_deal, warned
):
    kipfilet = ingredient(db_session, "kipfilet", Aisle.VLEES_VIS_VEGA)
    deal(db_session, Store.JUMBO, kipfilet, jumbo_deal, unit_size="500 g")
    prices = FakePrices().set("kipfilet", Store.AH, cents("6.00"), "500 g")
    prices.set("kipfilet", Store.JUMBO, cents("6.00"), "500 g")
    # Jumbo's rice is cheaper too, but not on a Deal, so it's no reason for the trip.
    prices.set("rijst", Store.AH, cents("3.00"), "1 kg").set(
        "rijst", Store.JUMBO, cents("1.00"), "1 kg"
    )
    meal_plan = plan(db_session)
    set_store(db_session, meal_plan, Store.AH, today=TODAY, prices=prices)
    chicken = recipe(db_session, "Kip", ("kipfilet", 300, "g"), ("rijst", 100, "g"))

    summary = set_meal(db_session, meal_plan, WEEK[0], chicken, 2, today=TODAY, prices=prices)

    expected = [(None, "kipfilet", cents("3.50"))] if warned else []
    assert warnings(summary, WarningKind.SPLIT) == expected


def test_rough_prices_at_the_plans_store_are_warned_about(db_session, rijst):
    prices = FakePrices().set("rijst", Store.AH, cents("2.00"), "1 kg", rough=True)
    meal_plan = plan(db_session)
    set_store(db_session, meal_plan, Store.AH, today=TODAY, prices=prices)

    summary = set_meal(
        db_session, meal_plan, WEEK[0], dish(db_session, "A"), 2, today=TODAY, prices=prices
    )

    assert warnings(summary, WarningKind.ROUGH) == [(None, "rijst", None)]


def test_a_recipe_repeated_within_three_weeks_is_warned_about(db_session, rijst):
    stew = dish(db_session, "Stoofpot")
    meal_plan = plan(db_session)
    set_meal(db_session, meal_plan, WEEK[0], stew, 2, today=TODAY, prices=PRICES)
    # Set without the plan operations, which would refuse it.
    earlier = start_meal_plan(db_session, SATURDAY - timedelta(weeks=2), now=NOW)
    db_session.add(Meal(meal_plan=earlier, date=earlier.week_start, recipe=stew, servings=2))

    summary = plan_summary(db_session, meal_plan, prices=PRICES)

    assert warnings(summary, WarningKind.REPEAT) == [(WEEK[0], None, None)]
