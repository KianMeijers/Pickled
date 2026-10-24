"""The plan summary as compact text, the form tool results give the agent."""

from planning_helpers import NOW, TODAY, WEEK, FakePrices, cents, deal, ingredient, plan, recipe

from pickled.ingredients import Aisle
from pickled.planning import clear_meal, set_leftovers, set_meal, set_store
from pickled.stores import Store
from pickled.taste import FoodGoalKind, set_food_goal


def test_the_text_shows_days_costs_goals_warnings_and_the_shopping_list(db_session):
    kipfilet = ingredient(db_session, "kipfilet", Aisle.VLEES_VIS_VEGA, keeps_days=2)
    ingredient(db_session, "rijst", Aisle.VOORRAAD)
    ingredient(db_session, "zout", Aisle.VOORRAAD, pantry=True)
    deal(db_session, Store.AH, kipfilet, "25% korting")
    set_food_goal(db_session, FoodGoalKind.BUDGET_CENTS_PER_WEEK, max=cents("50.00"), now=NOW)
    chicken = recipe(
        db_session,
        "Kip met rijst",
        ("kipfilet", 300, "g"),
        ("rijst", 150, "g"),
        ("zout", None, "to_taste"),
    )
    prices = FakePrices().set("kipfilet", Store.AH, cents("6.00"), "500 g")
    prices.set("rijst", Store.AH, cents("2.00"), "1 kg", rough=True)
    prices.set("kipfilet", Store.JUMBO, cents("5.00"), "500 g")
    meal_plan = plan(db_session)
    set_store(db_session, meal_plan, Store.AH, today=TODAY, prices=prices)
    set_meal(db_session, meal_plan, WEEK[3], chicken, 2, today=TODAY, prices=prices)
    set_leftovers(db_session, meal_plan, WEEK[4], WEEK[3], today=TODAY, prices=prices)

    text = clear_meal(db_session, meal_plan, WEEK[6], today=TODAY, prices=prices).text()

    # Each Meal uses 300 g kipfilet (€2.70 on the Deal at AH, €3.00 at Jumbo) and 150 g rijst
    # (€0.30 at AH, a rough price, and none at Jumbo). Zout is to taste, so costs nothing.
    assert text == "\n".join(
        [
            "Meal Plan 2026-10-17 to 2026-10-23: draft (partial), store AH, 2 people",
            "Days:",
            "  Sat 2026-10-17: not filled",
            "  Sun 2026-10-18: not filled",
            "  Mon 2026-10-19: not filled",
            f"  Tue 2026-10-20: Kip met rijst (recipe {chicken.id}), 2 servings:"
            " AH ≈ €3.00, Jumbo ≈ €3.00",
            f"  Wed 2026-10-21: leftovers of 2026-10-20, Kip met rijst (recipe {chicken.id}),"
            " 2 servings: AH ≈ €3.00, Jumbo ≈ €3.00",
            "  Thu 2026-10-22: not filled",
            "  Fri 2026-10-23: left empty",
            "Shopping cost: AH ≈ €11.00, 1 item estimated; Jumbo ≈ €10.00, 1 item unpriced",
            "Meal cost: AH ≈ €6.00; Jumbo ≈ €6.00",
            "Food Goals:",
            "  budget max €50.00: €11.00, met",
            "Warnings:",
            "  - kipfilet keeps 2 days from the Shopping Day, but Kip met rijst on 2026-10-20 is"
            " 3 days after it: cook it earlier in the week.",
            "  - rijst's price is estimated.",
            "Shopping List (AH):",
            "  vlees_vis_vega: kipfilet 600 g, 2 packs €9.00 [Deal: 25% korting]",
            "  voorraad: rijst 300 g, 1 pack ≈ €2.00",
            "  check you have: zout",
        ]
    )
