"""The AH adapter against an Appie Bonus payload.

The fixture is synthetic, built from the shapes documented by gwillem/appie-go and our
research (#2), because api.ah.nl refused every request when this was built. Replace it with a
recorded one (`scripts/record_deal_fixture.py ah`).
"""

import json
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from pickled.deals import AhDealSource, Channel, DealProductRecord
from pickled.deals.ah import parse

FIXTURE = Path(__file__).parent / "fixtures" / "deals_ah_synthetic.json"
TUESDAY = date(2026, 10, 13)


@pytest.fixture(scope="module")
def raw():
    return json.loads(FIXTURE.read_text())


@pytest.fixture(scope="module")
def result(raw):
    return parse(raw, TUESDAY)


def deal(result, source_id):
    [found] = [d for d in result.deals if d.source_id == source_id]
    return found


def test_it_keeps_each_national_deal_once_and_counts_bad_items(result):
    assert sorted(d.source_id for d in result.deals) == [
        "814121",
        "815000",
        "817000",
        "wi123456",
        "wi234567",
    ]
    assert result.skipped == 1


def test_a_bonus_group_becomes_a_deal(result):
    burgers = deal(result, "814121")

    assert burgers.title == "Alle AH Greenfields beefburgers 2 stuks"
    assert burgers.discount_text == "VOOR 2.49"
    assert (burgers.valid_from, burgers.valid_to) == (date(2026, 10, 12), date(2026, 10, 18))
    assert burgers.category == "Vlees"
    assert burgers.channel is Channel.BOTH
    assert (burgers.price_cents, burgers.was_price_cents) == (249, 329)
    assert burgers.products == ()


def test_a_single_product_is_a_deal_with_its_product(result):
    kipfilet = deal(result, "wi123456")

    assert kipfilet.discount_text == "25% KORTING"
    assert kipfilet.channel is Channel.IN_STORE
    assert (kipfilet.price_cents, kipfilet.was_price_cents) == (599, 799)
    assert kipfilet.unit_size == "500 g"
    assert kipfilet.products == (
        DealProductRecord(
            sku="wi123456",
            title="AH Scharrel kipfilet",
            price_cents=599,
            was_price_cents=799,
            unit_size="500 g",
        ),
    )


def test_a_group_that_lists_its_products_keeps_them(result):
    rookworst = deal(result, "815000")

    assert [p.sku for p in rookworst.products] == ["wi345678", "wi345679"]


def test_fetch_gets_a_token_then_reads_each_national_category_for_the_date(raw):
    sent = []

    def handle(request):
        sent.append(request)
        path = request.url.path
        if path.endswith("/token/anonymous"):
            return httpx.Response(200, json={"access_token": "t0ken", "expires_in": 604798})
        if path.endswith("/bonuspage/v3/metadata"):
            return httpx.Response(200, json=raw["metadata"])
        category = parse_qs(urlsplit(str(request.url)).query)["category"][0]
        return httpx.Response(200, json=raw["sections"][category])

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = AhDealSource(client).fetch(TUESDAY)

    token, metadata, *sections = sent
    assert token.method == "POST"
    assert json.loads(token.content) == {"clientId": "appie-ios"}
    assert metadata.headers["Authorization"] == "Bearer t0ken"
    queries = [parse_qs(urlsplit(str(r.url)).query) for r in sections]
    assert [q["category"] for q in queries] == [["Vlees"], ["Groente, aardappelen"]]
    assert all(q["date"] == ["2026-10-13"] and q["promotionType"] == ["NATIONAL"] for q in queries)
    assert result.raw == raw
    assert len(result.deals) == 5
