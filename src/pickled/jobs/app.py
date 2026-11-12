"""The Procrastinate app. Its queue lives in the `procrastinate` schema of our database."""

from datetime import datetime

import procrastinate
from croniter import croniter
from procrastinate import RetryStrategy
from procrastinate.tasks import Task

from pickled.config import Settings
from pickled.llm import out_of_credit
from pickled.migrate import PROCRASTINATE_SCHEMA, schema_conninfo
from pickled.stores import AMSTERDAM

app = procrastinate.App(
    connector=procrastinate.PsycopgConnector(
        conninfo=schema_conninfo(Settings().database_url, PROCRASTINATE_SCHEMA)
    ),
    import_paths=[
        "pickled.jobs.balance",
        "pickled.jobs.deals",
        "pickled.jobs.draft",
        "pickled.jobs.prices",
        "pickled.jobs.reflect",
        "pickled.jobs.start",
    ],
)


class LlmJobRetry(RetryStrategy):
    """Retry a failed LLM job, but not once Runware's credit has run out (spec §9)."""

    def get_retry_decision(self, *, exception, job):
        if out_of_credit(exception):
            return None
        return super().get_retry_decision(exception=exception, job=job)


def schedule(task: Task, *, cron: str, periodic_id: str, **options) -> None:
    """Run `task` on `cron`, read in Amsterdam time.

    Procrastinate reads crons in UTC, so each schedule gets an Amsterdam-aware croniter. This
    replaces `PeriodicTask.croniter`, a cached property inside Procrastinate (3.10); the
    schedule tests catch it if an upgrade changes that.
    """
    app.periodic(cron=cron, periodic_id=periodic_id, **options)(task)
    periodic_task = app.periodic_registry.periodic_tasks[(task.name, periodic_id)]
    periodic_task.__dict__["croniter"] = croniter(cron, datetime.now(AMSTERDAM))
