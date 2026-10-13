"""The `RegularPriceSource` port: where a store's regular (non-Deal) prices come from."""

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Protocol

from sqlalchemy.orm import Session

from pickled.ingredients.models import PriceSource
from pickled.stores import Store


@dataclass(frozen=True)
class ProductCandidate:
    """One store product on a shortlist, at its regular (non-Deal) price."""

    sku: str
    name: str
    price_cents: int
    pack_size: str | None = None
    url: str | None = None


def euro_cents(euros: float) -> int:
    """Cents from a store's price in euros, which its data gives as a float."""
    return int((Decimal(str(euros)) * 100).to_integral_value())


class PricesUnavailable(Exception):
    """A source can't give prices right now: its budget is spent, or it has no data yet."""


class RegularPriceSource(Protocol):
    """Where a store's regular prices come from, searched to shortlist Products.

    Both methods raise `PricesUnavailable` when the source can't answer at the moment.
    """

    store: Store
    price_source: PriceSource
    # How old a chosen Product's price may get before `current` is asked again.
    refresh_after: timedelta

    def shortlist(self, session: Session, query: str) -> list[ProductCandidate]:
        """Candidate Products for an Ingredient's name, best matches first."""
        ...

    def current(self, session: Session, sku: str) -> ProductCandidate | None:
        """The Product with `sku` at its current price, or None if it's no longer sold."""
        ...
