"""Recording regular prices seen elsewhere, such as on a Deal, for a store's chosen Products."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from pickled.ingredients.models import PriceObservation, PriceSource, Product
from pickled.stores import Store


def record_regular_price(
    session: Session,
    store: Store,
    sku: str,
    price_cents: int,
    source: PriceSource,
    *,
    observed_at: datetime,
) -> bool:
    """Observe `price_cents` for the chosen Product with `sku` at `store`.

    Returns False, and records nothing, if no Ingredient has that Product chosen.
    """
    product = session.scalars(
        select(Product).where(
            Product.store == store, Product.sku == sku, Product.replaced_at.is_(None)
        )
    ).first()
    if product is None:
        return False
    session.add(
        PriceObservation(
            product=product, price_cents=price_cents, source=source, observed_at=observed_at
        )
    )
    return True
