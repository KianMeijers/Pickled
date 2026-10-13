"""Jumbo regular prices from Checkjebon's `supermarkets.json` (#15), searched locally.

`refresh_checkjebon` replaces our copy of the Jumbo half; Checkjebon's AH half stopped updating
in 2025 and is never used. Reading it makes no requests to Jumbo. If the Jumbo half stops
changing for more than 3 days the copy is flagged stale, as happened upstream to AH.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import CheckConstraint, Index, delete, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Mapped, Session, mapped_column

from pickled.db import Base
from pickled.ingredients.models import PriceSource
from pickled.ingredients.prices import PricesUnavailable, ProductCandidate
from pickled.stores import Store

DATA_URL = "https://raw.githubusercontent.com/supermarkt/checkjebon/main/data/supermarkets.json"
STALE_AFTER = timedelta(days=3)
MAX_SKIPPED_SHARE = 0.2
SHORTLIST_SIZE = 30
# How much of a search must appear in a product name (pg_trgm word similarity). Loose on
# purpose, since the match model chooses from the shortlist: "biologische kipfilet" scores 0.43
# against "Jumbo Kipfilet", while "kippendij" scores 0.3 against it.
MATCH_THRESHOLD = 0.4


class CheckjebonError(Exception):
    """A download that doesn't look like Checkjebon's data; the last copy is kept."""


class CheckjebonProduct(Base):
    """One Jumbo product in our copy of Checkjebon, replaced on each changed refresh."""

    __tablename__ = "checkjebon_product"
    __table_args__ = (
        Index(
            "ix_checkjebon_product_name_trgm",
            func.lower(text("name")),
            postgresql_using="gin",
            postgresql_ops={"lower(name)": "gin_trgm_ops"},
        ),
    )

    sku: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str]
    price_cents: Mapped[int]
    size: Mapped[str | None]
    url: Mapped[str]


class CheckjebonState(Base):
    """The single row saying when our copy was last checked and when its data last changed."""

    __tablename__ = "checkjebon_state"
    __table_args__ = (CheckConstraint("id = 1", name="single_row"),)

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    checked_at: Mapped[datetime]
    changed_at: Mapped[datetime]
    content_hash: Mapped[str]
    product_count: Mapped[int]


@dataclass(frozen=True)
class CheckjebonRefresh:
    products: int
    skipped: int
    changed: bool
    stale: bool


class Item(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")

    name: str = Field(alias="n")
    link: str = Field(alias="l")
    price: float | int = Field(alias="p")
    size: str = Field("", alias="s")


def download_checkjebon(client: httpx.Client) -> Any:
    """Checkjebon's whole `supermarkets.json` (about 2.3 MB gzipped) from GitHub."""
    response = client.get(DATA_URL)
    response.raise_for_status()
    return response.json()


def refresh_checkjebon(session: Session, data: Any, *, now: datetime) -> CheckjebonRefresh:
    """Replace our Jumbo copy with `data`'s, unless it is unchanged; or raise `CheckjebonError`."""
    store = _jumbo(data)
    items = store.get("d")
    if not isinstance(items, list) or not items:
        raise CheckjebonError("Checkjebon's Jumbo data has no products")
    prefix = store.get("u") or ""
    products: dict[str, CheckjebonProduct] = {}
    skipped = 0
    for raw in items:
        try:
            item = Item.model_validate(raw)
        except ValidationError:
            skipped += 1
            continue
        product = _product(item, prefix)
        products[product.sku] = product
    if not products or skipped > MAX_SKIPPED_SHARE * len(items):
        raise CheckjebonError(f"{skipped} of {len(items)} Checkjebon Jumbo products are unreadable")

    content_hash = hashlib.sha256(json.dumps(items, sort_keys=True).encode()).hexdigest()
    state = session.get(CheckjebonState, 1)
    changed = state is None or state.content_hash != content_hash
    if changed:
        session.execute(delete(CheckjebonProduct))
        session.add_all(products.values())
        values = dict(
            checked_at=now, changed_at=now, content_hash=content_hash, product_count=len(products)
        )
        session.execute(
            insert(CheckjebonState)
            .values(id=1, **values)
            .on_conflict_do_update(index_elements=[CheckjebonState.id], set_=values)
        )
    else:
        assert state is not None
        state.checked_at = now
    session.flush()
    return CheckjebonRefresh(
        products=len(products),
        skipped=skipped,
        changed=changed,
        stale=checkjebon_stale(session, now=now),
    )


def checkjebon_stale(session: Session, *, now: datetime) -> bool:
    """Whether our Jumbo copy's data hasn't changed for more than 3 days."""
    changed_at = session.scalar(select(CheckjebonState.changed_at))
    return changed_at is not None and now - changed_at > STALE_AFTER


class CheckjebonJumboPriceSource:
    store = Store.JUMBO
    price_source = PriceSource.CHECKJEBON
    # Reading our copy is free, so a chosen Product takes each day's price.
    refresh_after = timedelta(days=1)

    def shortlist(self, session: Session, query: str) -> list[ProductCandidate]:
        """The Jumbo products whose names best contain `query`, by trigram word similarity.

        Many names contain a search word equally well ("kipfilet" is in cat food too), so among
        those the names closest to the search as a whole come first.
        """
        _require_copy(session)
        name = func.lower(CheckjebonProduct.name)
        contains = func.word_similarity(func.lower(query), name)
        closeness = func.similarity(func.lower(query), name)
        rows = session.scalars(
            select(CheckjebonProduct)
            .where(contains >= MATCH_THRESHOLD)
            .order_by(contains.desc(), closeness.desc(), CheckjebonProduct.sku)
            .limit(SHORTLIST_SIZE)
        )
        return [_candidate(row) for row in rows]

    def current(self, session: Session, sku: str) -> ProductCandidate | None:
        _require_copy(session)
        row = session.get(CheckjebonProduct, sku)
        return _candidate(row) if row is not None else None


def _jumbo(data: Any) -> dict:
    if not isinstance(data, list):
        raise CheckjebonError("Checkjebon's data is not a list of stores")
    for store in data:
        if isinstance(store, dict) and store.get("n") == "jumbo":
            return store
    raise CheckjebonError("Checkjebon's data has no Jumbo")


def _product(item: Item, prefix: str) -> CheckjebonProduct:
    # A Jumbo link ends in the product's SKU: "jumbo-kipfilet-ca-215-g-596629KGR".
    return CheckjebonProduct(
        sku=item.link.rsplit("-", 1)[-1],
        name=item.name,
        price_cents=int((Decimal(str(item.price)) * 100).to_integral_value()),
        size=item.size.strip() or None,
        url=prefix + item.link,
    )


def _candidate(row: CheckjebonProduct) -> ProductCandidate:
    return ProductCandidate(
        sku=row.sku, name=row.name, price_cents=row.price_cents, pack_size=row.size, url=row.url
    )


def _require_copy(session: Session) -> None:
    if session.get(CheckjebonState, 1) is None:
        raise PricesUnavailable("Checkjebon's Jumbo prices haven't been downloaded yet")
