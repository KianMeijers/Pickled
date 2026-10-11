from sqlalchemy import create_engine, text

from pickled.cli import main


def test_db_upgrade_migrates_and_creates_the_langgraph_schema(scratch_database):
    main(["db", "upgrade"])

    engine = create_engine(scratch_database)
    with engine.connect() as conn:
        tables = set(
            conn.execute(
                text(
                    "SELECT table_schema || '.' || table_name FROM information_schema.tables "
                    "WHERE table_schema IN ('public', 'langgraph')"
                )
            ).scalars()
        )
        extensions = set(conn.execute(text("SELECT extname FROM pg_extension")).scalars())
    engine.dispose()

    assert "public.alembic_version" in tables
    assert "langgraph.checkpoints" in tables
    assert "pg_trgm" in extensions


def test_db_upgrade_can_run_twice(scratch_database):
    main(["db", "upgrade"])
    main(["db", "upgrade"])
