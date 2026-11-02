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
TRY_LOCK = text("SELECT pg_try_advisory_lock(:space, CAST(:id AS integer))")


def plan_locked(sessions: sessionmaker[Session], meal_plan_id: int) -> bool:
    """Whether a job or a chat turn holds Meal Plan `meal_plan_id`'s lock right now."""
    keys = {"space": MEAL_PLAN_LOCKS, "id": meal_plan_id}
    with _connection(sessions) as connection:
        if not connection.execute(TRY_LOCK, keys).scalar_one():
            return True
        connection.execute(UNLOCK, keys)
        return False


@asynccontextmanager
async def plan_lock(sessions: sessionmaker[Session], meal_plan_id: int) -> AsyncIterator[None]:
    """Hold Meal Plan `meal_plan_id`'s lock, waiting for it if a job or a chat turn has it.

    It is a session-level lock on a connection of its own, so it lasts across the many
    transactions of a draft or a chat turn. The wait is in a thread, so other jobs on the
    worker go on meanwhile.
    """
    keys = {"space": MEAL_PLAN_LOCKS, "id": meal_plan_id}
    with _connection(sessions) as connection:
        await asyncio.to_thread(connection.execute, LOCK, keys)
        try:
            yield
        finally:
            await asyncio.to_thread(connection.execute, UNLOCK, keys)


def _connection(sessions: sessionmaker[Session]):
    """A connection of its own to hold a session-level lock on; in tests, the test's own."""
    bind = sessions.kw["bind"]
    if isinstance(bind, Engine):
        return bind.connect().execution_options(isolation_level="AUTOCOMMIT")
    return nullcontext(bind)
