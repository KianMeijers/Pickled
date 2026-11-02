"""`start_planning(week)`: the first run, from onboarding to a drafted Meal Plan (spec §8).

Before the first draft no Deals are stored yet, so this fetches and tags both stores' Deals
here, one after the other, and then drafts. Queued separately, the draft would find no Deals
and wait an hour for them.
"""

import asyncio
import logging
from datetime import datetime

from pickled.db import default_sessions
from pickled.jobs.app import app
from pickled.jobs.deals import fetch_deals_now, tag_deals_now
from pickled.jobs.draft import draft_meal_plan
from pickled.stores import AMSTERDAM, Store

logger = logging.getLogger(__name__)


@app.task(name="start_planning")
async def start_planning(week: str) -> None:
    """Fetch and tag each store's Deals, then draft the Meal Plan from Shopping Day `week`.

    A store whose Deals can't be fetched is left out: the draft then waits for its Deals as
    a scheduled draft does.
    """
    sessions = default_sessions()
    for store in Store:
        try:
            now = datetime.now(AMSTERDAM)
            await asyncio.to_thread(fetch_deals_now, store, sessions, now=now)
            await asyncio.to_thread(tag_deals_now, store, sessions, now=now)
        except Exception:
            logger.exception("start_planning %s: no Deals from %s", week, store)
    await draft_meal_plan(week=week)
