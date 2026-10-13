"""`price_for`: what an Ingredient costs at a store, from its chosen Product's observed prices."""

from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from pickled.ingredients.models import Ingredient, PriceObservation, PriceSource, Product
from pickled.ingredients.picking import ProductPicker
from pickled.stores import AMSTERDAM, Store

# A price observed longer ago than this before the day it is for is only a rough guide.
ROUGH_AFTER = timedelta(weeks=8)
# A Deal's regular price, seen within a Deal week before the day, beats any other source: a
# store's own listing can show the Deal price as if it were the regular one.
DEAL_WEEK = timedelta(days=7)


@dataclass(frozen=True)
class Price:
    """A regular pack price for an Ingredient, of `product` at its store.

    A rough one is old, or from the other store.
    """

    cents: int
    product: Product
    observed_at: datetime
    rough: bool


def price_for(
    session: Session, ingredient: Ingredient, store: Store, *, on: date, picker: ProductPicker
) -> Price | None:
    """The regular price of `ingredient` at `store` on `on`, or None if neither store has one.

    Without a Product or a price at `store`, the other store's price is used, marked rough.
    """
    price = _store_price(session, ingredient, store, on, picker)
    if price is not None:
        return price
    other = next(s for s in Store if s != store)
    price = _store_price(session, ingredient, other, on, picker)
    return replace(price, rough=True) if price is not None else None


def _store_price(
    session: Session, ingredient: Ingredient, store: Store, on: date, picker: ProductPicker
) -> Price | None:
    product = picker.chosen(session, ingredient, store)
    if product is None:
        return None
    picker.refresh(session, product)
    observation = _current_deal_observation(session, product, on) or _latest_observation(
        session, product
    )
    if observation is None:
        return None
    return Price(
        cents=observation.price_cents,
        product=product,
        observed_at=observation.observed_at,
        rough=on - observation.observed_at.astimezone(AMSTERDAM).date() > ROUGH_AFTER,
    )


def _current_deal_observation(
    session: Session, product: Product, on: date
) -> PriceObservation | None:
    since = datetime.combine(on - DEAL_WEEK + timedelta(days=1), time(), AMSTERDAM)
    until = datetime.combine(on + timedelta(days=1), time(), AMSTERDAM)
    return _latest_observation(
        session,
        product,
        PriceObservation.source == PriceSource.DEAL,
        PriceObservation.observed_at >= since,
        PriceObservation.observed_at < until,
    )


def _latest_observation(session: Session, product: Product, *conditions) -> PriceObservation | None:
    return session.scalars(
        select(PriceObservation)
        .where(PriceObservation.product_id == product.id, *conditions)
        .order_by(PriceObservation.observed_at.desc(), PriceObservation.id.desc())
        .limit(1)
    ).first()
