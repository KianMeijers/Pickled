"""The agent's system prompt: what it knows about the Household and the week (spec §7)."""

from planning_helpers import NOW, SATURDAY, TODAY, deal, ingredient, plan

from pickled.agent import system_prompt
from pickled.ingredients import Aisle
from pickled.seasonal import Freshness, SeasonalProduce
from pickled.stores import Store
from pickled.taste import Author, FoodGoalKind, add_taste_note, set_food_goal


def test_the_prompt_gives_the_household_its_taste_notes_goals_and_week(db_session):
    meal_plan = plan(db_session, people=3)
    mine = add_taste_note(db_session, "Houdt niet van koriander", Author.USER, now=NOW)
    learnt = add_taste_note(db_session, "Eet graag pittig", Author.AGENT, now=NOW)
    set_food_goal(db_session, FoodGoalKind.PROTEIN_G_PER_DAY, min=100, now=NOW)

    prompt = system_prompt(db_session, meal_plan, today=TODAY)

    assert "3 people" in prompt
    assert f"[{mine.id}] (written by the Household) Houdt niet van koriander" in prompt
    assert f"[{learnt.id}] (written by you) Eet graag pittig" in prompt
    assert "protein g per person per day min 100" in prompt
    assert f"Saturday {SATURDAY}" in prompt
    assert "Friday 2026-10-23" in prompt
    assert f"Today is Thursday {TODAY}" in prompt


def in_season(session, name, month, freshness=Freshness.FRESH):
    produce = ingredient(session, name, Aisle.GROENTE_FRUIT)
    session.add(SeasonalProduce(ingredient=produce, month=month, freshness=freshness))
    session.flush()


def test_the_prompt_lists_the_seasonal_ingredients_of_the_weeks_month(db_session):
    meal_plan = plan(db_session)
    in_season(db_session, "pompoen", 10)
    in_season(db_session, "appel", 10, Freshness.STORED)
    in_season(db_session, "asperge", 5)

    prompt = system_prompt(db_session, meal_plan, today=TODAY)

    assert "Seasonal Ingredients in October: pompoen (fresh), appel (stored)" in prompt
    assert "asperge" not in prompt


def test_the_prompt_says_when_there_is_no_seasonal_produce(db_session):
    prompt = system_prompt(db_session, plan(db_session), today=TODAY)

    assert "Seasonal Ingredients in October: unknown" in prompt


def test_the_deal_table_gives_each_stores_best_discount_on_an_ingredient(db_session):
    meal_plan = plan(db_session)
    kipfilet = ingredient(db_session, "kipfilet", Aisle.VLEES_VIS_VEGA)
    prei = ingredient(db_session, "prei", Aisle.GROENTE_FRUIT)
    deal(db_session, Store.AH, kipfilet, "10% korting")
    deal(db_session, Store.AH, kipfilet, "2e halve prijs")
    deal(db_session, Store.JUMBO, kipfilet, "35% korting")
    deal(db_session, Store.JUMBO, prei, "Bonus")

    prompt = system_prompt(db_session, meal_plan, today=TODAY)

    assert "- kipfilet: AH 2e halve prijs (25% off); Jumbo 35% korting (35% off)\n" in prompt
    assert "- prei: Jumbo Bonus\n" in prompt
    assert prompt.index("- kipfilet") < prompt.index("- prei")


def test_the_deal_table_keeps_the_100_best_discounts(db_session):
    meal_plan = plan(db_session)
    for n in range(100):
        deal(db_session, Store.AH, ingredient(db_session, f"product {n}"), "40% korting")
    deal(db_session, Store.JUMBO, ingredient(db_session, "kaas"), "10% korting")

    prompt = system_prompt(db_session, meal_plan, today=TODAY)

    assert prompt.count("AH 40% korting (40% off)") == 100
    assert "kaas" not in prompt
