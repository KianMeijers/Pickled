"""The plan summary: the Shopping List, meal and shopping costs, Food Goal checks and warnings."""

from datetime import timedelta

import pytest
from fakes import FakeChatModel
from planning_helpers import NOW, TODAY, WEEK, FakePrices, cents, deal, ingredient, plan, recipe

from pickled.deals import Channel
from pickled.ingredients import (
    Aisle,
    PriceObservation,
    PriceSource,
    Product,
    ProductPicker,
    find_ingredient,
)
from pickled.planning import (
    add_shopping_item,
    picked_prices,
    plan_summary,
    set_leftovers,
    set_meal,
    set_store,
    tick_shopping_item,
)
from pickled.stores import Store


def shopping(summary):
    """The Shopping List as (name, quantity, unit, packs, price cents)."""
    return [
        (line.name, line.quantity, line.unit, line.packs, line.price_cents)
        for line in summary.shopping_list
    ]


@pytest.fixture
def kip(db_session):
    ingredient(db_session, "kipfilet", Aisle.VLEES_VIS_VEGA)
    ingredient(db_session, "rijst", Aisle.VOORRAAD)
    return recipe(db_session, "Kip met rijst", ("kipfilet", 300, "g"), ("rijst", 150, "g"))


def test_the_shopping_list_buys_whole_packs_of_what_the_meals_use(db_session, kip):
    prices = FakePrices().set("kipfilet", Store.AH, cents("5.99"), "500 g")
    prices.set("rijst", Store.AH, cents("1.89"), "1 kg")
    meal_plan = plan(db_session)
    set_store(db_session, meal_plan, Store.AH, today=TODAY, prices=prices)

    summary = set_meal(db_session, meal_plan, WEEK[0], kip, 4, today=TODAY, prices=prices)

    assert shopping(summary) == [
        ("kipfilet", 600, "g", 2, cents("11.98")),
        ("rijst", 300, "g", 1, cents("1.89")),
    ]
    assert summary.costs[Store.AH].shopping_cents == cents("13.87")


def test_leftovers_grow_the_meal_that_was_cooked(db_session, kip):
    prices = FakePrices().set("kipfilet", Store.AH, cents("5.99"), "500 g")
    meal_plan = plan(db_session)
    set_store(db_session, meal_plan, Store.AH, today=TODAY, prices=prices)
    set_meal(db_session, meal_plan, WEEK[0], kip, 2, today=TODAY, prices=prices)

    summary = set_leftovers(
        db_session, meal_plan, WEEK[1], WEEK[0], servings=3, today=TODAY, prices=prices
    )

    assert shopping(summary)[0] == ("kipfilet", 750, "g", 2, cents("11.98"))


def test_pantry_items_are_listed_to_check_and_left_out_of_the_shopping_cost(db_session):
    ingredient(db_session, "pasta", Aisle.VOORRAAD)
    ingredient(db_session, "olijfolie", Aisle.VOORRAAD, pantry=True)
    pasta = recipe(db_session, "Pasta", ("pasta", 250, "g"), ("olijfolie", 2, "tbsp"))
    prices = FakePrices().set("pasta", Store.AH, cents("1.00"), "500 g")
    prices.set("olijfolie", Store.AH, cents("6.00"), "500 ml")
    meal_plan = plan(db_session)
    set_store(db_session, meal_plan, Store.AH, today=TODAY, prices=prices)

    summary = set_meal(db_session, meal_plan, WEEK[0], pasta, 2, today=TODAY, prices=prices)

    assert [(line.name, line.pantry) for line in summary.shopping_list] == [
        ("pasta", False),
        ("olijfolie", True),
    ]
    assert [line.name for line in summary.check_you_have] == ["olijfolie"]
    assert summary.costs[Store.AH].shopping_cents == cents("1.00")
    # The Meal uses half the pasta (€0.50) and 30 ml of the oil (€0.36).
    assert summary.days[0].meal_cents[Store.AH] == cents("0.86")


