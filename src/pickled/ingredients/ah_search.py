"""AH regular prices from the Appie product search (#15), one counted request per lookup.

Every request counts against AH's weekly budget (ADR 0005), and lookups leave enough of it for
one more Deal fetch, so AH price lookups never starve the Deals a Meal Plan is drafted from.
"""

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session

from pickled.ingredients.models import PriceSource
from pickled.ingredients.prices import PricesUnavailable, ProductCandidate, euro_cents
from pickled.stores import (
    AMSTERDAM,
    REQUEST_BUDGET,
    RequestBudgetExceeded,
    Store,
    requests_this_week,
)
from pickled.stores.appie import API, DEAL_FETCH_REQUESTS, anonymous_headers

PRODUCT_URL = "https://www.ah.nl/producten/product/wi{webshop_id}"
SHORTLIST_SIZE = 50


class SearchProduct(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")

    webshop_id: int = Field(alias="webshopId")
    title: str
    unit_size: str | None = Field(None, alias="salesUnitSize")
    price_before_bonus: float = Field(alias="priceBeforeBonus")
    virtual_bundle: bool = Field(False, alias="isVirtualBundle")


class AhSearchPriceSource:
    store = Store.AH
    price_source = PriceSource.AH_SEARCH
    refresh_after = timedelta(weeks=4)
    # Lookups always leave one Deal fetch's requests. The week starts on Monday, so Monday's
    # fetch always has its budget, and this keeps Thursday's, which the draft is made from.
    reserved_for_deals = DEAL_FETCH_REQUESTS

    def __init__(
        self,
        client: httpx.Client,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(AMSTERDAM),
    ):
        self.client = client
        self.clock = clock
        self._headers: dict[str, str] | None = None

    def shortlist(self, session: Session, query: str) -> list[ProductCandidate]:
        """AH's own best matches for `query`, leaving out multipack bundles."""
        products = self._search(
            session,
            "/mobile-services/product/search/v2",
            lambda body: body["products"],
            query=query,
            size=SHORTLIST_SIZE,
        )
        return [_candidate(product) for product in products if not product.virtual_bundle]

    def current(self, session: Session, sku: str) -> ProductCandidate | None:
        webshop_id = sku.removeprefix("wi")
        products = self._search(
            session,
            "/mobile-services/product/search/v2/products",
            # A lookup by id answers with a bare list of products.
            lambda body: body,
            ids=webshop_id,
            sortOn="INPUT_PRODUCT_IDS",
        )
        return next((_candidate(p) for p in products if str(p.webshop_id) == webshop_id), None)

    def _search(
        self, session: Session, path: str, items_in: Callable[[Any], Any], **params
    ) -> list[SearchProduct]:
        # The first lookup of a run also needs a token, which is kept for the rest.
        needed = 1 if self._headers is not None else 2
        used = requests_this_week(session, self.store, now=self.clock())
        if used + needed > REQUEST_BUDGET - self.reserved_for_deals:
            raise PricesUnavailable(
                f"AH has {REQUEST_BUDGET - used} requests left this week, kept for its Deals"
            )
        try:
            if self._headers is None:
                self._headers = anonymous_headers(self.client)
            response = self.client.get(f"{API}{path}", params=params, headers=self._headers)
            response.raise_for_status()
            items = items_in(response.json())
            if not isinstance(items, list):
                raise TypeError(f"expected a list of products, got {type(items).__name__}")
        except (httpx.HTTPError, RequestBudgetExceeded, KeyError, TypeError, ValueError) as error:
            raise PricesUnavailable(f"AH product search failed: {error!r}") from error
        products = []
        for item in items:
            try:
                products.append(SearchProduct.model_validate(item))
            except ValidationError:
                continue
        return products


def _candidate(product: SearchProduct) -> ProductCandidate:
    return ProductCandidate(
        sku=f"wi{product.webshop_id}",
        name=product.title,
        price_cents=euro_cents(product.price_before_bonus),
        pack_size=product.unit_size,
        url=PRODUCT_URL.format(webshop_id=product.webshop_id),
    )
