"""The settings page: the Household size, Food Goals, Taste notes and LLM-kosten (spec §8, §9)."""

import re
from datetime import datetime
from decimal import Decimal

import pytest
from planning_helpers import AMSTERDAM, NOW, plan
from test_web import Web

from pickled.llm import LlmBalance, LlmCall, Role
from pickled.taste import (
    Author,
    FoodGoalKind,
    active_food_goals,
    active_taste_notes,
    add_taste_note,
    household,
    set_food_goal,
    set_household,
)


@pytest.fixture
def web(sessions):
    return Web(sessions)


def test_settings_show_the_household_its_food_goals_and_who_wrote_each_taste_note(db_session, web):
    set_household(db_session, people=3)
    set_food_goal(db_session, FoodGoalKind.BUDGET_CENTS_PER_WEEK, max=7000, now=NOW)
    set_food_goal(db_session, FoodGoalKind.VEGETARIAN_DAYS_PER_WEEK, min=2, now=NOW)
    add_taste_note(db_session, "Geen spruitjes.", Author.USER, now=NOW)
    add_taste_note(db_session, "Houdt van pittig.", Author.AGENT, now=NOW)

    page = web.client.get("/instellingen")

    assert page.status_code == 200
    assert 'name="people" value="3"' in page.text
    assert 'name="budget_euros" value="70"' in page.text
    assert 'name="vegetarian_days" value="2"' in page.text
    assert "Geen spruitjes." in page.text
    assert "Houdt van pittig." in page.text
    assert page.text.index("door jou") < page.text.index("door Pickled")


def call(session, usd, role, *, at=NOW, meal_plan_id=None, job=None):
    session.add(
        LlmCall(
            called_at=at,
            role=role,
            model="claude-sonnet-5-5",
            job=job,
            meal_plan_id=meal_plan_id,
            input_tokens=0,
            cache_write_tokens=0,
            cache_read_tokens=0,
            output_tokens=0,
            cost_usd=Decimal(usd),
        )
    )
    session.flush()


def balance(session, usd, at):
    session.add(LlmBalance(checked_at=at, balance_usd=Decimal(usd)))
    session.flush()


def costs(page_text: str) -> str:
    """The LLM-kosten section as text, without its tags and with its whitespace squashed."""
    section = page_text[page_text.index("LLM-kosten") :]
    return " ".join(re.sub(r"<[^>]+>", " ", section).split())


SEPTEMBER = datetime(2026, 9, 20, 12, 0, tzinfo=AMSTERDAM)


def test_llm_costs_show_this_and_last_months_spend_by_role(db_session, web):
    set_household(db_session, people=2)
    call(db_session, "1.50", Role.CHAT)
    call(db_session, "2.25", Role.DRAFT)
    call(db_session, "0.40", Role.CHAT, at=SEPTEMBER)

    text = costs(web.client.get("/instellingen").text)

    assert "chat $ 1,50 $ 0,40" in text
    assert "draft $ 2,25 $ 0,00" in text
    assert "Totaal $ 3,75 $ 0,40" in text


def test_llm_costs_show_the_spend_per_meal_plan_week(db_session, web):
    meal_plan = plan(db_session)
    call(db_session, "2", Role.DRAFT, meal_plan_id=meal_plan.id)
    call(db_session, "0.5", Role.CHAT, meal_plan_id=meal_plan.id)

    text = costs(web.client.get("/instellingen").text)

    assert "zaterdag 17 okt $ 2,50" in text


def test_llm_costs_show_the_balance_and_the_cap(db_session, web):
    set_household(db_session, people=2)
    balance(db_session, "12.30", at=datetime(2026, 10, 15, 8, 0, tzinfo=AMSTERDAM))

    text = costs(web.client.get("/instellingen").text)

    assert "Tegoed bij Runware $ 12,30 (donderdag 15 okt)" in text
    assert "Maandbudget $ 25,00" in text


def test_llm_costs_compare_the_drop_in_balance_with_the_recorded_spend(db_session, web):
    set_household(db_session, people=2)
    balance(db_session, "20", at=datetime(2026, 10, 1, 8, 0, tzinfo=AMSTERDAM))
    balance(db_session, "15.50", at=datetime(2026, 10, 15, 8, 0, tzinfo=AMSTERDAM))
    call(db_session, "4", Role.DRAFT, at=datetime(2026, 10, 5, 18, 0, tzinfo=AMSTERDAM))
    # Eval calls count here, since they come off the balance too.
    call(db_session, "0.25", Role.EVAL_JUDGE, at=datetime(2026, 10, 6, 18, 0, tzinfo=AMSTERDAM))

    text = costs(web.client.get("/instellingen").text)

    assert "Afname van het tegoed $ 4,50" in text
    assert "Volgens Pickled $ 4,25" in text
    assert "Verschil $ 0,25" in text


def test_the_household_size_and_food_goals_can_be_changed_and_a_blank_goal_cleared(db_session, web):
    set_household(db_session, people=2)
    set_food_goal(db_session, FoodGoalKind.VEGETARIAN_DAYS_PER_WEEK, min=2, now=NOW)

    response = web.client.post(
        "/instellingen/huishouden",
        data={"people": "4", "budget_euros": "82,50", "vegetarian_days": "", "protein_g": "30"},
    )

    assert response.headers["HX-Refresh"] == "true"
    db_session.expire_all()
    assert household(db_session).people == 4
    assert {(goal.kind, goal.min, goal.max) for goal in active_food_goals(db_session)} == {
        (FoodGoalKind.BUDGET_CENTS_PER_WEEK, None, Decimal(8250)),
        (FoodGoalKind.PROTEIN_G_PER_DAY, Decimal(30), None),
    }


def test_the_household_adds_a_taste_note_as_theirs(db_session, web):
    set_household(db_session, people=2)

    web.client.post("/instellingen/smaak", data={"text": "Geen koriander."})

    [note] = active_taste_notes(db_session)
    assert (note.text, note.author) == ("Geen koriander.", Author.USER)


def test_a_note_the_household_rewrites_becomes_theirs(db_session, web):
    set_household(db_session, people=2)
    note = add_taste_note(db_session, "Houdt van pittig.", Author.AGENT, now=NOW)

    web.client.post(f"/instellingen/smaak/{note.id}", data={"text": "Houdt van heel pittig."})

    db_session.expire_all()
    [rewritten] = active_taste_notes(db_session)
    assert (rewritten.text, rewritten.author) == ("Houdt van heel pittig.", Author.USER)


def test_the_household_archives_a_taste_note(db_session, web):
    set_household(db_session, people=2)
    note = add_taste_note(db_session, "Houdt van pittig.", Author.AGENT, now=NOW)

    web.client.post(f"/instellingen/smaak/{note.id}/weg")

    db_session.expire_all()
    assert active_taste_notes(db_session) == []


def test_a_note_over_two_hundred_characters_is_refused_in_dutch(db_session, web):
    set_household(db_session, people=2)

    response = web.client.post("/instellingen/smaak", data={"text": "x" * 201})

    assert response.status_code == 422
    assert "200 tekens" in response.text
    assert active_taste_notes(db_session) == []
