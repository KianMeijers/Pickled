"""The advisory locks on a Meal Plan: draft jobs and chat turns change a plan one at a time.

Each lock is a session-level lock on a connection of its own, so it lasts across the many
transactions of a draft or a chat turn. It is only ever taken with `pg_try_advisory_lock`,
which never blocks: a cancelled wait then holds nothing, and a cancelled holder unlocks in a
`finally` that has nothing to await.
"""

import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager, nullcontext

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

# The first key of the two-key advisory lock, so these locks can't clash with any other.
MEAL_PLAN_LOCKS = 1
# Held by a draft job for as long as it runs, beside the Meal Plan's lock.
DRAFT_LOCKS = 2

LOCK = text("SELECT pg_advisory_lock(:space, CAST(:id AS integer))")
UNLOCK = text("SELECT pg_advisory_unlock(:space, CAST(:id AS integer))")
TRY_LOCK = text("SELECT pg_try_advisory_lock(:space, CAST(:id AS integer))")

# How long to wait before trying a held lock again.
RETRY = 0.2


@asynccontextmanager
async def plan_lock(sessions: sessionmaker[Session], meal_plan_id: int) -> AsyncIterator[None]:
    """Hold Meal Plan `meal_plan_id`'s lock, waiting for it if a job or a chat turn has it.
    The wait sleeps on the event loop, so other jobs on the worker go on meanwhile."""
    async with _held(sessions, MEAL_PLAN_LOCKS, meal_plan_id):
        yield


@asynccontextmanager
async def draft_lock(sessions: sessionmaker[Session], meal_plan_id: int) -> AsyncIterator[None]:
    """Mark Meal Plan `meal_plan_id` as being drafted, for as long as the block runs."""
    async with _held(sessions, DRAFT_LOCKS, meal_plan_id):
        yield


@contextmanager
def plan_lock_if_free(sessions: sessionmaker[Session], meal_plan_id: int) -> Iterator[bool]:
    """Hold Meal Plan `meal_plan_id`'s lock if nothing else has it: whether it is held."""
    with _tried(sessions, MEAL_PLAN_LOCKS, meal_plan_id) as held:
        yield held


def draft_running(sessions: sessionmaker[Session], meal_plan_id: int) -> bool:
    """Whether a draft job is at work on Meal Plan `meal_plan_id` right now."""
    with _tried(sessions, DRAFT_LOCKS, meal_plan_id) as held:
        return not held


@asynccontextmanager
async def _held(sessions: sessionmaker[Session], space: int, id: int) -> AsyncIterator[None]:
    keys = {"space": space, "id": id}
    with _connection(sessions) as connection:
        while not connection.execute(TRY_LOCK, keys).scalar_one():
            await asyncio.sleep(RETRY)
        try:
            yield
        finally:
            connection.execute(UNLOCK, keys)


@contextmanager
def _tried(sessions: sessionmaker[Session], space: int, id: int) -> Iterator[bool]:
    keys = {"space": space, "id": id}
    with _connection(sessions) as connection:
        held = connection.execute(TRY_LOCK, keys).scalar_one()
        try:
            yield held
        finally:
            if held:
                connection.execute(UNLOCK, keys)


def _connection(sessions: sessionmaker[Session]):
    """A connection of its own to hold a session-level lock on; in tests, the test's own."""
    bind = sessions.kw["bind"]
    if isinstance(bind, Engine):
        return bind.connect().execution_options(isolation_level="AUTOCOMMIT")
    return nullcontext(bind)
