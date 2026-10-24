from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

# Import every module's tables so they register on Base.metadata.
import pickled.deals  # noqa: F401
import pickled.ingredients  # noqa: F401
import pickled.llm  # noqa: F401
import pickled.planning  # noqa: F401
import pickled.seasonal  # noqa: F401
import pickled.stores  # noqa: F401
import pickled.taste  # noqa: F401
from pickled.config import Settings
from pickled.db import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# Schemas Alembic never touches: the LangGraph checkpointer owns `langgraph`.
IGNORED_SCHEMAS = {"langgraph"}


def include_name(name, type_, parent_names):
    if type_ == "schema":
        return name not in IGNORED_SCHEMAS
    return True


def run_migrations() -> None:
    url = config.get_main_option("sqlalchemy.url") or Settings().database_url
    engine = create_engine(url)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=Base.metadata,
            include_name=include_name,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    raise SystemExit("Offline migrations are not supported; run `pickled db upgrade`.")
run_migrations()
