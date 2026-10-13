"""The `RegularPriceSource` port. Its adapters (AH search, Checkjebon for Jumbo) come later."""

from dataclasses import dataclass
from typing import Protocol

from pickled.stores import Store


@dataclass(frozen=True)
class ProductCandidate:
    """One store product on a shortlist, at its regular (non-Deal) price."""

    sku: str
    name: str
    price_cents: int
    pack_size: str | None = None
    url: str | None = None


class RegularPriceSource(Protocol):
    """Where a store's regular prices come from, searched to shortlist Products."""

    store: Store

    def shortlist(self, ingredient_name: str) -> list[ProductCandidate]:
        """Candidate Products for an Ingredient, best matches first."""
        ...
