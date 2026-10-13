from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.exc import IntegrityError

from pickled.ingredients import Aisle, Ingredient, PriceObservation, PriceSource, Product
from pickled.stores import Store

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=ZoneInfo("Europe/Amsterdam"))


@pytest.fixture
def kipfilet(db_session):
    ingredient = Ingredient(name="kipfilet", aisle=Aisle.VLEES_VIS_VEGA)
    db_session.add(ingredient)
    db_session.flush()
    return ingredient


def product(ingredient, store, sku, replaced_at=None) -> Product:
    return Product(
        ingredient=ingredient,
        store=store,
        sku=sku,
        name=f"Kipfilet {sku}",
        pack_size="500 g",
        url=f"https://example.test/{sku}",
        chosen_at=NOW,
        replaced_at=replaced_at,
    )


def test_an_ingredient_has_at_most_one_chosen_product_per_store(db_session, kipfilet):
    db_session.add(product(kipfilet, Store.AH, "wi1"))
    db_session.add(product(kipfilet, Store.AH, "wi2"))

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_a_replaced_product_is_kept_alongside_the_new_choice(db_session, kipfilet):
    db_session.add(product(kipfilet, Store.AH, "wi1", replaced_at=NOW))
    db_session.add(product(kipfilet, Store.AH, "wi2"))
    db_session.add(product(kipfilet, Store.JUMBO, "123"))
    db_session.flush()


def test_a_price_observation_records_cents_source_and_time(db_session, kipfilet):
    chosen = product(kipfilet, Store.AH, "wi1")
    chosen.price_observations.append(
        PriceObservation(price_cents=599, source=PriceSource.AH_SEARCH, observed_at=NOW)
    )
    db_session.add(chosen)
    db_session.flush()
    db_session.expire_all()

    [observation] = db_session.get(Product, chosen.id).price_observations
    assert observation.price_cents == 599
    assert observation.source is PriceSource.AH_SEARCH
    assert observation.observed_at == NOW
