"""The AH regular-price adapter against an Appie product search payload.

The fixture is synthetic, built from the fields our research (#15) saw live and gwillem/appie-go
documents, because api.ah.nl refused requests while the AH Deals adapter was built.
"""

import json
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import httpx
import pytest

from pickled.ingredients import (
    AhSearchPriceSource,
    PriceSource,
    PricesUnavailable,
    ProductCandidate,
)
from pickled.stores import REQUEST_BUDGET, Store, make_client, requests_this_week, spend_request

FIXTURE = Path(__file__).parent / "fixtures" / "ah_search_synthetic.json"
NOW = datetime(2026, 10, 15, 18, 0, tzinfo=ZoneInfo("Europe/Amsterdam"))


@pytest.fixture
def sent():
    return []


@pytest.fixture
def source(sessions, sent):
    def handle(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        if request.url.path.endswith("/token/anonymous"):
            return httpx.Response(200, json={"access_token": "token-1", "expires_in": 604798})
        payload = json.loads(FIXTURE.read_text())
        ids = parse_qs(urlsplit(str(request.url)).query).get("ids")
        if ids:
            wanted = {int(i) for i in ids}
            payload["products"] = [p for p in payload["products"] if p["webshopId"] in wanted]
        return httpx.Response(200, json=payload)

    client = make_client(
        Store.AH, sessions, transport=httpx.MockTransport(handle), clock=lambda: NOW
    )
    with client:
        yield AhSearchPriceSource(client, clock=lambda: NOW)


def test_a_search_shortlists_single_products_at_their_regular_price(db_session, source, sent):
    shortlist = source.shortlist(db_session, "kipfilet")

    assert shortlist == [
        ProductCandidate(
            "wi533083",
            "AH Scharrel kipfilet 2 stuks",
            449,
            "300 g",
            "https://www.ah.nl/producten/product/wi533083",
        ),
        ProductCandidate(
            "wi57741",
            "AH Biologisch Kipfilet 2 stuks",
            899,
            "ca. 320 g",
            "https://www.ah.nl/producten/product/wi57741",
        ),
        ProductCandidate(
            "wi412345",
            "AH Kipfilet plakjes",
            229,
            "150 g",
            "https://www.ah.nl/producten/product/wi412345",
        ),
    ]
    search = parse_qs(urlsplit(str(sent[-1].url)).query)
    assert (search["query"], search["size"]) == (["kipfilet"], ["50"])
    assert sent[-1].headers["Authorization"] == "Bearer token-1"
    assert (source.store, source.price_source) == (Store.AH, PriceSource.AH_SEARCH)


def test_the_token_is_reused_so_each_later_search_is_one_request(db_session, source, sent):
    source.shortlist(db_session, "kipfilet")
    before = requests_this_week(db_session, Store.AH, now=NOW)

    source.shortlist(db_session, "rode kool")

    assert requests_this_week(db_session, Store.AH, now=NOW) == before + 1
    assert len(sent) == 3


def test_current_looks_up_one_product_by_its_id(db_session, source, sent):
    current = source.current(db_session, "wi57741")

    assert (current.sku, current.price_cents) == ("wi57741", 899)
    assert parse_qs(urlsplit(str(sent[-1].url)).query)["ids"] == ["57741"]
    assert source.current(db_session, "wi424242") is None


def test_lookups_leave_one_deal_fetch_of_the_weekly_budget_unspent(db_session, source, sent):
    for _ in range(REQUEST_BUDGET - AhSearchPriceSource.reserved_for_deals - 2):
        spend_request(db_session, Store.AH, now=NOW)
    source.shortlist(db_session, "kipfilet")

    with pytest.raises(PricesUnavailable):
        source.shortlist(db_session, "rode kool")
    with pytest.raises(PricesUnavailable):
        source.current(db_session, "wi57741")
    assert len(sent) == 2
