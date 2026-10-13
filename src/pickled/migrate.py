"""Bringing a database up to date: Alembic migrations, then the LangGraph checkpointer.

Alembic ignores the `langgraph` schema; `AsyncPostgresSaver.setup()` owns it.
"""

import asyncio
from pathlib import Path

import psycopg
from alembic import command
from alembic.config import Config
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy.engine import URL, make_url

LANGGRAPH_SCHEMA = "langgraph"
MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def langgraph_conninfo(database_url: str | URL) -> str:
    """A psycopg connection string that puts the LangGraph checkpointer in its own schema."""
    url = make_url(database_url).set(drivername="postgresql")
    url = url.update_query_dict({"options": f"-csearch_path={LANGGRAPH_SCHEMA}"})
    return url.render_as_string(hide_password=False)


def upgrade(database_url: str | URL) -> None:
    """Run every Alembic migration, then set up the LangGraph checkpointer tables."""
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    url = make_url(database_url).render_as_string(hide_password=False)
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")
    asyncio.run(_setup_langgraph(database_url))


async def _setup_langgraph(database_url: str | URL) -> None:
    conninfo = make_url(database_url).set(drivername="postgresql")
    async with await psycopg.AsyncConnection.connect(
        conninfo.render_as_string(hide_password=False), autocommit=True
    ) as conn:
        await conn.execute(f"CREATE SCHEMA IF NOT EXISTS {LANGGRAPH_SCHEMA}")
    async with AsyncPostgresSaver.from_conn_string(langgraph_conninfo(database_url)) as saver:
        await saver.setup()
