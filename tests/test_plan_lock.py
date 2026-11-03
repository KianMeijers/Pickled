"""The Meal Plan's advisory lock: draft jobs and chat turns change a plan one at a time."""

import asyncio
import threading
import time

from sqlalchemy.orm import sessionmaker

from pickled.planning import plan_lock
from pickled.planning.locks import LOCK, MEAL_PLAN_LOCKS, TRY_LOCK, UNLOCK

MEAL_PLAN_ID = 987_654
HELD_FOR = 0.5


def test_waiting_for_the_lock_leaves_other_jobs_running(test_engine):
    keys = {"space": MEAL_PLAN_LOCKS, "id": MEAL_PLAN_ID}
    holder = test_engine.connect().execution_options(isolation_level="AUTOCOMMIT")
    holder.execute(LOCK, keys)
    # Released from another thread, so a waiter that blocks the event loop can't hang the test.
    release = threading.Timer(HELD_FOR, lambda: holder.execute(UNLOCK, keys))
    ticks = 0

    async def other_job():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.05)
            ticks += 1

    async def scenario():
        ticker = asyncio.create_task(other_job())
        await asyncio.sleep(0)
        started = time.monotonic()
        async with plan_lock(sessionmaker(bind=test_engine), MEAL_PLAN_ID):
            waited, ticks_while_waiting = time.monotonic() - started, ticks
        ticker.cancel()
        return waited, ticks_while_waiting

    release.start()
    try:
        waited, ticks_while_waiting = asyncio.run(scenario())
    finally:
        release.join()
        holder.close()

    assert waited >= HELD_FOR * 0.9
    assert ticks_while_waiting >= 5


def test_a_cancelled_wait_leaves_the_lock_free(test_engine):
    keys = {"space": MEAL_PLAN_LOCKS, "id": MEAL_PLAN_ID}
    holder = test_engine.connect().execution_options(isolation_level="AUTOCOMMIT")
    holder.execute(LOCK, keys)

    async def scenario():
        async def wait_for_the_lock():
            async with plan_lock(sessionmaker(bind=test_engine), MEAL_PLAN_ID):
                pass

        waiter = asyncio.create_task(wait_for_the_lock())
        await asyncio.sleep(HELD_FOR)
        waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)
        holder.execute(UNLOCK, keys)
        await asyncio.sleep(HELD_FOR)

    try:
        asyncio.run(scenario())
    finally:
        holder.close()

    with test_engine.connect() as other:
        assert other.execute(TRY_LOCK, keys).scalar_one()
        other.execute(UNLOCK, keys)
