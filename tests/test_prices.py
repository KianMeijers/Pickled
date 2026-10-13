"""`price_for` and `set_product`: an Ingredient's price at a store, through its chosen Product."""

import json
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fakes import FakeChatModel, tool_call
from sqlalchemy import select

from pickled.ingredients import (
    Aisle,
    Ingredient,
    PriceObservation,
    PriceSource,
    PricesUnavailable,
    Product,
    ProductCandidate,
    ProductPicker,
    open_product_picker,
    price_for,
    refresh_checkjebon,
    set_product,
)
from pickled.llm import LlmCall, Role
from pickled.stores import Store

AMSTERDAM = ZoneInfo("Europe/Amsterdam")
NOW = datetime(2026, 10, 15, 18, 0, tzinfo=AMSTERDAM)
SATURDAY = date(2026, 10, 17)


@pytest.fixture
def kipfilet(db_session):
    ingredient = Ingredient(name="kipfilet", aisle=Aisle.VLEES_VIS_VEGA)
    db_session.add(ingredient)
    db_session.flush()
    return ingredient


def chosen(session, ingredient, store, sku, *observations) -> Product:
    """A chosen Product with `observations` of (cents, source, observed_at)."""
    product = Product(
        ingredient=ingredient,
        store=store,
        sku=sku,
        name=f"Kipfilet {sku}",
        pack_size="500 g",
        chosen_at=NOW - timedelta(days=60),
    )
    for cents, source, observed_at in observations:
        product.price_observations.append(
            PriceObservation(price_cents=cents, source=source, observed_at=observed_at)
        )
    session.add(product)
    session.flush()
    return product


class FakeSource:
    """A store's regular prices: `listed` is what a search for any name finds."""

    def __init__(
        self, store, price_source, *listed, refresh_after=timedelta(weeks=4), available=True
    ):
        self.store = store
        self.price_source = price_source
        self.listed = list(listed)
        self.refresh_after = refresh_after
        self.available = available
        self.searched: list[str] = []

    def shortlist(self, session, query):
        if not self.available:
            raise PricesUnavailable(f"{self.store} is out of requests")
        self.searched.append(query)
        return self.listed

    def current(self, session, sku):
        if not self.available:
            raise PricesUnavailable(f"{self.store} is out of requests")
        return next((c for c in self.listed if c.sku == sku), None)


def ah(*listed, **options) -> FakeSource:
    return FakeSource(Store.AH, PriceSource.AH_SEARCH, *listed, **options)


def jumbo(*listed, **options) -> FakeSource:
    return FakeSource(Store.JUMBO, PriceSource.CHECKJEBON, *listed, **options)


SLICES = ProductCandidate("wi2", "AH Kipfilet plakjes", 229, "150 g")
FILLET = ProductCandidate("wi1", "AH Kipfilet", 599, "500 g", "https://www.ah.nl/producten/wi1")


def pick(sku, reason="plain and raw") -> object:
    return tool_call("ProductChoice", {"sku": sku, "reason": reason})


def picker(*sources, replies=(), now=NOW) -> ProductPicker:
    return ProductPicker(
        {source.store: source for source in sources},
        FakeChatModel(replies=list(replies)),
        clock=lambda: now,
    )


def test_a_chosen_products_latest_price_is_its_price(db_session, kipfilet):
    product = chosen(
        db_session,
        kipfilet,
        Store.AH,
        "wi1",
        (649, PriceSource.AH_SEARCH, NOW - timedelta(days=20)),
        (599, PriceSource.DEAL, NOW - timedelta(days=10)),
    )

    price = price_for(db_session, kipfilet, Store.AH, on=SATURDAY, picker=picker(ah()))

    assert (price.cents, price.product, price.product.store, price.rough) == (
        599,
        product,
        Store.AH,
        False,
    )


def test_a_price_older_than_eight_weeks_is_rough(db_session, kipfilet):
    on_the_edge = datetime(2026, 8, 22, 12, 0, tzinfo=AMSTERDAM)
    chosen(db_session, kipfilet, Store.AH, "wi1", (599, PriceSource.AH_SEARCH, on_the_edge))
    spent = picker(ah(available=False))
    fresh_enough = price_for(db_session, kipfilet, Store.AH, on=SATURDAY, picker=spent)

    too_old = price_for(
        db_session, kipfilet, Store.AH, on=SATURDAY + timedelta(days=1), picker=spent
    )

    assert (fresh_enough.rough, too_old.rough) == (False, True)