def test_meal_cost_is_what_each_meal_uses_at_both_stores(db_session, kip):
    prices = FakePrices().set("kipfilet", Store.AH, cents("6.00"), "500 g")
    prices.set("kipfilet", Store.JUMBO, cents("5.00"), "500 g")
    prices.set("rijst", Store.AH, cents("2.00"), "1 kg")
    prices.set("rijst", Store.JUMBO, cents("2.00"), "1 kg")
    meal_plan = plan(db_session)
    set_meal(db_session, meal_plan, WEEK[0], kip, 2, today=TODAY, prices=prices)

    summary = set_leftovers(
        db_session, meal_plan, WEEK[1], WEEK[0], servings=1, today=TODAY, prices=prices
    )

    # 2 servings use 300 g kipfilet and 150 g rijst; leftovers for 1 use half that.
    assert summary.days[0].meal_cents == {Store.AH: cents("3.90"), Store.JUMBO: cents("3.30")}
    assert summary.days[1].meal_cents == {Store.AH: cents("1.95"), Store.JUMBO: cents("1.65")}
    assert summary.costs[Store.AH].meal_cents == cents("5.85")
    assert summary.costs[Store.JUMBO].shopping_cents == cents("7.00")


def test_without_a_store_the_shopping_list_is_unpriced_but_costs_are_at_both(db_session, kip):
    prices = FakePrices().set("kipfilet", Store.AH, cents("6.00"), "500 g")
    meal_plan = plan(db_session)

    summary = set_meal(db_session, meal_plan, WEEK[0], kip, 2, today=TODAY, prices=prices)

    assert shopping(summary)[0] == ("kipfilet", 300, "g", None, None)
    assert summary.costs[Store.AH].shopping_cents == cents("6.00")
    assert meal_plan.est_cost_cents is None


def test_a_deal_at_the_store_prices_the_line_and_marks_it(db_session, kip):
    kipfilet = find_ingredient(db_session, "kipfilet")
    deal(db_session, Store.AH, kipfilet, "25% korting")
    deal(db_session, Store.JUMBO, kipfilet, "25% korting", channel=Channel.ONLINE)
    prices = FakePrices().set("kipfilet", Store.AH, cents("6.00"), "500 g")
    prices.set("kipfilet", Store.JUMBO, cents("6.00"), "500 g")
    meal_plan = plan(db_session)
    set_store(db_session, meal_plan, Store.AH, today=TODAY, prices=prices)

    summary = set_meal(db_session, meal_plan, WEEK[0], kip, 2, today=TODAY, prices=prices)

    line = summary.shopping_list[0]
    assert (line.price_cents, line.deal) == (cents("4.50"), "25% korting")
    # Jumbo's Deal is online only, and the Household shops in store.
    assert summary.costs[Store.JUMBO].shopping_cents == cents("6.00")


def test_a_fixed_price_deal_with_its_own_size_is_bought_in_its_packs(db_session, kip):
    kipfilet = find_ingredient(db_session, "kipfilet")
    deal(db_session, Store.AH, kipfilet, "voor 7.00", unit_size="1 kg")
    prices = FakePrices().set("kipfilet", Store.AH, cents("6.00"), "500 g")
    meal_plan = plan(db_session)
    set_store(db_session, meal_plan, Store.AH, today=TODAY, prices=prices)

    summary = set_meal(db_session, meal_plan, WEEK[0], kip, 4, today=TODAY, prices=prices)

    # 600 g: one 1 kg pack on the Deal beats two 500 g packs at €6.00.
    assert shopping(summary)[0] == ("kipfilet", 600, "g", 1, cents("7.00"))


def test_rough_and_missing_prices_are_counted(db_session):
    for name in ("ui", "prei", "wortel", "peterselie"):
        ingredient(db_session, name, Aisle.GROENTE_FRUIT)
    soup = recipe(
        db_session,
        "Soep",
        ("ui", 2, "piece"),
        ("prei", 1, "piece"),
        ("wortel", 300, "g"),
        ("peterselie", 10, "g"),
    )
    prices = FakePrices().set("ui", Store.AH, cents("1.00"), "1 kg", rough=True)
    prices.set("prei", Store.AH, cents("1.50"), "per bos")
    prices.set("wortel", Store.AH, cents("1.20"), "1 kg")
    meal_plan = plan(db_session)
    set_store(db_session, meal_plan, Store.AH, today=TODAY, prices=prices)

    summary = set_meal(db_session, meal_plan, WEEK[0], soup, 2, today=TODAY, prices=prices)

    # ui is an old price, prei's pack size says no amount, and peterselie has no price.
    costs = summary.costs[Store.AH]
    assert (costs.rough, costs.unpriced) == (2, 1)
    assert costs.shopping_cents == cents("3.70")
    assert [line.name for line in summary.shopping_list if line.rough] == ["prei", "ui"]


