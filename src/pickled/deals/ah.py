"""AH Deals from the Appie mobile API (ADR 0005), modelled on gwillem/appie-go.

A run gets a fresh anonymous token, reads the Deal periods and categories, then reads each
NATIONAL category's section for the date: about 25 requests a run. The models are named after
the Appie payload's own fields.
"""

from datetime import date
from decimal import Decimal
from typing import Any

import httpx
from pydantic import Field, ValidationError

from pickled.deals.sources import (
    Channel,
    DealPayloadError,
    DealProductRecord,
    DealRecord,
    FetchResult,
    StrictModel,
)
from pickled.stores import Store
from pickled.stores.appie import API, APP_HEADERS, DEAL_FETCH_REQUESTS, anonymous_headers

NATIONAL = "NATIONAL"


class AhDealSource:
    store = Store.AH
    requests_per_fetch = DEAL_FETCH_REQUESTS

    def __init__(self, client: httpx.Client):
        self.client = client

    def download(self, on: date) -> dict:
        """The raw payload for `on`: the metadata, and the section of each NATIONAL category."""
        headers = anonymous_headers(self.client)
        response = self.client.get(f"{API}/mobile-services/bonuspage/v3/metadata", headers=headers)
        response.raise_for_status()
        metadata = response.json()
        sections = {}
        for category in national_categories(metadata, on):
            params = {
                "application": APP_HEADERS["x-application"],
                "date": on.isoformat(),
                "promotionType": NATIONAL,
                "category": category,
            }
            response = self.client.get(
                f"{API}/mobile-services/bonuspage/v2/section", params=params, headers=headers
            )
            response.raise_for_status()
            sections[category] = response.json()
        return {"metadata": metadata, "sections": sections}

    def fetch(self, on: date) -> FetchResult:
        return parse(self.download(on), on)


class CategoryMetadata(StrictModel):
    description: str
    bonus_type: str = Field(alias="bonusType")


class Tab(StrictModel):
    categories: list[CategoryMetadata] = Field(alias="urlMetadataList")


class Period(StrictModel):
    start: date = Field(alias="bonusStartDate", strict=False)
    end: date = Field(alias="bonusEndDate", strict=False)
    tabs: list[Tab]


class Metadata(StrictModel):
    periods: list[Period]


class Product(StrictModel):
    webshop_id: int = Field(alias="webshopId")
    title: str
    unit_size: str | None = Field(None, alias="salesUnitSize")
    current_price: float | None = Field(None, alias="currentPrice")
    price_before_bonus: float | None = Field(None, alias="priceBeforeBonus")


class ProductItem(Product):
    bonus_mechanism: str = Field(alias="bonusMechanism")
    start: date = Field(alias="bonusStartDate", strict=False)
    end: date = Field(alias="bonusEndDate", strict=False)
    promotion_type: str = Field(NATIONAL, alias="promotionType")
    store_only: bool = Field(False, alias="storeOnlyPromotion")


class BonusGroup(StrictModel):
    id: str
    segment_description: str = Field(alias="segmentDescription")
    discount_description: str = Field(alias="discountDescription")
    start: date = Field(alias="bonusStartDate", strict=False)
    end: date = Field(alias="bonusEndDate", strict=False)
    promotion_type: str = Field(alias="promotionType")
    store_only: bool = Field(alias="storeOnlyPromotion")
    products: list[Product]
    example_from_price: float | None = Field(None, alias="exampleFromPrice")
    example_for_price: float | None = Field(None, alias="exampleForPrice")


def national_categories(metadata: Any, on: date) -> list[str]:
    """The NATIONAL Deal categories of the period `on` falls in, each once, in order."""
    try:
        parsed = Metadata.model_validate(metadata)
    except ValidationError as error:
        raise DealPayloadError(f"the AH metadata has changed shape: {error}") from error
    categories = [
        category.description
        for period in parsed.periods
        if period.start <= on <= period.end
        for tab in period.tabs
        for category in tab.categories
        if category.bonus_type == NATIONAL
    ]
    if not categories:
        raise DealPayloadError(f"the AH metadata has no NATIONAL period on {on}")
    return list(dict.fromkeys(categories))


def parse(raw: dict, on: date) -> FetchResult:
    """The NATIONAL Deals valid on `on` in a raw payload from `AhDealSource.download`."""
    deals: dict[str, DealRecord] = {}
    skipped = 0
    try:
        items = [
            (category, item)
            for category in national_categories(raw["metadata"], on)
            for item in raw["sections"][category]["bonusGroupOrProducts"]
        ]
    except (KeyError, TypeError) as error:
        raise DealPayloadError(f"the AH payload has changed shape: {error!r}") from error

    for category, item in items:
        try:
            record = _deal(item, category)
        except ValidationError, KeyError, TypeError, AttributeError:
            skipped += 1
            continue
        if record is not None and record.valid_from <= on <= record.valid_to:
            deals.setdefault(record.source_id, record)
    return FetchResult(store=Store.AH, on=on, raw=raw, deals=list(deals.values()), skipped=skipped)


def _deal(item: dict, category: str) -> DealRecord | None:
    """The Deal an item describes, or None if it isn't a NATIONAL one."""
    if "bonusGroup" in item:
        group = BonusGroup.model_validate(item["bonusGroup"])
        if group.promotion_type != NATIONAL:
            return None
        return DealRecord(
            source_id=group.id,
            title=group.segment_description,
            discount_text=group.discount_description,
            valid_from=group.start,
            valid_to=group.end,
            channel=Channel.IN_STORE if group.store_only else Channel.BOTH,
            category=category,
            price_cents=_cents(group.example_for_price),
            was_price_cents=_cents(group.example_from_price),
            products=tuple(_product(p) for p in group.products),
        )
    product = ProductItem.model_validate(item["product"])
    if product.promotion_type != NATIONAL:
        return None
    record = _product(product)
    return DealRecord(
        source_id=record.sku,
        title=product.title,
        discount_text=product.bonus_mechanism,
        valid_from=product.start,
        valid_to=product.end,
        channel=Channel.IN_STORE if product.store_only else Channel.BOTH,
        category=category,
        price_cents=record.price_cents,
        was_price_cents=record.was_price_cents,
        unit_size=product.unit_size,
        products=(record,),
    )


def _product(product: Product) -> DealProductRecord:
    return DealProductRecord(
        sku=f"wi{product.webshop_id}",
        title=product.title,
        price_cents=_cents(product.current_price),
        was_price_cents=_cents(product.price_before_bonus),
        unit_size=product.unit_size,
    )


def _cents(euros: float | None) -> int | None:
    """Cents from AH's euro floats; a missing or zero price is unknown."""
    if not euros:
        return None
    return int((Decimal(str(euros)) * 100).to_integral_value())
