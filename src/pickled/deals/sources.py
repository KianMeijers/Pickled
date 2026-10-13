"""The `DealSource` port: what each store's adapter gives the deals module."""

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from pickled.stores import Store


class Channel(StrEnum):
    """Where a Deal can be used. The Household shops in store."""

    IN_STORE = "in_store"
    ONLINE = "online"
    BOTH = "both"


class StrictModel(BaseModel):
    """The base for checking a source's items: strict types, unknown fields ignored."""

    model_config = ConfigDict(strict=True, extra="ignore")


class DealPayloadError(Exception):
    """A source's payload has lost the shape its adapter reads; the format has changed."""


@dataclass(frozen=True)
class DealProductRecord:
    """A product a Deal lists, where the source gives it (AH single-product items)."""

    sku: str
    title: str
    price_cents: int | None = None
    was_price_cents: int | None = None
    unit_size: str | None = None


@dataclass(frozen=True)
class DealRecord:
    """One Deal as a source lists it, before it is stored."""

    source_id: str
    title: str
    discount_text: str
    valid_from: date
    valid_to: date
    channel: Channel
    description: str | None = None
    category: str | None = None
    price_cents: int | None = None
    was_price_cents: int | None = None
    unit_size: str | None = None
    products: tuple[DealProductRecord, ...] = ()


@dataclass(frozen=True)
class FetchResult:
    """A complete fetch of one store's Deals valid on `on`: the raw payload and its Deals.

    `skipped` counts items that failed their adapter's strict model.
    """

    store: Store
    on: date
    raw: Any
    deals: list[DealRecord] = field(default_factory=list)
    skipped: int = 0


class DealSource(Protocol):
    store: Store
    # About how many requests a fetch sends, so a run the week's budget can't cover isn't begun.
    requests_per_fetch: int

    def fetch(self, on: date) -> FetchResult:
        """Every Deal the store lists as valid on `on`."""
        ...
