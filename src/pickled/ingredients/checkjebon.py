"""Jumbo regular prices from Checkjebon's `supermarkets.json` (#15), searched locally.

`refresh_checkjebon` replaces our copy of the Jumbo half when it has changed; Checkjebon's AH
half stopped updating in 2025 and is never used. Reading it makes no requests to Jumbo.
Checkjebon updates daily, so a refresh that finds the data unchanged for more than 3 days marks
it stale, as happened upstream to AH; the copy is kept either way.
"""

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import delete, exists, func, select
from sqlalchemy.orm import Session

from pickled.ingredients.models import CheckjebonCheck, CheckjebonProduct, PriceSource
from pickled.ingredients.prices import PricesUnavailable, ProductCandidate, euro_cents
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


class Listing(BaseModel):
    """A product as Checkjebon lists it."""

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


def refresh_checkjebon(session: Session, data: Any, *, now: datetime) -> CheckjebonCheck:
    """Replace our Jumbo copy with `data`'s if it changed, and record the check.

    Raises `CheckjebonError`, recording nothing, if `data` doesn't look like Checkjebon's.
    """
    jumbo = _jumbo_data(data)
    listings = jumbo.get("d")
    if not isinstance(listings, list) or not listings:
        raise CheckjebonError("Checkjebon's Jumbo data has no products")
    prefix = jumbo.get("u") or ""
    products: dict[str, CheckjebonProduct] = {}
    skipped = 0
    for raw in listings:
        try:
            product = _product(Listing.model_validate(raw), prefix)
        except ValidationError:
            skipped += 1
            continue
        products[product.sku] = product
    if not products or skipped > MAX_SKIPPED_SHARE * len(listings):
        raise CheckjebonError(
            f"{skipped} of {len(listings)} Checkjebon Jumbo products are unreadable"
        )

    content_hash = hashlib.sha256(json.dumps(listings, sort_keys=True).encode()).hexdigest()
    last = _last_check(session)
    changed = last is None or last.content_hash != content_hash
    if changed:
        session.execute(delete(CheckjebonProduct))
        session.add_all(products.values())
    last_change = now if changed else _last_change(session)
    check = CheckjebonCheck(
        checked_at=now,
        content_hash=content_hash,
        changed=changed,
        stale=last_change is not None and now - last_change > STALE_AFTER,
        products=len(products),
        skipped=skipped,
    )
    session.add(check)
    session.flush()
    return check


def checkjebon_stale(session: Session) -> bool:
    """Whether the last refresh found Checkjebon's Jumbo data unchanged for over 3 days."""
    last = _last_check(session)
    return last is not None and last.stale


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
        row = session.scalars(select(CheckjebonProduct).where(CheckjebonProduct.sku == sku)).first()
        return _candidate(row) if row is not None else None


def _jumbo_data(data: Any) -> dict:
    if not isinstance(data, list):
        raise CheckjebonError("Checkjebon's data is not a list of stores")
    for store in data:
        if isinstance(store, dict) and store.get("n") == "jumbo":
            return store
    raise CheckjebonError("Checkjebon's data has no Jumbo")


def _product(listing: Listing, prefix: str) -> CheckjebonProduct:
    # A Jumbo link ends in the product's SKU: "jumbo-kipfilet-ca-215-g-596629KGR".
    return CheckjebonProduct(
        sku=listing.link.rsplit("-", 1)[-1],
        name=listing.name,
        price_cents=euro_cents(listing.price),
        size=listing.size.strip() or None,
        url=prefix + listing.link,
    )


def _candidate(row: CheckjebonProduct) -> ProductCandidate:
    return ProductCandidate(
        sku=row.sku, name=row.name, price_cents=row.price_cents, pack_size=row.size, url=row.url
    )


def _last_check(session: Session) -> CheckjebonCheck | None:
    return session.scalars(
        select(CheckjebonCheck)
        .order_by(CheckjebonCheck.checked_at.desc(), CheckjebonCheck.id.desc())
        .limit(1)
    ).first()


def _last_change(session: Session) -> datetime | None:
    return session.scalar(
        select(func.max(CheckjebonCheck.checked_at)).where(CheckjebonCheck.changed)
    )


def _require_copy(session: Session) -> None:
    if not session.scalar(select(exists().where(CheckjebonCheck.changed))):
        raise PricesUnavailable("Checkjebon's Jumbo prices haven't been downloaded yet")
