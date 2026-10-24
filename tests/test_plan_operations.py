"""The plan operations and the rules code enforces on them (spec §7)."""

from datetime import timedelta

import pytest
from planning_helpers import NOW, SATURDAY, TODAY, WEEK, FakePrices, ingredient, plan, recipe

from pickled.planning import (
    PlanRefused,
    PlanStatus,
    accept_meal_plan,
    clear_meal,
    finish_draft,
    meal_plan_for,
    set_leftovers,
    set_meal,
    set_store,
    start_meal_plan,
)
from pickled.stores import Store
from pickled.taste import set_household

PRICES = FakePrices()


@pytest.fixture
def stew(db_session):
    ingredient(db_session, "ui")
    return recipe(db_session, "Stoofpot", ("ui", 1, "piece"))


def fill(session, meal_plan, leaving_out=()):
    """Fill the days of the week with a different Recipe each, but for `leaving_out`."""
    for day in WEEK:
        if day in leaving_out:
            continue
        other = recipe(session, f"Stoofpot {day}", ("ui", 1, "piece"))
        set_meal(session, meal_plan, day, other, 2, today=TODAY, prices=PRICES)


def test_a_new_plan_is_a_draft_for_the_households_size(db_session):
    meal_plan = plan(db_session, people=3)

    assert (meal_plan.status, meal_plan.people) == (PlanStatus.DRAFT, 3)
    assert meal_plan_for(db_session, SATURDAY) == meal_plan


def test_a_plan_starts_on_a_saturday_and_there_is_one_per_week(db_session):
    plan(db_session)

    with pytest.raises(PlanRefused, match="already"):
        start_meal_plan(db_session, SATURDAY, now=NOW)
    with pytest.raises(PlanRefused, match="Saturday"):
        start_meal_plan(db_session, SATURDAY + timedelta(days=1), now=NOW)


def test_a_plan_needs_the_household_size_first(db_session):
    with pytest.raises(PlanRefused, match="Household"):
        start_meal_plan(db_session, SATURDAY, now=NOW)


def test_meals_are_set_on_the_days_of_the_plans_week(db_session, stew):
    meal_plan = plan(db_session)

    summary = set_meal(db_session, meal_plan, WEEK[1], stew, 2, today=TODAY, prices=PRICES)

    assert [(d.date, d.title, d.servings) for d in summary.days if d.title] == [
        (WEEK[1], "Stoofpot", 2)
    ]
    with pytest.raises(PlanRefused, match="week"):
        set_meal(db_session, meal_plan, WEEK[6] + timedelta(1), stew, 2, today=TODAY, prices=PRICES)


def test_setting_a_meal_again_replaces_that_days_meal(db_session, stew):
    meal_plan = plan(db_session)
    other = recipe(db_session, "Soep", ("ui", 2, "piece"))
    set_meal(db_session, meal_plan, WEEK[0], stew, 2, today=TODAY, prices=PRICES)

    summary = set_meal(db_session, meal_plan, WEEK[0], other, 3, today=TODAY, prices=PRICES)

    assert (summary.days[0].title, summary.days[0].servings) == ("Soep", 3)


def test_days_that_have_passed_never_change(db_session, stew):
    meal_plan = plan(db_session)
    sunday = WEEK[1]

    for change in (
        lambda: set_meal(db_session, meal_plan, WEEK[0], stew, 2, today=sunday, prices=PRICES),
        lambda: clear_meal(db_session, meal_plan, WEEK[0], today=sunday, prices=PRICES),
        lambda: set_leftovers(db_session, meal_plan, WEEK[0], WEEK[2], today=sunday, prices=PRICES),
    ):
        with pytest.raises(PlanRefused, match="passed"):
            change()
    set_meal(db_session, meal_plan, sunday, stew, 2, today=sunday, prices=PRICES)


def test_a_recipe_may_not_repeat_within_three_weeks(db_session, stew):
    this_week = plan(db_session)
    set_meal(db_session, this_week, WEEK[0], stew, 2, today=TODAY, prices=PRICES)
    two_weeks_on = start_meal_plan(db_session, SATURDAY + timedelta(weeks=2), now=NOW)
    three_weeks_on = start_meal_plan(db_session, SATURDAY + timedelta(weeks=3), now=NOW)

    with pytest.raises(PlanRefused, match="3 weeks"):
        set_meal(db_session, this_week, WEEK[3], stew, 2, today=TODAY, prices=PRICES)
    with pytest.raises(PlanRefused, match="3 weeks"):
        set_meal(
            db_session, two_weeks_on, two_weeks_on.week_start, stew, 2, today=TODAY, prices=PRICES
        )
    set_meal(
        db_session, three_weeks_on, three_weeks_on.week_start, stew, 2, today=TODAY, prices=PRICES
    )