def test_a_current_deals_regular_price_beats_a_newer_checkjebon_price(db_session, kipfilet):
    wednesday = datetime(2026, 10, 14, 6, 0, tzinfo=AMSTERDAM)
    chosen(
        db_session,
        kipfilet,
        Store.JUMBO,
        "596629KGR",
        (449, PriceSource.DEAL, wednesday),
        (379, PriceSource.CHECKJEBON, NOW),
    )

    this_week = price_for(db_session, kipfilet, Store.JUMBO, on=SATURDAY, picker=picker(jumbo()))
    next_week = price_for(
        db_session, kipfilet, Store.JUMBO, on=SATURDAY + timedelta(days=7), picker=picker(jumbo())
    )

    assert (this_week.cents, next_week.cents) == (449, 379)


def test_the_match_model_picks_a_product_from_the_shortlist_the_first_time(db_session, kipfilet):
    source = ah(SLICES, FILLET)
    prices = picker(source, replies=[pick("wi1")])

    price = price_for(db_session, kipfilet, Store.AH, on=SATURDAY, picker=prices)
    again = price_for(db_session, kipfilet, Store.AH, on=SATURDAY, picker=prices)

    assert (price.cents, price.rough, again.cents) == (599, False, 599)
    product = db_session.scalars(select(Product)).one()
    assert (product.sku, product.name, product.pack_size, product.url, product.chosen_at) == (
        "wi1",
        "AH Kipfilet",
        "500 g",
        "https://www.ah.nl/producten/wi1",
        NOW,
    )
    assert [(o.price_cents, o.source) for o in product.price_observations] == [
        (599, PriceSource.AH_SEARCH)
    ]
    assert source.searched == ["kipfilet"]
    prompt = "\n".join(message.text for message in prices.model.sent[0])
    assert "kipfilet" in prompt and "[wi2] AH Kipfilet plakjes" in prompt and "€2.29" in prompt


def test_without_a_product_at_the_store_the_other_stores_price_is_used_as_rough(
    db_session, kipfilet
):
    jumbo_fillet = chosen(
        db_session, kipfilet, Store.JUMBO, "596629KGR", (386, PriceSource.CHECKJEBON, NOW)
    )
    prices = picker(ah(SLICES), jumbo(), replies=[pick(None, "only sliced chicken")])

    price = price_for(db_session, kipfilet, Store.AH, on=SATURDAY, picker=prices)

    assert (price.cents, price.product, price.product.store, price.rough) == (
        386,
        jumbo_fillet,
        Store.JUMBO,
        True,
    )


def test_with_no_product_at_either_store_there_is_no_price(db_session, kipfilet):
    prices = picker(ah(SLICES), jumbo(), replies=[pick(None)])

    assert price_for(db_session, kipfilet, Store.AH, on=SATURDAY, picker=prices) is None


def test_a_store_without_a_product_is_not_asked_again_for_four_weeks(db_session, kipfilet):
    source = ah(SLICES)
    price_for(
        db_session,
        kipfilet,
        Store.AH,
        on=SATURDAY,
        picker=picker(source, jumbo(), replies=[pick(None)]),
    )
    # In UTC: four weeks of Amsterdam wall-clock time cross the end of summer time.
    weeks_later = NOW.astimezone(UTC) + timedelta(weeks=4)

    price_for(
        db_session,
        kipfilet,
        Store.AH,
        on=SATURDAY,
        picker=picker(source, jumbo(), now=weeks_later - timedelta(minutes=1)),
    )
    later = picker(source, jumbo(), replies=[pick("wi2")], now=weeks_later)
    price = price_for(db_session, kipfilet, Store.AH, on=SATURDAY, picker=later)

    assert source.searched == ["kipfilet", "kipfilet"]
    assert price.cents == 229


def test_with_the_ah_budget_spent_the_jumbo_price_is_used_and_ah_is_asked_again_later(
    db_session, kipfilet
):
    chosen(db_session, kipfilet, Store.JUMBO, "596629KGR", (386, PriceSource.CHECKJEBON, NOW))
    spent = picker(ah(FILLET, available=False), jumbo())

    price = price_for(db_session, kipfilet, Store.AH, on=SATURDAY, picker=spent)
    later = price_for(
        db_session,
        kipfilet,
        Store.AH,
        on=SATURDAY,
        picker=picker(ah(FILLET), replies=[pick("wi1")]),
    )

    assert (price.product.store, price.cents, price.rough) == (Store.JUMBO, 386, True)
    assert (later.product.store, later.cents, later.rough) == (Store.AH, 599, False)


