"""The Jumbo adapter against a real recorded `__NUXT_DATA__` payload (2026-10-13)."""

import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from pickled.deals import Channel, DealPayloadError, JumboDealSource
from pickled.deals.jumbo import parse

FIXTURE = Path(__file__).parent / "fixtures" / "deals_jumbo_2026-10-13.json"
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


def test_it_keeps_each_promotion_valid_on_the_date_once(result):
    assert len(result.deals) == 150
    assert len({d.source_id for d in result.deals}) == 150
    assert result.skipped == 0


def test_it_leaves_out_promotions_that_start_later(result):
    assert "3021228" not in {d.source_id for d in result.deals}


def test_a_promotion_becomes_a_deal(result):
    champignons = deal(result, "3021066")

    assert champignons.title == "Kastanjechampignons"
    assert champignons.description == "Bak 250 gram"
    assert champignons.discount_text == "voor 1,29"
    assert champignons.valid_from == date(2026, 10, 7)
    assert champignons.valid_to == date(2026, 10, 13)
    assert champignons.category == "Aardappelen, groente en fruit"
    assert champignons.channel is Channel.BOTH


def test_a_channel_tag_sets_the_channel_and_is_not_the_discount(result):
    stoofvlees = deal(result, "3021122")

    assert stoofvlees.channel is Channel.IN_STORE
    assert stoofvlees.discount_text == "25% korting"
    assert stoofvlees.valid_to == date(2026, 10, 20)


def test_a_bad_promotion_is_skipped_and_counted(raw):
    broken = json.loads(json.dumps(raw))
    # In the devalue array a Promotion's fields point at other entries; break one title.
    [title_index] = {
        v["title"]
        for v in broken
        if isinstance(v, dict) and "tags" in v and broken[v["id"]] == "3021005"
    }
    broken[title_index] = 42

    result = parse(broken, TUESDAY)

    assert result.skipped == 1
    assert len(result.deals) == 149


def test_a_payload_without_promotions_fails_loudly():
    with pytest.raises(DealPayloadError):
        parse([{"data": 1}, {}], TUESDAY)


def test_fetch_reads_the_offers_page_through_the_client(raw):
    html = f'<html><script type="application/json" id="__NUXT_DATA__">{json.dumps(raw)}</script>'
    sent = []

    def handle(request):
        sent.append(request)
        return httpx.Response(200, text=html)

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = JumboDealSource(client).fetch(TUESDAY)

    assert [str(r.url) for r in sent] == ["https://www.jumbo.com/aanbiedingen/nu"]
    assert result.raw == raw
    assert len(result.deals) == 150