def test_leftovers_are_of_an_earlier_meal_cooked_from_a_recipe(db_session, stew):
    meal_plan = plan(db_session)
    set_meal(db_session, meal_plan, WEEK[0], stew, 4, today=TODAY, prices=PRICES)

    summary = set_leftovers(db_session, meal_plan, WEEK[1], WEEK[0], today=TODAY, prices=PRICES)

    assert (summary.days[1].leftovers_of, summary.days[1].servings) == (WEEK[0], 2)
    with pytest.raises(PlanRefused, match="earlier"):
        set_leftovers(db_session, meal_plan, WEEK[2], WEEK[3], today=TODAY, prices=PRICES)
    with pytest.raises(PlanRefused, match="no Meal"):
        set_leftovers(db_session, meal_plan, WEEK[4], WEEK[2], today=TODAY, prices=PRICES)


def test_leftovers_of_leftovers_are_of_the_meal_that_was_cooked(db_session, stew):
    meal_plan = plan(db_session)
    set_meal(db_session, meal_plan, WEEK[0], stew, 2, today=TODAY, prices=PRICES)
    set_leftovers(db_session, meal_plan, WEEK[1], WEEK[0], servings=1, today=TODAY, prices=PRICES)

    summary = set_leftovers(
        db_session, meal_plan, WEEK[2], WEEK[1], servings=1, today=TODAY, prices=PRICES
    )

    assert summary.days[2].leftovers_of == WEEK[0]


def test_clearing_a_cooked_meal_leaves_its_leftovers_days_unfilled(db_session, stew):
    meal_plan = plan(db_session)
    set_meal(db_session, meal_plan, WEEK[0], stew, 2, today=TODAY, prices=PRICES)
    set_leftovers(db_session, meal_plan, WEEK[1], WEEK[0], today=TODAY, prices=PRICES)

    summary = clear_meal(db_session, meal_plan, WEEK[0], today=TODAY, prices=PRICES)

    assert [d.kind for d in summary.days[:2]] == ["empty", "unfilled"]


def test_finishing_a_draft_needs_every_day_filled_or_deliberately_empty(db_session, stew):
    meal_plan = plan(db_session)
    fill(db_session, meal_plan, leaving_out=[WEEK[5]])
    clear_meal(db_session, meal_plan, WEEK[3], today=TODAY, prices=PRICES)

    with pytest.raises(PlanRefused, match="2026-10-22"):
        finish_draft(db_session, meal_plan, now=NOW, prices=PRICES)
    with pytest.raises(PlanRefused, match="2026-10-22"):
        accept_meal_plan(db_session, meal_plan, now=NOW, prices=PRICES)

    clear_meal(db_session, meal_plan, WEEK[5], today=TODAY, prices=PRICES)
    summary = finish_draft(db_session, meal_plan, now=NOW, prices=PRICES)
    assert summary.complete and meal_plan.drafted_at == NOW


def test_accepting_is_one_way(db_session, stew):
    meal_plan = plan(db_session)
    fill(db_session, meal_plan)

    accept_meal_plan(db_session, meal_plan, now=NOW, prices=PRICES)

    assert (meal_plan.status, meal_plan.accepted_at) == (PlanStatus.ACCEPTED, NOW)
    with pytest.raises(PlanRefused, match="accepted"):
        finish_draft(db_session, meal_plan, now=NOW, prices=PRICES)
    # Accepting freezes nothing: the days ahead still change.
    clear_meal(db_session, meal_plan, WEEK[6], today=TODAY, prices=PRICES)


def test_the_store_is_set_on_the_plan(db_session):
    meal_plan = plan(db_session)

    summary = set_store(db_session, meal_plan, Store.JUMBO, today=TODAY, prices=PRICES)

    assert summary.store == Store.JUMBO


def test_household_size_changes_do_not_change_a_started_plan(db_session):
    meal_plan = plan(db_session, people=2)

    set_household(db_session, people=4)

    assert meal_plan.people == 2
