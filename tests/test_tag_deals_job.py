"""The `tag_deals(source)` job: queued after each fetch, run with the match model."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import anthropic
import httpx2
import pytest
from fakes import FakeChatModel, tool_call
from sqlalchemy import select

import pickled.jobs.deals
from pickled.cli import main
from pickled.deals import Channel, Deal, DealRecord, FetchRejected, FetchResult, save_fetch
from pickled.jobs.deals import fetch_deals, tag_deals_job, tag_deals_now
from pickled.llm import LlmCall, Role, make_chat_model
from pickled.stores import Store

AMSTERDAM = ZoneInfo("Europe/Amsterdam")
NOW = datetime(2026, 10, 12, 7, 0, tzinfo=AMSTERDAM)


def queued(job_queue) -> list[tuple[str, dict]]:
    return [(job["task_name"], job["args"]) for job in job_queue.jobs.values()]


def test_tagging_uses_the_match_model_and_records_its_calls_as_the_tag_deals_job(
    db_session, sessions
):
    deal = DealRecord(
        source_id="1",
        title="Robijn wasmiddel",
        discount_text="1+1 gratis",
        valid_from=date(2026, 10, 12),
        valid_to=date(2026, 10, 18),
        channel=Channel.BOTH,
    )
    save_fetch(
        db_session,
        FetchResult(store=Store.AH, on=date(2026, 10, 12), raw={}, deals=[deal]),
        now=NOW,
    )
    deal_id = db_session.execute(select(Deal.id)).scalar_one()
    fake = FakeChatModel(
        replies=[tool_call("DealTags", {"deals": [{"deal": deal_id, "non_food": True}]})]
    )
    model = make_chat_model(Role.TAG_DEALS, sessions=sessions, build=lambda name, settings: fake)

    tag_deals_now(Store.AH, sessions, now=NOW, model=model)

    [call] = db_session.scalars(select(LlmCall))
    assert (call.role, call.job) == (Role.TAG_DEALS, "tag_deals")


@pytest.fixture
def fetched(monkeypatch):
    stores = []
    monkeypatch.setattr(
        pickled.jobs.deals, "fetch_deals_now", lambda store, sessions, now: stores.append(store)
    )
    return stores


def test_a_fetch_queues_tagging_for_its_store(fetched, job_queue):
    fetch_deals(source="jumbo")

    assert queued(job_queue) == [("tag_deals", {"source": "jumbo"})]


def test_a_second_fetch_while_tagging_is_still_queued_queues_nothing_more(fetched, job_queue):
    fetch_deals(source="ah")
    fetch_deals(source="ah")

    assert queued(job_queue) == [("tag_deals", {"source": "ah"})]


def test_a_failed_fetch_queues_no_tagging(monkeypatch, job_queue):
    def reject(store, sessions, now):
        raise FetchRejected("too few")

    monkeypatch.setattr(pickled.jobs.deals, "fetch_deals_now", reject)

    with pytest.raises(FetchRejected):
        fetch_deals(source="ah")

    assert queued(job_queue) == []


@pytest.fixture
def tagged(monkeypatch):
    stores = []
    monkeypatch.setattr(
        pickled.jobs.deals, "tag_deals_now", lambda store, sessions, now: stores.append(store)
    )
    return stores


def test_jobs_run_tag_deals_for_one_source(tagged):
    main(["jobs", "run", "tag_deals", "--source", "jumbo"])

    assert tagged == [Store.JUMBO]


def test_jobs_run_tag_deals_without_a_source_tags_every_store(tagged):
    main(["jobs", "run", "tag_deals"])

    assert tagged == [Store.AH, Store.JUMBO]


class Attempt:
    def __init__(self, attempts):
        self.attempts = attempts


def retried(exception) -> bool:
    decision = tag_deals_job.retry_strategy.get_retry_decision(exception=exception, job=Attempt(0))
    return decision is not None


def test_a_failed_tagging_run_is_retried():
    assert retried(RuntimeError("the model timed out"))


def test_tagging_is_not_retried_once_runware_says_the_credit_has_run_out():
    request = httpx2.Request("POST", "https://api.runware.ai/v1/messages")
    no_credit = anthropic.APIStatusError(
        "Insufficient credit", response=httpx2.Response(402, request=request), body=None
    )

    assert not retried(no_credit)
