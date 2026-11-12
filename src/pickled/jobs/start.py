"""`start_planning(week)`: the first run, from onboarding to a drafted Meal Plan (spec §8).

Before the first draft no Deals are stored yet, so this fetches and tags both stores' Deals
here, one after the other, and then drafts. Queued separately, the draft would find no Deals
and wait an hour for them.
"""

import asyncio
import logging
from datetime import datetime

from procrastinate.exceptions import AlreadyEnqueued

from pickled.db import default_sessions
from pickled.jobs.app import app
from pickled.jobs.deals import fetch_deals_now, tag_deals_now
from pickled.jobs.draft import QUEUEING_LOCK, draft_meal_plan
from pickled.llm import out_of_credit
from pickled.stores import AMSTERDAM, Store

logger = logging.getLogger(__name__)

DRAFT_AGAIN_AFTER_SECONDS = 600


@app.task(name="start_planning")
async def start_planning(week: str) -> None:
    """Fetch and tag each store's Deals, then draft the Meal Plan from Shopping Day `week`.

    A store whose Deals can't be fetched is left out: the draft then waits for its Deals as
    a scheduled draft does.
    """
    logger.info("start_planning %s: start", week)
    sessions = default_sessions()
    for store in Store:
        try:
            now = datetime.now(AMSTERDAM)
            await asyncio.to_thread(fetch_deals_now, store, sessions, now=now)
            await asyncio.to_thread(tag_deals_now, store, sessions, now=now)
        except Exception:
            logger.exception("start_planning %s: no Deals from %s", week, store)
    try:
        await draft_meal_plan(week=week)
    except Exception as error:
        if out_of_credit(error):
            raise
        # Run here the draft has none of its job's retries, so it is queued to get them,
        # without fetching the Deals again.
        logger.exception("start_planning %s: the draft failed; queueing it again", week)
        try:
            await draft_meal_plan.configure(
                queueing_lock=QUEUEING_LOCK, schedule_in={"seconds": DRAFT_AGAIN_AFTER_SECONDS}
            ).defer_async(week=week)
        except AlreadyEnqueued:
            logger.info("start_planning %s: a draft is already queued", week)
    logger.info("start_planning %s: done", week)
