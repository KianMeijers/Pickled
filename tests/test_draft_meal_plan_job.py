"""How the `draft_meal_plan(week)` job is scheduled, retried and run by hand (spec §6)."""

import asyncio
from datetime import date, datetime
from zoneinfo import ZoneInfo

import anthropic
import httpx2
import pytest

import pickled.jobs.draft
from pickled.cli import main
from pickled.jobs import app
from pickled.jobs.draft import MissingDeals, draft_meal_plan
from pickled.planning import next_shopping_day
from pickled.stores import Store

AMSTERDAM = ZoneInfo("Europe/Amsterdam")


def test_the_draft_runs_on_thursday_at_six_in_the_evening_amsterdam_time():
    [(periodic_id, task)] = [
        (periodic_id, task)
        for (name, periodic_id), task in app.periodic_registry.periodic_tasks.items()
        if name == draft_meal_plan.name
    ]
    sunday = datetime(2026, 10, 11, 12, 0, tzinfo=AMSTERDAM)

    timestamp = task.croniter.get_next(ret_type=float, start_time=sunday.timestamp())

    assert datetime.fromtimestamp(timestamp, AMSTERDAM) == datetime(
        2026, 10, 15, 18, 0, tzinfo=AMSTERDAM
    )
    assert task.configure_kwargs["queueing_lock"] == "draft_meal_plan"


class Attempt:
    def __init__(self, attempts):
        self.attempts = attempts


def retry_decision(exception):
    return draft_meal_plan.retry_strategy.get_retry_decision(exception=exception, job=Attempt(0))


def test_a_failed_draft_is_retried():
    assert retry_decision(RuntimeError("the model timed out")) is not None


def test_a_draft_is_not_retried_once_runware_says_the_credit_has_run_out():
    request = httpx2.Request("POST", "https://api.runware.ai/v1/messages")
    no_credit = anthropic.APIStatusError(
        "Insufficient credit", response=httpx2.Response(402, request=request), body=None
    )

    assert retry_decision(no_credit) is None


@pytest.fixture
def drafted(monkeypatch):
    weeks = []

    async def record(week_start):
        weeks.append(week_start)

    monkeypatch.setattr(pickled.jobs.draft, "draft_with_the_app", record)
    return weeks


def test_missing_deals_queue_a_fresh_draft_of_the_same_week_when_the_job_says(
    monkeypatch, job_queue
):
    retry_at = datetime(2026, 10, 15, 19, 0, tzinfo=AMSTERDAM)

    async def missing(week_start):
        raise MissingDeals([Store.JUMBO], retry_at=retry_at)

    monkeypatch.setattr(pickled.jobs.draft, "draft_with_the_app", missing)

    asyncio.run(draft_meal_plan(week="2026-10-17"))

    [job] = job_queue.jobs.values()
    assert (job["task_name"], job["args"], job["attempts"]) == (
        "draft_meal_plan",
        {"week": "2026-10-17"},
        0,
    )
    assert job["scheduled_at"] == retry_at
    assert job["queueing_lock"] == "draft_meal_plan"


def test_the_job_drafts_the_week_it_is_given(drafted):
    asyncio.run(draft_meal_plan(week="2026-10-24"))

    assert drafted == [date(2026, 10, 24)]


def test_the_scheduled_job_drafts_the_shopping_day_after_when_it_was_scheduled(drafted):
    thursday_evening = datetime(2026, 10, 15, 18, 0, tzinfo=AMSTERDAM)

    # A retry may run after midnight on Friday, and must still draft that Saturday's week.
    asyncio.run(draft_meal_plan(timestamp=int(thursday_evening.timestamp())))

    assert drafted == [date(2026, 10, 17)]


def test_jobs_run_drafts_the_next_shopping_day(drafted):
    main(["jobs", "run", "draft_meal_plan"])

    assert drafted == [next_shopping_day(datetime.now(AMSTERDAM).date())]


@pytest.mark.parametrize(
    ("today", "shopping_day"),
    [
        (date(2026, 10, 15), date(2026, 10, 17)),  # Thursday
        (date(2026, 10, 16), date(2026, 10, 17)),  # Friday
        (date(2026, 10, 17), date(2026, 10, 24)),  # Saturday: today's shop is under way
        (date(2026, 10, 18), date(2026, 10, 24)),  # Sunday
    ],
)
def test_the_next_shopping_day_is_the_first_saturday_after_today(today, shopping_day):
    assert next_shopping_day(today) == shopping_day
