"""Bringing a database up to date: Alembic migrations, the LangGraph checkpointer, Procrastinate.

Alembic only manages `public`. The LangGraph checkpointer owns the `langgraph` schema and
Procrastinate's job queue owns `procrastinate`; each is set up by its own library.
"""

import asyncio
from pathlib import Path

import psycopg
from alembic import command
from alembic.config import Config
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from procrastinate.schema import SchemaManager
from sqlalchemy.engine import URL, make_url

LANGGRAPH_SCHEMA = "langgraph"
PROCRASTINATE_SCHEMA = "procrastinate"
MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def schema_conninfo(database_url: str | URL, schema: str) -> str:
    """A psycopg connection string whose search path is `schema`, for a library's own tables."""
    url = make_url(database_url).set(drivername="postgresql")
    url = url.update_query_dict({"options": f"-csearch_path={schema}"})
    return url.render_as_string(hide_password=False)


def upgrade(database_url: str | URL) -> None:
    """Run every Alembic migration, then set up the LangGraph and Procrastinate tables."""
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    url = make_url(database_url).render_as_string(hide_password=False)
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")
    asyncio.run(_setup_langgraph(database_url))
    _setup_procrastinate(database_url)


async def _setup_langgraph(database_url: str | URL) -> None:
    conninfo = make_url(database_url).set(drivername="postgresql")
    async with await psycopg.AsyncConnection.connect(
        conninfo.render_as_string(hide_password=False), autocommit=True
    ) as conn:
        await conn.execute(f"CREATE SCHEMA IF NOT EXISTS {LANGGRAPH_SCHEMA}")
    conninfo = schema_conninfo(database_url, LANGGRAPH_SCHEMA)
    async with AsyncPostgresSaver.from_conn_string(conninfo) as saver:
        await saver.setup()


def _setup_procrastinate(database_url: str | URL) -> None:
    """Create Procrastinate's schema once. Upgrading Procrastinate needs its migration SQL."""
    conninfo = schema_conninfo(database_url, PROCRASTINATE_SCHEMA)
    with psycopg.connect(conninfo, autocommit=True) as conn:
        conn.execute(f"CREATE SCHEMA IF NOT EXISTS {PROCRASTINATE_SCHEMA}")
        installed = conn.execute(
            "SELECT to_regclass(%s)", [f"{PROCRASTINATE_SCHEMA}.procrastinate_jobs"]
        ).fetchone()
        if installed is None or installed[0] is None:
            with conn.transaction():
                conn.execute(SchemaManager.get_schema())