def test_pieces_are_bought_by_weight_when_the_ingredient_says_what_a_piece_weighs(db_session):
    ingredient(db_session, "ui", Aisle.GROENTE_FRUIT, grams_per_piece=150)
    soup = recipe(db_session, "Uiensoep", ("ui", 8, "piece"))
    prices = FakePrices().set("ui", Store.AH, cents("1.00"), "1 kg")
    meal_plan = plan(db_session)
    set_store(db_session, meal_plan, Store.AH, today=TODAY, prices=prices)

    summary = set_meal(db_session, meal_plan, WEEK[0], soup, 2, today=TODAY, prices=prices)

    assert shopping(summary)[0] == ("ui", 8, "piece", 2, cents("2.00"))
    assert summary.costs[Store.AH].rough == 0


def test_regenerating_the_list_keeps_manual_items_and_ticks_matched_by_name(db_session, kip):
    ingredient(db_session, "broccoli", Aisle.GROENTE_FRUIT)
    with_broccoli = recipe(
        db_session, "Kip met broccoli", ("kipfilet", 300, "g"), ("broccoli", 1, "piece")
    )
    prices = FakePrices()
    meal_plan = plan(db_session)
    set_meal(db_session, meal_plan, WEEK[0], kip, 2, today=TODAY, prices=prices)
    add_shopping_item(db_session, meal_plan, "wc-papier", 1, "pak", prices=prices)
    rice = next(
        line
        for line in plan_summary(db_session, meal_plan, prices=prices).shopping_list
        if line.name == "rijst"
    )
    chicken = next(
        line
        for line in plan_summary(db_session, meal_plan, prices=prices).shopping_list
        if line.name == "kipfilet"
    )
    tick_shopping_item(db_session, rice.id)
    tick_shopping_item(db_session, chicken.id)

    summary = set_meal(db_session, meal_plan, WEEK[0], with_broccoli, 2, today=TODAY, prices=prices)

    assert {(line.name, line.manual, line.checked) for line in summary.shopping_list} == {
        ("kipfilet", False, True),
        ("broccoli", False, False),
        ("wc-papier", True, False),
    }


def test_a_manual_item_goes_in_the_aisle_of_the_ingredient_it_names(db_session, kip):
    meal_plan = plan(db_session)

    summary = add_shopping_item(db_session, meal_plan, "Rijst", prices=FakePrices())

    assert [(line.name, line.aisle, line.manual) for line in summary.shopping_list] == [
        ("Rijst", "voorraad", True)
    ]


class UnchangedSource:
    """A store whose prices never need refreshing, and which sells nothing new."""

    def __init__(self, store):
        self.store = store
        self.price_source = PriceSource.AH_SEARCH
        self.refresh_after = timedelta(weeks=520)

    def shortlist(self, session, query):
        return []


def test_the_apps_prices_are_the_chosen_products_on_the_shopping_day(db_session, kip):
    kipfilet = find_ingredient(db_session, "kipfilet")
    product = Product(
        ingredient=kipfilet,
        store=Store.AH,
        sku="wi1",
        name="AH Kipfilet",
        pack_size="500 g",
        chosen_at=NOW,
    )
    product.price_observations.append(
        PriceObservation(price_cents=cents("5.99"), source=PriceSource.AH_SEARCH, observed_at=NOW)
    )
    db_session.add(product)
    picker = ProductPicker(
        {store: UnchangedSource(store) for store in Store}, FakeChatModel(replies=[])
    )
    meal_plan = plan(db_session)
    set_store(db_session, meal_plan, Store.AH, today=TODAY, prices=FakePrices())
    prices = picked_prices(db_session, meal_plan, picker)

    summary = set_meal(db_session, meal_plan, WEEK[0], kip, 2, today=TODAY, prices=prices)

    assert shopping(summary)[0] == ("kipfilet", 300, "g", 1, cents("5.99"))
    # Jumbo has no Product, so AH's price stands in for it, marked rough.
    assert summary.costs[Store.JUMBO].rough == 1
