"""`tag_deals`: the match model links Deals to Ingredients or marks them non-food."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from fakes import FakeChatModel, tool_call
from sqlalchemy import select

from pickled.deals import (
    Channel,
    Deal,
    DealIngredient,
    DealProductRecord,
    DealRecord,
    FetchResult,
    deals_by_ingredient,
    save_fetch,
    tag_deals,
)
from pickled.ingredients import Aisle, Ingredient
from pickled.stores import Store

AMSTERDAM = ZoneInfo("Europe/Amsterdam")
MONDAY = date(2026, 10, 12)
SUNDAY = date(2026, 10, 18)
NOW = datetime(2026, 10, 12, 7, 0, tzinfo=AMSTERDAM)


def record(source_id, title, **fields) -> DealRecord:
    values = dict(
        source_id=source_id,
        title=title,
        discount_text="25% korting",
        valid_from=MONDAY,
        valid_to=SUNDAY,
        channel=Channel.BOTH,
    )
    return DealRecord(**(values | fields))


def store_deals(session, *records, store=Store.AH, on=MONDAY) -> dict[str, int]:
    """Store `records` as one fetch, and return each Deal's id by its title."""
    save_fetch(session, FetchResult(store=store, on=on, raw={}, deals=list(records)), now=NOW)
    return {deal.title: deal.id for deal in deals_of(session, store)}


def deals_of(session, store):
    return session.scalars(select(Deal).where(Deal.store == store).order_by(Deal.id)).all()


def tags(*deals) -> FakeChatModel:
    """A fake match model whose replies tag `deals`, one list of tags per call."""
    return FakeChatModel(replies=[tool_call("DealTags", {"deals": batch}) for batch in deals])


def food(deal_id, *ingredients) -> dict:
    return {"deal": deal_id, "non_food": False, "ingredients": list(ingredients)}


def non_food(deal_id) -> dict:
    return {"deal": deal_id, "non_food": True, "ingredients": []}


def ingredient(name, aisle=Aisle.GROENTE_FRUIT, **fields) -> dict:
    return {"name": name, "aisle": aisle.value} | fields


def links(session) -> set[tuple[str, str | None]]:
    rows = session.scalars(select(DealIngredient)).all()
    return {(row.deal.title, row.ingredient.name if row.ingredient else None) for row in rows}


@pytest.fixture
def catalogue(db_session):
    db_session.add_all(
        [
            Ingredient(name="kipfilet", aliases=["kipborstfilet"], aisle=Aisle.VLEES_VIS_VEGA),
            Ingredient(name="rode kool", aliases=["rodekool"], aisle=Aisle.GROENTE_FRUIT),
        ]
    )
    db_session.flush()
    return db_session


def test_deals_are_linked_to_ingredients_through_the_lookup(catalogue, sessions):
    ids = store_deals(catalogue, record("1", "AH Kipborstfilet"), record("2", "Rodekool"))
    model = tags(
        [
            food(ids["AH Kipborstfilet"], ingredient("kipborstfilet", Aisle.VLEES_VIS_VEGA)),
            food(ids["Rodekool"], ingredient("Rode-kool")),
        ]
    )

    tag_deals(sessions, Store.AH, model, on=MONDAY, now=NOW)

    assert links(catalogue) == {("AH Kipborstfilet", "kipfilet"), ("Rodekool", "rode kool")}
    assert catalogue.scalar(select(Ingredient.id).where(Ingredient.name == "rodekool")) is None


def test_a_deal_can_link_to_several_ingredients(catalogue, sessions):
    ids = store_deals(catalogue, record("1", "Alle AH kip en rode kool"))
    model = tags(
        [
            food(
                ids["Alle AH kip en rode kool"],
                ingredient("kipfilet", Aisle.VLEES_VIS_VEGA),
                ingredient("rode kool"),
            )
        ]
    )

    tag_deals(sessions, Store.AH, model, on=MONDAY, now=NOW)

    assert links(catalogue) == {
        ("Alle AH kip en rode kool", "kipfilet"),
        ("Alle AH kip en rode kool", "rode kool"),
    }


def test_an_ingredient_the_catalogue_lacks_is_created_with_what_the_model_says(catalogue, sessions):
    ids = store_deals(catalogue, record("1", "Hollandse pastinaak"))
    model = tags(
        [
            food(
                ids["Hollandse pastinaak"],
                ingredient("pastinaak", keeps_days=10, grams_per_piece=150),
            )
        ]
    )

    tag_deals(sessions, Store.AH, model, on=MONDAY, now=NOW)

    created = catalogue.scalars(select(Ingredient).where(Ingredient.name == "pastinaak")).one()
    assert (created.aisle, created.pantry, created.keeps_days) == (Aisle.GROENTE_FRUIT, False, 10)
    assert created.grams_per_piece == 150
    assert links(catalogue) == {("Hollandse pastinaak", "pastinaak")}


def test_a_non_food_deal_is_marked_and_linked_to_no_ingredient(catalogue, sessions):
    ids = store_deals(catalogue, record("1", "Robijn wasmiddel"))

    tag_deals(sessions, Store.AH, tags([non_food(ids["Robijn wasmiddel"])]), on=MONDAY, now=NOW)

    assert links(catalogue) == {("Robijn wasmiddel", None)}


