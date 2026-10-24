"""The advisory lock on a Meal Plan: draft jobs and chat turns change a plan one at a time."""

from collections.abc import Iterator
from contextlib import contextmanager, nullcontext

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

# The first key of the two-key advisory lock, so Meal Plan locks can't clash with any other.
MEAL_PLAN_LOCKS = 1

LOCK = text("SELECT pg_advisory_lock(:space, CAST(:id AS integer))")
UNLOCK = text("SELECT pg_advisory_unlock(:space, CAST(:id AS integer))")


@contextmanager
def plan_lock(sessions: sessionmaker[Session], meal_plan_id: int) -> Iterator[None]:
    """Hold Meal Plan `meal_plan_id`'s lock, waiting for it if a job or a chat turn has it.

    It is a session-level lock on a connection of its own, so it lasts across the many
    transactions of a draft or a chat turn.
    """
    bind = sessions.kw["bind"]
    if isinstance(bind, Engine):
        held = bind.connect().execution_options(isolation_level="AUTOCOMMIT")
    else:
        held = nullcontext(bind)
    keys = {"space": MEAL_PLAN_LOCKS, "id": meal_plan_id}
    with held as connection:
        connection.execute(LOCK, keys)
        try:
            yield
        finally:
            connection.execute(UNLOCK, keys)
