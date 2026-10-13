"""Background jobs on Procrastinate, run by `pickled worker` (ADR 0002).

All schedules are in Europe/Amsterdam time.
"""

from pickled.jobs.app import app
from pickled.jobs.deals import run_fetch_deals, run_tag_deals

# What `pickled jobs run <job> [--source …]` can run by hand.
RUNNABLE = {"fetch_deals": run_fetch_deals, "tag_deals": run_tag_deals}


def run_job(name: str, source: str | None = None) -> None:
    """Run job `name` now, in this process, instead of queueing it."""
    RUNNABLE[name](source)


def run_worker() -> None:
    """Work the queue and defer scheduled jobs until stopped."""
    app.run_worker()


__all__ = ["RUNNABLE", "app", "run_job", "run_worker"]
