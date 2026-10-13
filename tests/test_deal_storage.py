"""Storing a fetch: upsert, withdraw, the failure thresholds, and `deals_valid_on`."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select

from pickled.deals import (
    Channel,
    Deal,
    DealFetch,
    DealProductRecord,
    DealRecord,
    DiscountKind,
    FetchRejected,
    FetchResult,
    deals_valid_on,
    save_fetch,
)
from pickled.ingredients import Aisle, Ingredient, PriceSource, Product
from pickled.stores import Store

AMSTERDAM = ZoneInfo("Europe/Amsterdam")
MONDAY = date(2026, 10, 12)
SUNDAY = date(2026, 10, 18)
NOW = datetime(2026, 10, 12, 6, 0, tzinfo=AMSTERDAM)
LATER = NOW + timedelta(days=3)


def record(source_id, discount="25% korting", **fields) -> DealRecord:
    values = dict(
        source_id=source_id,
        title=f"Deal {source_id}",
        discount_text=discount,
        valid_from=MONDAY,
        valid_to=SUNDAY,
        channel=Channel.BOTH,
    )
    return DealRecord(**(values | fields))


def fetch(*deals, store=Store.AH, on=MONDAY, skipped=0) -> FetchResult:
    return FetchResult(
        store=store, on=on, raw={"deals": len(deals)}, deals=list(deals), skipped=skipped
    )


def many(count, prefix="d"):
    return [record(f"{prefix}{i}") for i in range(count)]


def stored(session, store=Store.AH):
    return session.scalars(select(Deal).where(Deal.store == store).order_by(Deal.source_id)).all()


def test_a_fetch_stores_its_deals_with_the_parsed_discount(db_session):
    save_fetch(db_session, fetch(record("a", "voor 2,49", was_price_cents=349)), now=NOW)

    [deal] = deals_valid_on(db_session, MONDAY)
    assert deal.store is Store.AH
    assert deal.discount_text == "voor 2,49"
    assert deal.discount_kind is DiscountKind.FIXED_PRICE
    assert deal.discount_price_cents == 249
    assert deal.effective_fraction == Decimal("0.2865")
    assert deal.withdrawn_at is None


def test_the_same_fetch_twice_is_idempotent(db_session):
    result = fetch(record("a", products=(DealProductRecord("wi1", "Kipfilet", 599, 799),)))

    save_fetch(db_session, result, now=NOW)
    first = [(d.id, d.title, len(d.products)) for d in stored(db_session)]
    save_fetch(db_session, result, now=LATER)

    assert [(d.id, d.title, len(d.products)) for d in stored(db_session)] == first
    assert stored(db_session)[0].last_seen_at == LATER


def test_a_deal_missing_from_a_later_fetch_is_withdrawn_and_kept(db_session):
    save_fetch(db_session, fetch(record("a"), record("b")), now=NOW)

    save_fetch(db_session, fetch(record("a")), now=LATER)

    a, b = stored(db_session)
    assert a.withdrawn_at is None
    assert b.withdrawn_at == LATER
    assert [d.source_id for d in deals_valid_on(db_session, MONDAY)] == ["a"]


def test_a_withdrawn_deal_that_comes_back_is_no_longer_withdrawn(db_session):
    save_fetch(db_session, fetch(record("a"), record("b")), now=NOW)
    save_fetch(db_session, fetch(record("a")), now=LATER)

    save_fetch(db_session, fetch(record("a"), record("b")), now=LATER + timedelta(hours=1))

    assert [d.withdrawn_at for d in stored(db_session)] == [None, None]


def test_withdrawing_only_touches_the_same_store_and_deals_valid_on_the_date(db_session):
    last_week = record("old", valid_from=MONDAY - timedelta(7), valid_to=SUNDAY - timedelta(7))
    save_fetch(db_session, fetch(last_week, on=MONDAY - timedelta(7)), now=NOW - timedelta(7))
    save_fetch(db_session, fetch(record("j"), store=Store.JUMBO), now=NOW)

    save_fetch(db_session, fetch(record("a")), now=LATER)

    assert [d.withdrawn_at for d in stored(db_session)] == [None, None]
    assert stored(db_session, Store.JUMBO)[0].withdrawn_at is None


def test_a_fetch_with_more_than_a_fifth_skipped_writes_nothing(db_session):
    with pytest.raises(FetchRejected):
        save_fetch(db_session, fetch(*many(7), skipped=3), now=NOW)

    assert stored(db_session) == []
    assert db_session.scalar(select(func.count()).select_from(DealFetch)) == 0


def test_a_fetch_with_a_fifth_skipped_is_stored(db_session):
    save_fetch(db_session, fetch(*many(8), skipped=2), now=NOW)

    assert len(stored(db_session)) == 8


def test_a_fetch_with_no_deals_is_rejected(db_session):
    with pytest.raises(FetchRejected):
        save_fetch(db_session, fetch(), now=NOW)


def test_a_fetch_below_40_percent_of_last_weeks_count_writes_nothing(db_session):
    last_week = MONDAY - timedelta(7)
    old = [
        record(f"o{i}", valid_from=last_week, valid_to=last_week + timedelta(6)) for i in range(10)
    ]
    save_fetch(db_session, fetch(*old, on=last_week), now=NOW - timedelta(7))

    with pytest.raises(FetchRejected):
        save_fetch(db_session, fetch(*many(3)), now=NOW)
    save_fetch(db_session, fetch(*many(4)), now=NOW)

    assert len(deals_valid_on(db_session, MONDAY)) == 4


def test_only_the_last_eight_fetches_per_store_are_kept(db_session):
    for hour in range(10):
        save_fetch(db_session, fetch(record("a")), now=NOW + timedelta(hours=hour))
    save_fetch(db_session, fetch(record("j"), store=Store.JUMBO), now=NOW)

    fetches = db_session.scalars(select(DealFetch).where(DealFetch.store == Store.AH)).all()
    assert len(fetches) == 8
    assert min(f.fetched_at for f in fetches) == NOW + timedelta(hours=2)
    assert db_session.scalar(select(func.count()).where(DealFetch.store == Store.JUMBO)) == 1


def test_a_fetch_records_its_raw_payload_and_counts(db_session):
    save_fetch(db_session, fetch(record("a"), record("b")), now=NOW)
    save_fetch(db_session, fetch(*many(4), skipped=1), now=LATER)

    latest = db_session.scalars(select(DealFetch).order_by(DealFetch.fetched_at.desc())).first()
    assert latest.raw == {"deals": 4}
    assert (latest.parsed_count, latest.skipped_count, latest.withdrawn_count) == (4, 1, 2)
    assert latest.valid_on == MONDAY


def test_a_deal_products_regular_price_is_observed_for_its_chosen_product(db_session):
    kipfilet = Ingredient(name="kipfilet", aisle=Aisle.VLEES_VIS_VEGA)
    chosen = Product(
        ingredient=kipfilet, store=Store.AH, sku="wi1", name="AH Kipfilet", chosen_at=NOW
    )
    db_session.add(chosen)
    db_session.flush()
    products = (
        DealProductRecord("wi1", "AH Kipfilet", 599, 799),
        DealProductRecord("wi2", "Onbekend", 100, 150),
    )

    save_fetch(db_session, fetch(record("a", products=products)), now=NOW)

    db_session.expire_all()
    [observation] = chosen.price_observations
    assert (observation.price_cents, observation.source) == (799, PriceSource.DEAL)
    assert observation.observed_at == NOW


def test_deals_valid_on_filters_by_date_store_and_channel(db_session):
    save_fetch(
        db_session,
        fetch(
            record("both"),
            record("store", channel=Channel.IN_STORE),
            record("online", channel=Channel.ONLINE),
        ),
        now=NOW,
    )
    save_fetch(db_session, fetch(record("j"), store=Store.JUMBO), now=NOW)

    def ids(*args, **kwargs):
        return sorted(d.source_id for d in deals_valid_on(db_session, *args, **kwargs))

    assert ids(MONDAY) == ["both", "j", "store"]
    assert ids(MONDAY, store=Store.AH) == ["both", "store"]
    assert ids(MONDAY, channel=Channel.ONLINE) == ["both", "j", "online"]
    assert ids(SUNDAY + timedelta(1)) == []
