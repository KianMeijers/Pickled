import os

import pytest
from procrastinate.testing import InMemoryConnector
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, sessionmaker

from pickled import migrate
from pickled.config import Settings
from pickled.jobs import app


def database_url(name: str) -> URL:
    """The Compose Postgres from Settings, pointed at another database."""
    base = os.environ.get("TEST_DATABASE_URL") or Settings().database_url
    return make_url(base).set(database=name)


@pytest.fixture
def scratch_database(monkeypatch):
    """An empty database for one test, set as DATABASE_URL, dropped afterwards."""
    name = "pickled_test_scratch"
    admin = create_engine(database_url("postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"))
        conn.execute(text(f"CREATE DATABASE {name}"))
    url = database_url(name)
    monkeypatch.setenv("DATABASE_URL", url.render_as_string(hide_password=False))
    yield url
    with admin.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"))
    admin.dispose()


@pytest.fixture(scope="session")
def test_engine():
    """The `pickled_test` database, migrated once per test session."""
    url = database_url("pickled_test")
    migrate.upgrade(url)
    engine = create_engine(url)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(test_engine):
    """A Session inside a transaction that is rolled back after the test.

    `session.commit()` in code under test only releases a savepoint, so nothing persists.
    """
    with test_engine.connect() as connection:
        transaction = connection.begin()
        session = Session(bind=connection, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            session.close()
            transaction.rollback()


@pytest.fixture
def sessions(db_session):
    """A sessionmaker whose sessions work in savepoints of `db_session`'s transaction."""
    return sessionmaker(bind=db_session.connection(), join_transaction_mode="create_savepoint")


@pytest.fixture(autouse=True)
def job_queue():
    """An in-memory job queue, so no test queues a job on a real database."""
    connector = InMemoryConnector()
    with app.replace_connector(connector):
        yield connector
