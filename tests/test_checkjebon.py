"""Jumbo's regular prices from Checkjebon's daily `supermarkets.json` (#15).

The fixture is made up in Checkjebon's shape; Checkjebon's AH data is never used.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from pickled.ingredients import (
    CheckjebonError,
    CheckjebonJumboPriceSource,
    PriceSource,
    PricesUnavailable,
    ProductCandidate,
    checkjebon_stale,
    refresh_checkjebon,
)
from pickled.stores import Store

FIXTURE = Path(__file__).parent / "fixtures" / "checkjebon_made_up.json"
NOW = datetime(2026, 10, 15, 16, 0, tzinfo=ZoneInfo("Europe/Amsterdam"))


@pytest.fixture
def data():
    return json.loads(FIXTURE.read_text())


def jumbo_products(data) -> list:
    return next(store for store in data if store["n"] == "jumbo")["d"]


SOURCE = CheckjebonJumboPriceSource()


def test_a_refresh_loads_only_jumbo_and_the_shortlist_finds_its_products(db_session, data):
    summary = refresh_checkjebon(db_session, data, now=NOW)

    shortlist = SOURCE.shortlist(db_session, "kipfilet")

    assert (summary.products, summary.skipped, summary.changed) == (5, 1, True)
    assert {c.sku for c in shortlist} == {"596629KGR", "123456PAK", "555555PAK"}
    assert (
        ProductCandidate(
            "596629KGR",
            "Jumbo Kipfilet ca. 215 g",
            386,
            None,
            "https://www.jumbo.com/producten/jumbo-kipfilet-ca-215-g-596629KGR",
        )
        in shortlist
    )
    assert SOURCE.shortlist(db_session, "biologische kipfilet") != []
    assert SOURCE.shortlist(db_session, "kip filet") != []
    assert SOURCE.shortlist(db_session, "spruitjes") == []
    assert (SOURCE.store, SOURCE.price_source) == (Store.JUMBO, PriceSource.CHECKJEBON)


def test_the_shortlist_is_the_thirty_best_matches(db_session, data):
    jumbo_products(data).extend(
        {"n": f"Jumbo Kipfilet Variant {n}", "l": f"variant-{n}-{n}VAR", "p": 3.0, "s": ""}
        for n in range(40)
    )
    refresh_checkjebon(db_session, data, now=NOW)

    assert len(SOURCE.shortlist(db_session, "kipfilet")) == 30


def test_current_reads_a_products_price_by_its_sku(db_session, data):
    refresh_checkjebon(db_session, data, now=NOW)

    assert SOURCE.current(db_session, "777777ZK").price_cents == 129
    assert SOURCE.current(db_session, "000000XX") is None


def test_without_a_refresh_there_are_no_jumbo_prices(db_session):
    with pytest.raises(PricesUnavailable):
        SOURCE.shortlist(db_session, "kipfilet")
    with pytest.raises(PricesUnavailable):
        SOURCE.current(db_session, "596629KGR")


def test_a_refresh_with_new_data_replaces_the_copy(db_session, data):
    refresh_checkjebon(db_session, data, now=NOW)
    products = jumbo_products(data)
    products[:] = [p for p in products if "Plakjes" not in p["n"]]
    products[0]["p"] = 3.99

    summary = refresh_checkjebon(db_session, data, now=NOW + timedelta(days=1))

    assert summary.changed
    assert SOURCE.current(db_session, "596629KGR").price_cents == 399
    assert SOURCE.current(db_session, "123456PAK") is None


def test_data_unchanged_for_more_than_three_days_is_stale(db_session, data):
    refresh_checkjebon(db_session, data, now=NOW)

    three_days = refresh_checkjebon(db_session, data, now=NOW + timedelta(days=3))
    four_days = refresh_checkjebon(db_session, data, now=NOW + timedelta(days=4))

    assert (three_days.changed, three_days.stale) == (False, False)
    assert (four_days.changed, four_days.stale) == (False, True)
    assert checkjebon_stale(db_session)
    jumbo_products(data)[0]["p"] = 3.99
    refresh_checkjebon(db_session, data, now=NOW + timedelta(days=5))
    assert not checkjebon_stale(db_session)


def test_checkjebon_is_not_stale_before_its_first_refresh(db_session):
    assert not checkjebon_stale(db_session)


def test_changed_data_stays_fresh_until_a_later_refresh_finds_it_unchanged(db_session, data):
    """Refreshed weekly, the copy is days old between runs without being stale."""
    refresh_checkjebon(db_session, data, now=NOW - timedelta(days=7))
    jumbo_products(data)[0]["p"] = 3.99

    refresh_checkjebon(db_session, data, now=NOW)

    assert not checkjebon_stale(db_session)


@pytest.mark.parametrize(
    "broken",
    [
        lambda data: [store for store in data if store["n"] != "jumbo"],
        lambda data: [store | {"d": []} for store in data],
        lambda data: [store | {"d": [{"n": "kapot"}] * 10 + store["d"]} for store in data],
        lambda data: {"not": "a list"},
    ],
    ids=["no jumbo", "no products", "mostly broken", "wrong shape"],
)
def test_a_broken_download_is_refused_and_the_last_copy_kept(db_session, data, broken):
    refresh_checkjebon(db_session, data, now=NOW)

    with pytest.raises(CheckjebonError):
        refresh_checkjebon(db_session, broken(data), now=NOW + timedelta(days=1))

    assert SOURCE.current(db_session, "596629KGR").price_cents == 386


def test_among_names_containing_the_search_the_closest_come_first(db_session, data):
    jumbo_products(data).append(
        {"n": "Sheba Filets Kipfilet stukjes in saus kattenvoer 60 g", "l": "sheba-1CUP", "p": 1.69}
    )
    refresh_checkjebon(db_session, data, now=NOW)

    shortlist = SOURCE.shortlist(db_session, "kipfilet")

    assert [c.name.split()[0] for c in shortlist] == ["Jumbo", "Jumbo", "Jumbo", "Sheba"]
