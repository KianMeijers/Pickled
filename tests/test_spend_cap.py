"""The monthly LLM spend cap: at 100% the tag, draft and reflect jobs are skipped, unless run by
hand. Evals don't count toward it (spec §9)."""

import asyncio
from datetime import date, datetime
from decimal import Decimal

import pytest
from fakes import FakeChatModel, tool_call
from langgraph.checkpoint.memory import InMemorySaver
from planning_helpers import NOW as PLAN_NOW
from planning_helpers import SATURDAY, FakePrices, plan
from sqlalchemy import select

import pickled.jobs.deals
import pickled.jobs.draft
import pickled.jobs.reflect
from pickled.cli import main
from pickled.deals import Channel, Deal, DealIngredient, DealRecord, FetchResult, save_fetch
from pickled.jobs.deals import tag_deals_now
from pickled.jobs.draft import draft_meal_plan_now
from pickled.jobs.reflect import reflect_on_week_now
from pickled.llm import LlmCall, Role, spend_cap
from pickled.planning import meal_plan_for, weeks_to_reflect_on
from pickled.stores import AMSTERDAM, Store

NOW = datetime(2026, 10, 12, 7, 0, tzinfo=AMSTERDAM)
CAP = Decimal("25")


def spent(session, usd, *, role=Role.CHAT, job=None, at=NOW):
    session.add(
        LlmCall(
            called_at=at,
            role=role,
            model="claude-sonnet-5-5",
            job=job,
            input_tokens=0,
            cache_write_tokens=0,
            cache_read_tokens=0,
            output_tokens=0,
            cost_usd=Decimal(usd),
        )
    )
    session.flush()


def untagged_deal(session):
    deal = DealRecord(
        source_id="1",
        title="Kipfilet",
        discount_text="25% korting",
        valid_from=date(2026, 10, 12),
        valid_to=date(2026, 10, 18),
        channel=Channel.BOTH,
    )
    save_fetch(
        session, FetchResult(store=Store.AH, on=date(2026, 10, 12), raw={}, deals=[deal]), now=NOW
    )


def test_tagging_is_skipped_once_this_months_spend_reaches_the_cap(db_session, sessions):
    untagged_deal(db_session)
    spent(db_session, CAP)
    fake = FakeChatModel(replies=[])

    tag_deals_now(Store.AH, sessions, now=NOW, model=fake)

    assert fake.sent == []
    assert db_session.scalars(select(DealIngredient)).all() == []


def test_this_months_spend_counts_from_midnight_on_the_first_in_amsterdam(db_session):
    spent(db_session, "7", at=datetime(2026, 9, 30, 23, 59, tzinfo=AMSTERDAM))
    spent(db_session, "2", at=datetime(2026, 10, 1, 0, 0, tzinfo=AMSTERDAM))
    spent(db_session, "3", at=NOW)

    assert spend_cap(db_session, now=NOW).spent == Decimal("5")


def test_evals_dont_count_toward_the_cap(db_session):
    spent(db_session, "4", role=Role.EVAL_JUDGE)
    spent(db_session, "6", role=Role.DRAFT, job="eval_run")
    spent(db_session, "1", role=Role.DRAFT, job="draft_meal_plan")

    assert spend_cap(db_session, now=NOW).spent == Decimal("1")


def test_the_cap_warns_from_eighty_percent_and_is_reached_at_a_hundred(db_session):
    spent(db_session, "19.99")
    below = spend_cap(db_session, now=NOW)
    spent(db_session, "0.01")
    warning = spend_cap(db_session, now=NOW)
    spent(db_session, "5")
    reached = spend_cap(db_session, now=NOW)

    assert (below.warning, below.reached) == (False, False)
    assert (warning.warning, warning.reached) == (True, False)
    assert (reached.warning, reached.reached) == (True, True)


def test_the_cap_is_the_setting(db_session, monkeypatch):
    monkeypatch.setenv("PICKLED_LLM_MONTHLY_CAP_USD", "10")
    spent(db_session, "10")

    assert spend_cap(db_session, now=NOW).reached


def test_tagging_run_by_hand_goes_ahead_at_the_cap(db_session, sessions):
    untagged_deal(db_session)
    spent(db_session, CAP)
    deal_id = db_session.scalars(select(Deal.id)).one()
    fake = FakeChatModel(
        replies=[tool_call("DealTags", {"deals": [{"deal": deal_id, "non_food": True}]})]
    )

    tag_deals_now(Store.AH, sessions, now=NOW, model=fake, capped=False)

    assert len(fake.sent) == 1


def test_drafting_is_skipped_at_the_cap(db_session, sessions):
    plan(db_session)
    spent(db_session, CAP, at=PLAN_NOW)
    fake = FakeChatModel(replies=[])

    asyncio.run(
        draft_meal_plan_now(
            SATURDAY,
            sessions=sessions,
            model=fake,
            checkpointer=InMemorySaver(),
            prices=lambda session, meal_plan: FakePrices(),
            clock=lambda: PLAN_NOW,
        )
    )

    assert fake.sent == []
    db_session.expire_all()
    assert meal_plan_for(db_session, SATURDAY).drafted_at is None


def test_reflecting_is_skipped_at_the_cap_and_left_for_a_later_run(db_session, sessions):
    meal_plan = plan(db_session)
    after_the_week = datetime(2026, 10, 24, 3, 0, tzinfo=AMSTERDAM)
    spent(db_session, CAP, at=after_the_week)
    fake = FakeChatModel(replies=[])

    asyncio.run(
        reflect_on_week_now(
            meal_plan.id,
            sessions=sessions,
            model=fake,
            checkpointer=InMemorySaver(),
            clock=lambda: after_the_week,
        )
    )

    assert fake.sent == []
    db_session.expire_all()
    assert weeks_to_reflect_on(db_session, today=after_the_week.date()) == [meal_plan.id]


@pytest.mark.parametrize(
    ("job", "patched", "entry"),
    [
        ("draft_meal_plan", pickled.jobs.draft, "draft_with_the_app"),
        ("reflect_on_week", pickled.jobs.reflect, "reflect_with_the_app"),
    ],
)
def test_jobs_run_by_hand_ignore_the_cap(monkeypatch, job, patched, entry):
    runs = []

    async def record(*args, **options):
        runs.append(options)

    monkeypatch.setattr(patched, entry, record)
    monkeypatch.setattr(pickled.jobs.reflect, "weeks_to_reflect_on", lambda session, today: [1])

    main(["jobs", "run", job])

    assert runs == [{**runs[0], "capped": False}]


def test_tag_deals_run_by_hand_ignores_the_cap(monkeypatch):
    runs = []
    monkeypatch.setattr(
        pickled.jobs.deals, "tag_deals_now", lambda store, sessions, **options: runs.append(options)
    )

    main(["jobs", "run", "tag_deals", "--source", "ah"])

    assert [run["capped"] for run in runs] == [False]
