"""`draft_meal_plan(week)`: the agent drafts the Meal Plan for a week (spec §6, §7).

It runs on Thursday evening for the coming Shopping Day, after both stores' Deals are fetched.
If a store's Deals are still missing, it tries again until Friday noon, then drafts with what
there is.
"""

import asyncio
import logging
from collections.abc import Callable
from datetime import date, datetime, time, timedelta

from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Checkpointer
from procrastinate.exceptions import AlreadyEnqueued
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from pickled.agent import DRAFT_CALL_LIMIT, PlanContext, draft_request, make_agent, thread
from pickled.config import Settings
from pickled.db import default_sessions
from pickled.deals import deals_valid_on
from pickled.ingredients import ProductPicker, open_product_picker
from pickled.jobs.app import app, schedule
from pickled.jobs.deals import LlmJobRetry
from pickled.jobs.notify import notify
from pickled.llm import Role, llm_context, make_chat_model
from pickled.migrate import LANGGRAPH_SCHEMA, schema_conninfo
from pickled.planning import (
    MealPlan,
    PlanStatus,
    Prices,
    meal_plan_for,
    next_shopping_day,
    picked_prices,
    plan_lock,
    start_meal_plan,
)
from pickled.stores import AMSTERDAM, Store

logger = logging.getLogger(__name__)

# Thursday 18:00, an hour after both stores' Deals are fetched for the weekend.
SCHEDULE = "0 18 * * 4"
# How long to wait before looking again for a store's missing Deals.
DEALS_RETRY = timedelta(hours=1)
# Drafting waits for missing Deals until this time on the Friday before the Shopping Day.
DEALS_DEADLINE = time(12)
# One draft queued at a time.
QUEUEING_LOCK = "draft_meal_plan"


class MissingDeals(Exception):
    """A store has no Deals for the Shopping Day yet: look again at `retry_at`."""

    def __init__(self, stores: list[Store], retry_at: datetime):
        super().__init__(f"No Deals yet from {', '.join(stores)}; trying again at {retry_at}")
        self.retry_at = retry_at


async def draft_meal_plan_now(
    week_start: date,
    *,
    sessions: sessionmaker[Session],
    model: BaseChatModel,
    checkpointer: Checkpointer,
    prices: Callable[[Session, MealPlan], Prices],
    picker: ProductPicker | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(AMSTERDAM),
    hint: str | None = None,
) -> None:
    """Draft the Meal Plan for the week from `week_start` with `model`, through the agent.

    A week whose draft is finished is left alone. A run that failed part-way resumes where it
    stopped; one that hit the call limit stays a partial draft.
    """
    now = clock()
    meal_plan_id, week = _meal_plan(sessions, week_start, now)
    agent = make_agent(model, call_limit=DRAFT_CALL_LIMIT, checkpointer=checkpointer)
    config = thread(meal_plan_id)
    context = PlanContext(meal_plan_id, sessions, prices, picker, clock)
    async with plan_lock(sessions, meal_plan_id):
        # Looked at only with the lock held, as another run may have drafted it meanwhile.
        with sessions() as session:
            meal_plan = session.get_one(MealPlan, meal_plan_id)
            if meal_plan.drafted_at is not None or meal_plan.status != PlanStatus.DRAFT:
                logger.info("draft_meal_plan %s: already drafted", week_start)
                return
        with llm_context(job="draft_meal_plan", meal_plan=meal_plan_id):
            state = await agent.aget_state(config)
            if state.next:
                logger.info("draft_meal_plan %s: resuming", week_start)
                await agent.ainvoke(None, config, context=context)
            elif state.values.get("messages"):
                logger.info("draft_meal_plan %s: left partial by an earlier run", week_start)
                return
            else:
                request = {"messages": [draft_request(week, hint)]}
                await agent.ainvoke(request, config, context=context)

    with sessions() as session:
        drafted = session.get_one(MealPlan, meal_plan_id).drafted_at is not None
    logger.info("draft_meal_plan %s: %s", week_start, "drafted" if drafted else "partial")
    notify("meal_plan_drafted" if drafted else "meal_plan_partial", week_start=week_start)


def _meal_plan(
    sessions: sessionmaker[Session], week_start: date, now: datetime
) -> tuple[int, list[date]]:
    """The week's Meal Plan, started if it has none yet once the Deals are in."""
    try:
        with sessions.begin() as session:
            meal_plan = meal_plan_for(session, week_start)
            if meal_plan is None:
                _check_deals(session, week_start, now)
                meal_plan = start_meal_plan(session, week_start, now=now)
            return meal_plan.id, meal_plan.week
    except IntegrityError:
        # Another run started the week's plan at the same moment: draft that one.
        with sessions() as session:
            meal_plan = meal_plan_for(session, week_start)
            assert meal_plan is not None
            return meal_plan.id, meal_plan.week


def deals_deadline(week_start: date) -> datetime:
    """When drafting stops waiting for missing Deals: the Friday noon before `week_start`."""
    return datetime.combine(week_start - timedelta(days=1), DEALS_DEADLINE, AMSTERDAM)


def _check_deals(session: Session, week_start: date, now: datetime) -> None:
    deadline = deals_deadline(week_start)
    if now >= deadline:
        return
    found = {deal.store for deal in deals_valid_on(session, week_start)}
    missing = [store for store in Store if store not in found]
    if missing:
        raise MissingDeals(missing, retry_at=min(now + DEALS_RETRY, deadline))


async def draft_with_the_app(week_start: date) -> None:
    """Draft with the app's database, draft model, Product picks and checkpointer."""
    sessions = default_sessions()
    conninfo = schema_conninfo(Settings().database_url, LANGGRAPH_SCHEMA)
    with open_product_picker(sessions) as picker:
        async with AsyncPostgresSaver.from_conn_string(conninfo) as checkpointer:
            await draft_meal_plan_now(
                week_start,
                sessions=sessions,
                model=make_chat_model(Role.DRAFT, sessions=sessions),
                checkpointer=checkpointer,
                prices=lambda session, meal_plan: picked_prices(session, meal_plan, picker),
                picker=picker,
            )


@app.task(name="draft_meal_plan", retry=LlmJobRetry(max_attempts=2, wait=600))
async def draft_meal_plan(week: str | None = None, timestamp: int | None = None) -> None:
    """Draft the Meal Plan for the week from Shopping Day `week`. By default that is the next
    one after the time the job was scheduled (`timestamp`), or after now when run by hand.

    While Deals are missing it queues a fresh job for later rather than retrying, so the
    waiting doesn't use up the retries a failed draft gets.
    """
    if week is not None:
        week_start = date.fromisoformat(week)
    else:
        scheduled = datetime.now(AMSTERDAM)
        if timestamp is not None:
            scheduled = datetime.fromtimestamp(timestamp, AMSTERDAM)
        week_start = next_shopping_day(scheduled.date())
    logger.info("draft_meal_plan %s: start", week_start)
    try:
        await draft_with_the_app(week_start)
    except MissingDeals as missing:
        logger.info("draft_meal_plan %s: %s", week_start, missing)
        try:
            await draft_meal_plan.configure(
                schedule_at=missing.retry_at, queueing_lock=QUEUEING_LOCK
            ).defer_async(week=week_start.isoformat())
        except AlreadyEnqueued:
            logger.info("draft_meal_plan %s: a draft is already queued", week_start)


def run_draft_meal_plan() -> None:
    """Run `draft_meal_plan` here and now for the next Shopping Day."""
    asyncio.run(draft_meal_plan())


schedule(draft_meal_plan, cron=SCHEDULE, periodic_id="thursday", queueing_lock=QUEUEING_LOCK)
