"""Each test runs inside a transaction that is rolled back, so writes never leak.

The two tests run in file order: the first writes, the second must not see it.
"""

from sqlalchemy import text


def test_a_test_can_create_and_write_a_table(db_session):
    db_session.execute(text("CREATE TABLE isolation_probe (id bigint)"))
    db_session.execute(text("INSERT INTO isolation_probe VALUES (1)"))
    db_session.commit()

    assert db_session.execute(text("SELECT count(*) FROM isolation_probe")).scalar() == 1


def test_the_next_test_sees_none_of_it(db_session):
    exists = db_session.execute(text("SELECT to_regclass('isolation_probe')")).scalar()

    assert exists is None


def test_the_test_database_is_migrated(db_session):
    version = db_session.execute(text("SELECT version_num FROM alembic_version")).scalar()

    assert version is not None
