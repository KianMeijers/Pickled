"""The status line: warnings only, in Dutch, about the jobs and data planning depends on
(spec §6, §9)."""

import asyncio
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from fakes import FakeChatModel
from langgraph.checkpoint.memory import InMemorySaver
from planning_helpers import AMSTERDAM, ingredient, plan

from pickled.deals import Channel, DealRecord, FetchResult, save_fetch
from pickled.ingredients import Aisle, CheckjebonCheck
from pickled.jobs.deals import fetch_deals
from pickled.jobs.draft import QUEUEING_LOCK, draft_meal_plan
from pickled.jobs.prices import refresh_checkjebon_job
from pickled.llm import LlmBalance, LlmCall, Role
from pickled.seasonal import Freshness, SeasonalProduce
from pickled.stores import Store
from pickled.web import Services
from pickled.web.status import status_line

# Thursday 15 October 2026, the evening the week's draft runs.
NOW = datetime(2026, 10, 15, 18, 0, tzinfo=AMSTERDAM)
TODAY = NOW.date()


def services(sessions, now=NOW):
    return Services(
        sessions=sessions,
        checkpointer=InMemorySaver(),
        chat_model=lambda: FakeChatModel(replies=[]),
        prices=lambda session, meal_plan: None,
        shown_prices=lambda session, meal_plan: None,
        clock=lambda: now,
    )


def status(sessions, now=NOW) -> list[str]:
    return asyncio.run(status_line(services(sessions, now)))


def fetched(session, store, *, at=NOW - timedelta(hours=1), valid_to=TODAY + timedelta(days=3)):
    """A fetch of one Deal at `store`, valid from a few days ago to `valid_to`."""
    deal = DealRecord(
        source_id=f"{store}-{at}",
        title="Kipfilet",
        discount_text="25% korting",
        valid_from=TODAY - timedelta(days=3),
        valid_to=valid_to,
        channel=Channel.BOTH,
    )
    save_fetch(session, FetchResult(store=store, on=at.date(), raw={}, deals=[deal]), now=at)


def in_season(session, month=TODAY.month):
    pompoen = ingredient(session, "pompoen", Aisle.GROENTE_FRUIT)
    session.add(SeasonalProduce(ingredient_id=pompoen.id, month=month, freshness=Freshness.FRESH))
    session.flush()


@pytest.fixture
def all_well(db_session):
    """Both stores' Deals fetched today and the month's Seasonal Produce imported."""
    for store in Store:
        fetched(db_session, store)
    in_season(db_session)


def test_all_well_shows_nothing(all_well, sessions):
    assert status(sessions) == []


def test_a_store_without_current_deals_is_missing(db_session, sessions):
    fetched(db_session, Store.AH)
    fetched(db_session, Store.JUMBO, valid_to=TODAY - timedelta(days=1))
    in_season(db_session)

    assert status(sessions) == ["Er zijn geen aanbiedingen van Jumbo."]


def test_a_store_not_fetched_for_over_a_week_shows_when_it_last_was(db_session, sessions):
    fetched(db_session, Store.AH, at=datetime(2026, 10, 7, 6, 0, tzinfo=AMSTERDAM))
    fetched(db_session, Store.JUMBO)
    in_season(db_session)

    assert status(sessions) == [
        "De aanbiedingen van Albert Heijn zijn voor het laatst opgehaald op woensdag 7 okt."
    ]


def test_stale_checkjebon_prices_are_shown(all_well, db_session, sessions):
    db_session.add(
        CheckjebonCheck(
            checked_at=NOW, content_hash="x", changed=False, stale=True, products=1, skipped=0
        )
    )
    db_session.flush()

    assert status(sessions) == [
        "De Jumbo-prijzen van Checkjebon zijn al dagen niet bijgewerkt; ze kunnen verouderd zijn."
    ]


def test_missing_seasonal_produce_is_shown(db_session, sessions):
    for store in Store:
        fetched(db_session, store)
    in_season(db_session, month=9)

    assert status(sessions) == [
        "Er is geen seizoensgroente voor deze maand: draai `pickled seasonal import`."
    ]


def spent(session, usd):
    session.add(
        LlmCall(
            called_at=NOW,
            role=Role.CHAT,
            model="claude-sonnet-5-5",
            input_tokens=0,
            cache_write_tokens=0,
            cache_read_tokens=0,
            output_tokens=0,
            cost_usd=Decimal(usd),
        )
    )
    session.flush()


def test_the_spend_cap_warns_from_eighty_percent(all_well, db_session, sessions):
    spent(db_session, "20.50")

    assert status(sessions) == ["De LLM-kosten deze maand zijn $ 20,50 van de $ 25,00."]


def test_a_reached_spend_cap_says_what_is_skipped(all_well, db_session, sessions):
    spent(db_session, "25")

    assert status(sessions) == [
        "Het maandbudget van $ 25,00 voor LLM-kosten is op: plannen, aanbiedingen koppelen en "
        "terugblikken worden overgeslagen tot volgende maand. Chatten kan nog."
    ]


def balance(session, usd, at=NOW):
    session.add(LlmBalance(checked_at=at, balance_usd=Decimal(usd)))
    session.flush()


def test_a_low_runware_balance_is_shown(all_well, db_session, sessions):
    balance(db_session, "9", at=NOW - timedelta(days=1))
    balance(db_session, "3.20")

    assert status(sessions) == ["Het Runware-tegoed is laag: $ 3,20."]


def test_a_spent_runware_balance_says_the_credit_has_run_out(all_well, db_session, sessions):
    balance(db_session, "0")

    assert status(sessions) == [
        "Het Runware-tegoed is op: vul het aan, anders kan Pickled niet plannen of chatten."
    ]


def ran(job_queue, task, status, **args):
    """A job run of `task` with `args` that ended in `status`."""
    job_id = task.defer(**args)
    job_queue.jobs[job_id]["status"] = status


def test_a_job_whose_last_run_failed_is_shown(all_well, job_queue, sessions):
    ran(job_queue, fetch_deals, "succeeded", source="ah")
    ran(job_queue, fetch_deals, "failed", source="jumbo")
    ran(job_queue, refresh_checkjebon_job, "failed")

    assert status(sessions) == [
        "Aanbiedingen ophalen (Jumbo) is mislukt; kijk in de logs.",
        "Jumbo-prijzen bijwerken is mislukt; kijk in de logs.",
    ]


def test_a_failed_job_that_has_since_succeeded_is_not_shown(all_well, job_queue, sessions):
    ran(job_queue, fetch_deals, "failed", source="jumbo")
    ran(job_queue, fetch_deals, "succeeded", source="jumbo")

    assert status(sessions) == []


def test_a_partial_draft_is_shown(all_well, db_session, sessions):
    plan(db_session)  # the week of Saturday 17 October, never finished

    assert status(sessions) == [
        "Het plan voor de week van zaterdag 17 okt is maar half af: maak het af in de chat, of "
        "maak het opnieuw."
    ]


def test_a_draft_still_being_made_is_not_partial(all_well, db_session, sessions):
    plan(db_session)
    draft_meal_plan.configure(queueing_lock=QUEUEING_LOCK).defer(week="2026-10-17")

    assert status(sessions) == []
