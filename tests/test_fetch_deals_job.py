"""The `fetch_deals(source)` job: what a run stores, how it retries, and when it is scheduled."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from pickled.deals import Channel, DealRecord, FetchRejected, FetchResult, deals_valid_on
from pickled.jobs import app
from pickled.jobs.deals import fetch_deals, fetch_deals_now
from pickled.stores import REQUEST_BUDGET, RequestBudgetExceeded, Store, spend_request

AMSTERDAM = ZoneInfo("Europe/Amsterdam")
NOW = datetime(2026, 10, 12, 6, 0, tzinfo=AMSTERDAM)


class FakeSource:
    requests_per_fetch = 25

    def __init__(self, store, deals):
        self.store = store
        self.deals = deals
        self.asked_for = None

    def fetch(self, on):
        self.asked_for = on
        return FetchResult(store=self.store, on=on, raw={}, deals=self.deals)


def deal(source_id):
    return DealRecord(
        source_id=source_id,
        title=source_id,
        discount_text="1+1 gratis",
        valid_from=date(2026, 10, 12),
        valid_to=date(2026, 10, 18),
        channel=Channel.BOTH,
    )


def test_a_run_fetches_todays_deals_and_stores_them(db_session, sessions):
    source = FakeSource(Store.AH, [deal("a"), deal("b")])

    fetch_deals_now(Store.AH, sessions, now=NOW, source_for=lambda store, client: source)

    assert source.asked_for == date(2026, 10, 12)
    assert [d.source_id for d in deals_valid_on(db_session, date(2026, 10, 14))] == ["a", "b"]


def test_a_rejected_run_stores_nothing(db_session, sessions):
    source = FakeSource(Store.AH, [])

    with pytest.raises(FetchRejected):
        fetch_deals_now(Store.AH, sessions, now=NOW, source_for=lambda store, client: source)

    assert deals_valid_on(db_session, date(2026, 10, 14)) == []


def test_a_run_the_budget_cannot_cover_is_not_started(db_session, sessions):
    for _ in range(REQUEST_BUDGET - 24):
        spend_request(db_session, Store.AH, now=NOW)
    source = FakeSource(Store.AH, [deal("a")])

    with pytest.raises(RequestBudgetExceeded):
        fetch_deals_now(Store.AH, sessions, now=NOW, source_for=lambda store, client: source)

    assert source.asked_for is None


class Attempt:
    def __init__(self, attempts):
        self.attempts = attempts


def retries(exception, attempts):
    decision = fetch_deals.retry_strategy.get_retry_decision(
        exception=exception, job=Attempt(attempts)
    )
    return decision is not None


def test_a_failed_run_is_retried_three_times_with_backoff():
    error = FetchRejected("too few")

    assert [retries(error, attempts) for attempts in range(4)] == [True, True, True, False]
    retry_at = [
        fetch_deals.retry_strategy.get_retry_decision(exception=error, job=Attempt(n)).retry_at
        for n in range(3)
    ]
    assert retry_at[0] < retry_at[1] < retry_at[2]


def test_a_spent_request_budget_is_not_retried():
    assert not retries(RequestBudgetExceeded(Store.AH, date(2026, 10, 12)), 0)


def next_runs(after: datetime) -> dict[tuple[str, str], datetime]:
    """When each fetch_deals schedule next fires after `after`, in Amsterdam time."""
    runs = {}
    for (name, periodic_id), task in app.periodic_registry.periodic_tasks.items():
        if name == fetch_deals.name:
            timestamp = task.croniter.get_next(ret_type=float, start_time=after.timestamp())
            source = task.configure_kwargs["task_kwargs"]["source"]
            runs[(periodic_id, source)] = datetime.fromtimestamp(timestamp, AMSTERDAM)
    return runs


def test_deals_are_fetched_on_each_stores_schedule_in_amsterdam_time():
    sunday = datetime(2026, 10, 11, 12, 0, tzinfo=AMSTERDAM)

    runs = sorted((when, source) for (_, source), when in next_runs(sunday).items())

    assert runs == [
        (datetime(2026, 10, 12, 6, 0, tzinfo=AMSTERDAM), "ah"),
        (datetime(2026, 10, 14, 6, 0, tzinfo=AMSTERDAM), "jumbo"),
        (datetime(2026, 10, 15, 17, 0, tzinfo=AMSTERDAM), "ah"),
        (datetime(2026, 10, 15, 17, 0, tzinfo=AMSTERDAM), "jumbo"),
    ]


def test_the_schedule_follows_amsterdam_time_across_the_clock_change():
    after_dst = datetime(2026, 11, 1, 12, 0, tzinfo=AMSTERDAM)

    runs = sorted(when for (_, source), when in next_runs(after_dst).items() if source == "ah")

    assert runs[0] == datetime(2026, 11, 2, 6, 0, tzinfo=AMSTERDAM)


def test_only_one_fetch_per_source_can_be_queued():
    locks = {
        task.configure_kwargs["task_kwargs"]["source"]: task.configure_kwargs["queueing_lock"]
        for (name, _), task in app.periodic_registry.periodic_tasks.items()
        if name == fetch_deals.name
    }

    assert locks == {"ah": "fetch_deals:ah", "jumbo": "fetch_deals:jumbo"}
