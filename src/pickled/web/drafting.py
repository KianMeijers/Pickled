"""Whether a draft job is at work on a week, which closes its plan's chat until it is done."""

import asyncio
from datetime import date

from pickled.jobs import app
from pickled.jobs.draft import QUEUEING_LOCK, draft_week
from pickled.planning import draft_running
from pickled.web.services import Services

# Every draft job, the first run's `start_planning` too, is queued under this lock.
WAITING = ("todo", "doing")


async def drafting(services: Services, week_start: date, meal_plan_id: int | None) -> bool:
    """A draft job is drafting the week's Meal Plan, or one is queued or starting for the week.
    A chat turn holding the plan's lock is not a draft."""
    if meal_plan_id is not None and await asyncio.to_thread(
        draft_running, services.sessions, meal_plan_id
    ):
        return True
    for status in WAITING:
        jobs = await app.job_manager.list_jobs_async(queueing_lock=QUEUEING_LOCK, status=status)
        for job in jobs:
            week = draft_week(job.task_kwargs.get("week"), job.task_kwargs.get("timestamp"))
            if week == week_start:
                return True
    return False
