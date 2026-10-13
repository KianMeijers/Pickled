"""The per-store weekly request counter (ADR 0005: ~60 requests per store per week)."""

from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy.orm import sessionmaker

from pickled.stores import (
    REQUEST_BUDGET,
    RequestBudgetExceeded,
    Store,
    make_client,
    requests_this_week,
    spend_request,
)

AMSTERDAM = ZoneInfo("Europe/Amsterdam")
WEDNESDAY = datetime(2026, 10, 14, 12, 0, tzinfo=AMSTERDAM)
SUNDAY_LATE = datetime(2026, 10, 18, 23, 30, tzinfo=AMSTERDAM)
NEXT_MONDAY = datetime(2026, 10, 19, 0, 30, tzinfo=AMSTERDAM)


def spend_budget(session, store, now):
    for _ in range(REQUEST_BUDGET):
        spend_request(session, store, now=now)


def test_each_request_is_counted_per_store(db_session):
    spend_request(db_session, Store.AH, now=WEDNESDAY)
    spend_request(db_session, Store.AH, now=WEDNESDAY)
    spend_request(db_session, Store.JUMBO, now=WEDNESDAY)

    assert requests_this_week(db_session, Store.AH, now=WEDNESDAY) == 2
    assert requests_this_week(db_session, Store.JUMBO, now=WEDNESDAY) == 1


def test_a_request_over_budget_is_refused(db_session):
    spend_budget(db_session, Store.AH, WEDNESDAY)

    with pytest.raises(RequestBudgetExceeded):
        spend_request(db_session, Store.AH, now=WEDNESDAY)
    assert requests_this_week(db_session, Store.AH, now=WEDNESDAY) == REQUEST_BUDGET


def test_one_store_over_budget_does_not_block_the_other(db_session):
    spend_budget(db_session, Store.AH, WEDNESDAY)

    spend_request(db_session, Store.JUMBO, now=WEDNESDAY)


def test_the_week_runs_monday_to_sunday_in_amsterdam_time(db_session):
    spend_budget(db_session, Store.AH, WEDNESDAY)

    with pytest.raises(RequestBudgetExceeded):
        spend_request(db_session, Store.AH, now=SUNDAY_LATE)


def test_the_count_resets_in_a_new_week(db_session):
    spend_budget(db_session, Store.AH, WEDNESDAY)

    spend_request(db_session, Store.AH, now=NEXT_MONDAY)

    assert requests_this_week(db_session, Store.AH, now=NEXT_MONDAY) == 1


@pytest.fixture
def sessions(db_session):
    """Sessions that each open a savepoint inside the test's rolled-back transaction."""
    return sessionmaker(bind=db_session.connection(), join_transaction_mode="create_savepoint")


def fake_store(sent: list[httpx.Request]) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={"ok": True})

    return httpx.MockTransport(handle)


def client(store, sessions, sent):
    return make_client(store, sessions, transport=fake_store(sent), clock=lambda: WEDNESDAY)


def test_the_client_counts_each_request_and_sends_a_realistic_user_agent(db_session, sessions):
    sent: list[httpx.Request] = []
    with client(Store.JUMBO, sessions, sent) as store_client:
        store_client.get("https://www.jumbo.com/aanbiedingen/nu")

    assert len(sent) == 1
    assert "Mozilla/5.0" in sent[0].headers["User-Agent"]
    assert requests_this_week(db_session, Store.JUMBO, now=WEDNESDAY) == 1


def test_the_client_refuses_a_request_over_budget_without_sending_it(db_session, sessions):
    spend_budget(db_session, Store.AH, WEDNESDAY)
    sent: list[httpx.Request] = []

    with client(Store.AH, sessions, sent) as store_client:
        with pytest.raises(RequestBudgetExceeded):
            store_client.get("https://api.ah.nl/mobile-services/product/search/v2")

    assert sent == []


def test_the_ah_client_identifies_as_the_appie_app(sessions):
    sent: list[httpx.Request] = []
    with client(Store.AH, sessions, sent) as store_client:
        store_client.get("https://api.ah.nl/mobile-services/product/search/v2")

    assert sent[0].headers["User-Agent"].startswith("Appie/")
