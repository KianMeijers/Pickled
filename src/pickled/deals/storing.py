"""Storing a fetch, and reading the Deals valid on a date.

A fetch is all or nothing: it is checked first and rejected, writing nothing, if too many
items were skipped or it has far fewer Deals than the store's last stored fetch. Otherwise its
Deals are upserted on `(store, source_id, valid_from)`, and any stored Deal valid on the same
date that it no longer lists is withdrawn (never deleted).
"""

from datetime import date, datetime

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from pickled.deals.discounts import parse_discount
from pickled.deals.models import Deal, DealFetch, DealProduct
from pickled.deals.sources import Channel, DealRecord, FetchResult
from pickled.ingredients import PriceSource, record_regular_price
from pickled.stores import Store

MAX_SKIPPED_SHARE = 0.2
MIN_SHARE_OF_LAST_COUNT = 0.4
KEPT_FETCHES = 8


class FetchRejected(Exception):
    """A fetch looked broken, so nothing from it was stored."""


def save_fetch(session: Session, result: FetchResult, *, now: datetime) -> DealFetch:
    """Store a complete fetch of `result.store`'s Deals, or raise `FetchRejected`."""
    _check(session, result)

    kept_ids = [_upsert(session, result.store, record, now) for record in result.deals]
    withdrawn = session.execute(
        update(Deal)
        .where(
            Deal.store == result.store,
            Deal.valid_from <= result.on,
            Deal.valid_to >= result.on,
            Deal.withdrawn_at.is_(None),
            Deal.id.not_in(kept_ids),
        )
        .values(withdrawn_at=now)
        .returning(Deal.id)
    ).all()

    for record in result.deals:
        for product in record.products:
            if product.was_price_cents is not None:
                record_regular_price(
                    session,
                    result.store,
                    product.sku,
                    product.was_price_cents,
                    PriceSource.DEAL,
                    observed_at=now,
                )

    deal_fetch = DealFetch(
        store=result.store,
        fetched_at=now,
        valid_on=result.on,
        raw=result.raw,
        parsed_count=len(result.deals),
        skipped_count=result.skipped,
        withdrawn_count=len(withdrawn),
    )
    session.add(deal_fetch)
    session.flush()
    _prune_fetches(session, result.store)
    return deal_fetch


def deals_valid_on(
    session: Session,
    on: date,
    store: Store | None = None,
    channel: Channel = Channel.IN_STORE,
) -> list[Deal]:
    """The Deals valid on `on` that can be used in `channel`, leaving out withdrawn ones."""
    query = select(Deal).where(
        Deal.valid_from <= on,
        Deal.valid_to >= on,
        Deal.withdrawn_at.is_(None),
        Deal.channel.in_([channel, Channel.BOTH]),
    )
    if store is not None:
        query = query.where(Deal.store == store)
    return list(session.scalars(query.order_by(Deal.store, Deal.id)))


def _check(session: Session, result: FetchResult) -> None:
    parsed = len(result.deals)
    if parsed == 0:
        raise FetchRejected(f"{result.store}: the fetch for {result.on} has no Deals")
    if result.skipped > MAX_SKIPPED_SHARE * (parsed + result.skipped):
        raise FetchRejected(
            f"{result.store}: {result.skipped} of {parsed + result.skipped} items were skipped"
        )
    last_count = session.scalar(
        select(DealFetch.parsed_count)
        .where(DealFetch.store == result.store)
        .order_by(DealFetch.fetched_at.desc())
        .limit(1)
    )
    if last_count is not None and parsed < MIN_SHARE_OF_LAST_COUNT * last_count:
        raise FetchRejected(
            f"{result.store}: {parsed} Deals is under {MIN_SHARE_OF_LAST_COUNT:.0%} "
            f"of the last fetch's {last_count}"
        )


def _upsert(session: Session, store: Store, record: DealRecord, now: datetime) -> int:
    discount = parse_discount(record.discount_text, record.was_price_cents)
    values = dict(
        valid_to=record.valid_to,
        title=record.title,
        description=record.description,
        discount_text=record.discount_text,
        discount_kind=discount.kind,
        discount_percent=discount.percent,
        discount_price_cents=discount.price_cents,
        discount_n=discount.n,
        discount_m=discount.m,
        effective_fraction=discount.fraction,
        channel=record.channel,
        category=record.category,
        price_cents=record.price_cents,
        was_price_cents=record.was_price_cents,
        unit_size=record.unit_size,
        last_seen_at=now,
        withdrawn_at=None,
    )
    statement = (
        insert(Deal)
        .values(
            store=store,
            source_id=record.source_id,
            valid_from=record.valid_from,
            first_seen_at=now,
            **values,
        )
        .on_conflict_do_update(
            index_elements=[Deal.store, Deal.source_id, Deal.valid_from], set_=values
        )
        .returning(Deal)
    )
    # Refresh a Deal this session already holds, so it sees the upserted values.
    deal_id = session.scalars(statement, execution_options={"populate_existing": True}).one().id

    for product in record.products:
        product_values = dict(
            title=product.title,
            price_cents=product.price_cents,
            was_price_cents=product.was_price_cents,
            unit_size=product.unit_size,
        )
        session.execute(
            insert(DealProduct)
            .values(deal_id=deal_id, sku=product.sku, **product_values)
            .on_conflict_do_update(
                index_elements=[DealProduct.deal_id, DealProduct.sku], set_=product_values
            )
        )
    return deal_id


def _prune_fetches(session: Session, store: Store) -> None:
    kept = (
        select(DealFetch.id)
        .where(DealFetch.store == store)
        .order_by(DealFetch.fetched_at.desc(), DealFetch.id.desc())
        .limit(KEPT_FETCHES)
    )
    session.execute(delete(DealFetch).where(DealFetch.store == store, DealFetch.id.not_in(kept)))
