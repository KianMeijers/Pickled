"""Whether a draft job is at work on a week, which closes its plan's chat until it is done."""

import asyncio
from datetime import date

from pickled.jobs import app
from pickled.jobs.draft import draft_meal_plan
from pickled.jobs.start import start_planning
from pickled.planning import plan_locked
from pickled.web.services import Services

DRAFT_JOBS = {draft_meal_plan.name, start_planning.name}
WAITING = {"todo", "doing"}


async def drafting(services: Services, week_start: date, meal_plan_id: int | None) -> bool:
    """A draft job holds the week's Meal Plan's lock, or one is queued for the week."""
    if meal_plan_id is not None and await asyncio.to_thread(
        plan_locked, services.sessions, meal_plan_id
    ):
        return True
    jobs = await app.job_manager.list_jobs_async()
    return any(
        job.task_name in DRAFT_JOBS
        and job.status in WAITING
        and job.task_kwargs.get("week") == week_start.isoformat()
        for job in jobs
    )
