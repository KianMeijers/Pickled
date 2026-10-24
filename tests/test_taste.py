"""The Household, Taste notes and Food Goals."""

from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from pickled.taste import (
    MAX_ACTIVE_NOTES,
    Author,
    FoodGoalKind,
    TasteRefused,
    active_food_goals,
    active_taste_notes,
    add_taste_note,
    archive_taste_note,
    clear_food_goal,
    household,
    set_food_goal,
    set_household,
    update_taste_note,
)

NOW = datetime(2026, 10, 15, 18, 0, tzinfo=ZoneInfo("Europe/Amsterdam"))


def test_there_is_no_household_until_one_is_set(db_session):
    assert household(db_session) is None


def test_setting_the_household_again_changes_the_one_household(db_session):
    set_household(db_session, people=2)
    set_household(db_session, people=3, name="Thuis")

    assert (household(db_session).people, household(db_session).name) == (3, "Thuis")


def test_a_household_cooks_for_at_least_one_person(db_session):
    with pytest.raises(TasteRefused):
        set_household(db_session, people=0)


def test_active_notes_leave_out_archived_ones_and_come_oldest_first(db_session):
    first = add_taste_note(db_session, "Houdt van pittig", Author.AGENT, now=NOW)
    gone = add_taste_note(db_session, "Lust geen vis", Author.USER, now=NOW + timedelta(1))
    last = add_taste_note(db_session, "Liever geen koriander", Author.AGENT, now=NOW + timedelta(2))
    archive_taste_note(db_session, gone.id, Author.USER, now=NOW + timedelta(3))

    assert [n.text for n in active_taste_notes(db_session)] == [first.text, last.text]


def test_a_note_longer_than_200_characters_is_refused(db_session):
    with pytest.raises(TasteRefused, match="200"):
        add_taste_note(db_session, "x" * 201, Author.AGENT, now=NOW)


def test_a_note_is_refused_once_the_taste_profile_is_full(db_session):
    for i in range(MAX_ACTIVE_NOTES):
        add_taste_note(db_session, f"Note {i}", Author.AGENT, now=NOW)

    with pytest.raises(TasteRefused, match="merge"):
        add_taste_note(db_session, "One too many", Author.AGENT, now=NOW)


def test_the_agent_can_rewrite_its_own_note(db_session):
    note = add_taste_note(db_session, "Houdt van pittig", Author.AGENT, now=NOW)

    update_taste_note(db_session, note.id, "Houdt van heel pittig", Author.AGENT, now=NOW)

    assert [n.text for n in active_taste_notes(db_session)] == ["Houdt van heel pittig"]


def test_the_agent_never_rewrites_or_archives_a_note_the_household_wrote(db_session):
    note = add_taste_note(db_session, "Lust geen vis", Author.USER, now=NOW)

    with pytest.raises(TasteRefused, match="Household wrote"):
        update_taste_note(db_session, note.id, "Lust wel zalm", Author.AGENT, now=NOW)
    with pytest.raises(TasteRefused, match="Household wrote"):
        archive_taste_note(db_session, note.id, Author.AGENT, now=NOW)
    assert [n.text for n in active_taste_notes(db_session)] == ["Lust geen vis"]


def test_the_household_can_rewrite_any_note_and_then_it_is_theirs(db_session):
    note = add_taste_note(db_session, "Houdt van pittig", Author.AGENT, now=NOW)

    update_taste_note(db_session, note.id, "Niet te pittig", Author.USER, now=NOW)

    assert active_taste_notes(db_session)[0].author == Author.USER


def test_setting_a_goal_replaces_the_active_one_of_its_kind(db_session):
    set_food_goal(db_session, FoodGoalKind.PROTEIN_G_PER_DAY, min=80, now=NOW)
    set_food_goal(db_session, FoodGoalKind.PROTEIN_G_PER_DAY, min=100, now=NOW)
    set_food_goal(db_session, FoodGoalKind.BUDGET_CENTS_PER_WEEK, max=6000, now=NOW)

    goals = {g.kind: (g.min, g.max) for g in active_food_goals(db_session)}
    assert goals == {
        FoodGoalKind.PROTEIN_G_PER_DAY: (Decimal(100), None),
        FoodGoalKind.BUDGET_CENTS_PER_WEEK: (None, Decimal(6000)),
    }


def test_a_cleared_goal_is_no_longer_active(db_session):
    set_food_goal(db_session, FoodGoalKind.KCAL_PER_DAY, min=1800, max=2200, now=NOW)

    clear_food_goal(db_session, FoodGoalKind.KCAL_PER_DAY, now=NOW)

    assert active_food_goals(db_session) == []


def test_a_goal_needs_a_bound_and_an_other_goal_needs_its_text(db_session):
    with pytest.raises(TasteRefused):
        set_food_goal(db_session, FoodGoalKind.KCAL_PER_DAY, now=NOW)
    with pytest.raises(TasteRefused):
        set_food_goal(db_session, FoodGoalKind.OTHER, now=NOW)
    with pytest.raises(TasteRefused):
        set_food_goal(db_session, FoodGoalKind.KCAL_PER_DAY, min=2200, max=1800, now=NOW)


def test_other_goals_are_kept_side_by_side(db_session):
    set_food_goal(db_session, FoodGoalKind.OTHER, text="Weinig zout", now=NOW)
    set_food_goal(db_session, FoodGoalKind.OTHER, text="Twee keer vis", now=NOW)

    assert {g.text for g in active_food_goals(db_session)} == {"Weinig zout", "Twee keer vis"}