def test_a_price_older_than_the_sources_refresh_age_is_looked_up_again(db_session, kipfilet):
    old = NOW - timedelta(weeks=4, minutes=1)
    product = chosen(db_session, kipfilet, Store.AH, "wi1", (599, PriceSource.AH_SEARCH, old))
    risen = ProductCandidate("wi1", "AH Kipfilet", 629, "500 g")

    price = price_for(db_session, kipfilet, Store.AH, on=SATURDAY, picker=picker(ah(risen)))

    assert (price.cents, price.observed_at) == (629, NOW)
    assert [o.price_cents for o in product.price_observations] == [599, 629]


def test_a_price_within_the_refresh_age_is_not_looked_up(db_session, kipfilet):
    recent = NOW - timedelta(weeks=4, minutes=-1)
    chosen(db_session, kipfilet, Store.AH, "wi1", (599, PriceSource.AH_SEARCH, recent))
    risen = ProductCandidate("wi1", "AH Kipfilet", 629, "500 g")

    price = price_for(db_session, kipfilet, Store.AH, on=SATURDAY, picker=picker(ah(risen)))

    assert price.cents == 599


@pytest.mark.parametrize("source", [ah(available=False), ah(SLICES)], ids=["spent", "unlisted"])
def test_without_a_fresh_price_the_last_one_is_kept(db_session, kipfilet, source):
    old = NOW - timedelta(weeks=6)
    chosen(db_session, kipfilet, Store.AH, "wi1", (599, PriceSource.AH_SEARCH, old))

    price = price_for(db_session, kipfilet, Store.AH, on=SATURDAY, picker=picker(source))

    assert (price.cents, price.observed_at, price.rough) == (599, old, False)


def test_set_product_replaces_the_choice_with_the_one_the_hint_asks_for(db_session, kipfilet):
    first = chosen(db_session, kipfilet, Store.AH, "wi1", (599, PriceSource.AH_SEARCH, NOW))
    prices = picker(ah(SLICES, FILLET), replies=[pick("wi2", "the Household wants slices")])

    product = set_product(db_session, kipfilet, Store.AH, "de plakjes", picker=prices)
    price = price_for(db_session, kipfilet, Store.AH, on=SATURDAY, picker=prices)

    assert (product.sku, price.product, price.cents) == ("wi2", product, 229)
    assert first.replaced_at == NOW
    prompt = "\n".join(message.text for message in prices.model.sent[0])
    assert "de plakjes" in prompt and "Currently chosen: [wi1]" in prompt


def test_set_product_keeps_the_choice_if_nothing_fits_the_hint(db_session, kipfilet):
    first = chosen(db_session, kipfilet, Store.AH, "wi1", (599, PriceSource.AH_SEARCH, NOW))
    prices = picker(ah(SLICES, FILLET), replies=[pick(None)])

    assert set_product(db_session, kipfilet, Store.AH, "biologisch", picker=prices) is None
    assert first.replaced_at is None
    assert price_for(db_session, kipfilet, Store.AH, on=SATURDAY, picker=prices).product == first


def test_set_product_chooses_even_after_the_store_was_found_to_have_none(db_session, kipfilet):
    prices = picker(ah(SLICES), jumbo(), replies=[pick(None), pick("wi2")])
    price_for(db_session, kipfilet, Store.AH, on=SATURDAY, picker=prices)

    product = set_product(db_session, kipfilet, Store.AH, "plakjes zijn prima", picker=prices)

    assert price_for(db_session, kipfilet, Store.AH, on=SATURDAY, picker=prices).product == product


def test_the_app_picker_uses_the_match_model_as_pick_product(db_session, sessions, kipfilet):
    from test_checkjebon import FIXTURE as CHECKJEBON

    refresh_checkjebon(db_session, json.loads(CHECKJEBON.read_text()), now=NOW)
    fake = FakeChatModel(replies=[pick("596629KGR")])

    with open_product_picker(sessions, build=lambda name, settings: fake) as prices:
        price = price_for(db_session, kipfilet, Store.JUMBO, on=SATURDAY, picker=prices)

    assert price.cents == 386
    [call] = db_session.scalars(select(LlmCall))
    assert call.role is Role.PICK_PRODUCT
