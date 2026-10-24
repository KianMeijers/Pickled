"""Background jobs on Procrastinate, run by `pickled worker` (ADR 0002).

All schedules are in Europe/Amsterdam time.
"""

from pickled.jobs.app import app
from pickled.jobs.deals import run_fetch_deals, run_tag_deals
from pickled.jobs.prices import run_refresh_checkjebon

# What `pickled jobs run <job> [--source …]` can run by hand: the jobs run per store take a
# source, and the store-wide ones don't.
PER_STORE = {"fetch_deals": run_fetch_deals, "tag_deals": run_tag_deals}
STORE_WIDE = {"refresh_checkjebon": run_refresh_checkjebon}
RUNNABLE = PER_STORE.keys() | STORE_WIDE.keys()


def run_job(name: str, source: str | None = None) -> None:
    """Run job `name` now, in this process, instead of queueing it."""
    if name in PER_STORE:
        PER_STORE[name](source)
    else:
        STORE_WIDE[name]()


def run_worker() -> None:
    """Work the queue and defer scheduled jobs until stopped."""
    app.run_worker()


__all__ = ["PER_STORE", "RUNNABLE", "app", "run_job", "run_worker"]
