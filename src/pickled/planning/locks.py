"""The advisory lock on a Meal Plan: draft jobs and chat turns change a plan one at a time."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, nullcontext

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

# The first key of the two-key advisory lock, so Meal Plan locks can't clash with any other.
MEAL_PLAN_LOCKS = 1

LOCK = text("SELECT pg_advisory_lock(:space, CAST(:id AS integer))")
UNLOCK = text("SELECT pg_advisory_unlock(:space, CAST(:id AS integer))")


@asynccontextmanager
async def plan_lock(sessions: sessionmaker[Session], meal_plan_id: int) -> AsyncIterator[None]:
    """Hold Meal Plan `meal_plan_id`'s lock, waiting for it if a job or a chat turn has it.

    It is a session-level lock on a connection of its own, so it lasts across the many
    transactions of a draft or a chat turn. The wait is in a thread, so other jobs on the
    worker go on meanwhile.
    """
    bind = sessions.kw["bind"]
    if isinstance(bind, Engine):
        held = bind.connect().execution_options(isolation_level="AUTOCOMMIT")
    else:
        held = nullcontext(bind)
    keys = {"space": MEAL_PLAN_LOCKS, "id": meal_plan_id}
    with held as connection:
        await asyncio.to_thread(connection.execute, LOCK, keys)
        try:
            yield
        finally:
            await asyncio.to_thread(connection.execute, UNLOCK, keys)
