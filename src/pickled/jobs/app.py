"""The Procrastinate app. Its queue lives in the `procrastinate` schema of our database."""

from datetime import datetime

import procrastinate
from croniter import croniter
from procrastinate.tasks import Task

from pickled.config import Settings
from pickled.migrate import PROCRASTINATE_SCHEMA, schema_conninfo
from pickled.stores import AMSTERDAM

app = procrastinate.App(
    connector=procrastinate.PsycopgConnector(
        conninfo=schema_conninfo(Settings().database_url, PROCRASTINATE_SCHEMA)
    ),
    import_paths=["pickled.jobs.deals", "pickled.jobs.prices"],
)


def schedule(task: Task, *, cron: str, periodic_id: str, **options) -> None:
    """Run `task` on `cron`, read in Amsterdam time.

    Procrastinate reads crons in UTC, so each schedule gets an Amsterdam-aware croniter. This
    replaces `PeriodicTask.croniter`, a cached property inside Procrastinate (3.10); the
    schedule tests catch it if an upgrade changes that.
    """
    app.periodic(cron=cron, periodic_id=periodic_id, **options)(task)
    periodic_task = app.periodic_registry.periodic_tasks[(task.name, periodic_id)]
    periodic_task.__dict__["croniter"] = croniter(cron, datetime.now(AMSTERDAM))