def test_deals_go_to_the_model_in_batches(catalogue, sessions):
    ids = store_deals(catalogue, *(record(str(n), f"Deal {n}") for n in range(5)))
    model = tags(
        [non_food(ids["Deal 0"]), non_food(ids["Deal 1"])],
        [non_food(ids["Deal 2"]), non_food(ids["Deal 3"])],
        [non_food(ids["Deal 4"])],
    )

    tag_deals(sessions, Store.AH, model, on=MONDAY, now=NOW, batch_size=2)

    assert len(model.sent) == 3
    assert len(links(catalogue)) == 5


def test_a_tagged_deal_is_not_sent_again(catalogue, sessions):
    ids = store_deals(catalogue, record("1", "Robijn wasmiddel"))
    tag_deals(sessions, Store.AH, tags([non_food(ids["Robijn wasmiddel"])]), on=MONDAY, now=NOW)
    again = tags()

    tag_deals(sessions, Store.AH, again, on=MONDAY, now=NOW)

    assert again.sent == []


def test_only_the_stores_current_deals_are_tagged(catalogue, sessions):
    store_deals(catalogue, record("1", "Jumbo kipfilet"), store=Store.JUMBO)
    store_deals(
        catalogue,
        record("2", "Vorige week", valid_from=date(2026, 10, 5), valid_to=date(2026, 10, 11)),
        on=date(2026, 10, 5),
    )
    model = tags()

    tag_deals(sessions, Store.AH, model, on=MONDAY, now=NOW)

    assert model.sent == []


def test_a_deal_the_model_leaves_out_stays_untagged_and_is_not_asked_again_this_run(
    catalogue, sessions
):
    ids = store_deals(catalogue, record("1", "Robijn wasmiddel"), record("2", "Iets vaags"))
    model = tags([non_food(ids["Robijn wasmiddel"]), non_food(999_999)])

    tag_deals(sessions, Store.AH, model, on=MONDAY, now=NOW)

    assert links(catalogue) == {("Robijn wasmiddel", None)}
    assert len(model.sent) == 1


def test_a_food_deal_without_ingredients_stays_untagged(catalogue, sessions):
    ids = store_deals(catalogue, record("1", "Iets vaags"))

    tag_deals(sessions, Store.AH, tags([food(ids["Iets vaags"])]), on=MONDAY, now=NOW)

    assert links(catalogue) == set()


def test_the_model_sees_each_deal_its_products_and_the_catalogue(catalogue, sessions):
    product = DealProductRecord(sku="wi1", title="AH Kipfilet 300 g")
    ids = store_deals(
        catalogue, record("1", "AH Kipfilet", category="Vlees, kip, vis", products=(product,))
    )
    model = tags([food(ids["AH Kipfilet"], ingredient("kipfilet", Aisle.VLEES_VIS_VEGA))])

    tag_deals(sessions, Store.AH, model, on=MONDAY, now=NOW)

    prompt = "\n".join(message.text for message in model.sent[0])
    assert f"[{ids['AH Kipfilet']}] AH Kipfilet" in prompt
    assert "Vlees, kip, vis" in prompt and "AH Kipfilet 300 g" in prompt
    assert "kipfilet" in prompt and "rode kool" in prompt


def test_deals_by_ingredient_groups_the_tagged_deals_valid_on_a_date(catalogue, sessions):
    ids = store_deals(
        catalogue,
        record("1", "AH Kipfilet"),
        record("2", "Kip online", channel=Channel.ONLINE),
        record("3", "Robijn wasmiddel"),
        record("4", "Rodekool"),
    )
    jumbo = store_deals(catalogue, record("5", "Jumbo kipfilet"), store=Store.JUMBO)
    chicken = ingredient("kipfilet", Aisle.VLEES_VIS_VEGA)
    tag_deals(
        sessions,
        Store.AH,
        tags(
            [
                food(ids["AH Kipfilet"], chicken),
                food(ids["Kip online"], chicken),
                non_food(ids["Robijn wasmiddel"]),
                food(ids["Rodekool"], ingredient("rode kool")),
            ]
        ),
        on=MONDAY,
        now=NOW,
    )
    tag_deals(
        sessions, Store.JUMBO, tags([food(jumbo["Jumbo kipfilet"], chicken)]), on=MONDAY, now=NOW
    )

    found = deals_by_ingredient(catalogue, date(2026, 10, 14))
    ah_only = deals_by_ingredient(catalogue, date(2026, 10, 14), store=Store.AH)

    assert {i.name: [d.title for d in deals] for i, deals in found.items()} == {
        "kipfilet": ["AH Kipfilet", "Jumbo kipfilet"],
        "rode kool": ["Rodekool"],
    }
    assert {i.name: [d.title for d in deals] for i, deals in ah_only.items()} == {
        "kipfilet": ["AH Kipfilet"],
        "rode kool": ["Rodekool"],
    }
    assert deals_by_ingredient(catalogue, date(2026, 10, 19)) == {}
