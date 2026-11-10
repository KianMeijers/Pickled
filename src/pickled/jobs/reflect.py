"""`reflect_on_week(meal_plan)`: after a Meal Plan's Friday, anything lasting from its
Conversation is merged into the Taste notes (spec §6)."""

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Checkpointer
from sqlalchemy.orm import Session, sessionmaker

from pickled.agent import conversation, is_note, reflect_on_conversation
from pickled.config import Settings
from pickled.db import default_sessions
from pickled.jobs.app import app, schedule
from pickled.jobs.deals import LlmJobRetry
from pickled.jobs.spend import at_the_cap
from pickled.llm import Role, llm_context, make_chat_model
from pickled.migrate import LANGGRAPH_SCHEMA, schema_conninfo
from pickled.planning import MealPlan, weeks_to_reflect_on
from pickled.stores import AMSTERDAM

logger = logging.getLogger(__name__)

# Saturday 03:00, once the plan's Friday is over.
SCHEDULE = "0 3 * * 6"


async def reflect_on_week_now(
    meal_plan_id: int,
    *,
    sessions: sessionmaker[Session],
    model: BaseChatModel,
    checkpointer: Checkpointer,
    clock: Callable[[], datetime] = lambda: datetime.now(AMSTERDAM),
    capped: bool = True,
) -> None:
    """Merge anything lasting from Meal Plan `meal_plan_id`'s Conversation into the Taste notes.

    Each week is reflected on once. A week in which the Household said nothing isn't sent to
    the model. At the monthly spend cap, unless not `capped`, the week is left for a later run.
    """
    if capped and at_the_cap(f"reflect_on_week {meal_plan_id}", sessions, now=clock()):
        return
    messages = await conversation(checkpointer, meal_plan_id)
    with llm_context(job="reflect_on_week", meal_plan=meal_plan_id), sessions.begin() as session:
        # Locked, so two runs at once can't both reflect on the week.
        meal_plan = session.get_one(MealPlan, meal_plan_id, with_for_update=True)
        week_start = meal_plan.week_start
        if meal_plan.reflected_at is not None:
            logger.info("reflect_on_week %s: already reflected on", week_start)
            return
        if any(_households(message) for message in messages):
            reflect_on_conversation(session, week_start, messages, model, now=clock())
        else:
            logger.info("reflect_on_week %s: nothing said to reflect on", week_start)
        meal_plan.reflected_at = clock()
    logger.info("reflect_on_week %s: done", week_start)


def _households(message) -> bool:
    return isinstance(message, HumanMessage) and not is_note(message)


async def reflect_with_the_app(meal_plan_id: int, *, capped: bool = True) -> None:
    """Reflect with the app's database, reflect model and checkpointer."""
    sessions = default_sessions()
    conninfo = schema_conninfo(Settings().database_url, LANGGRAPH_SCHEMA)
    async with AsyncPostgresSaver.from_conn_string(conninfo) as checkpointer:
        await reflect_on_week_now(
            meal_plan_id,
            sessions=sessions,
            model=make_chat_model(Role.REFLECT, sessions=sessions),
            checkpointer=checkpointer,
            capped=capped,
        )


@app.task(name="reflect_on_week", retry=LlmJobRetry(max_attempts=2, wait=600))
async def reflect_on_week(
    meal_plan: int | None = None, timestamp: int | None = None, by_hand: bool = False
) -> None:
    """Reflect on Meal Plan `meal_plan`'s week. By default, on every week that has ended and
    hasn't been reflected on, so a missed Saturday is caught up the next. Run `by_hand`, it
    reflects even at the monthly spend cap."""
    if meal_plan is not None:
        meal_plans = [meal_plan]
    else:
        with default_sessions()() as session:
            meal_plans = weeks_to_reflect_on(session, today=datetime.now(AMSTERDAM).date())
    for meal_plan_id in meal_plans:
        logger.info("reflect_on_week %s: start", meal_plan_id)
        await reflect_with_the_app(meal_plan_id, capped=not by_hand)


def run_reflect_on_week() -> None:
    """Run `reflect_on_week` here and now for every week that is due, even at the spend cap."""
    asyncio.run(reflect_on_week(by_hand=True))


schedule(reflect_on_week, cron=SCHEDULE, periodic_id="saturday", queueing_lock="reflect_on_week")
