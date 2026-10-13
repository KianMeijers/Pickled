"""`pickled seasonal import` downloads the calendar and loads it in one transaction."""

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import pickled.seasonal
from pickled import migrate
from pickled.cli import main
from pickled.seasonal import seasonal_for

FIXTURE = Path(__file__).parent / "fixtures" / "seasonal_calendar_made_up.html"


@pytest.fixture
def database(scratch_database):
    """A migrated database of its own: the command commits, so it can't share `db_session`."""
    migrate.upgrade(scratch_database)
    engine = create_engine(scratch_database)
    yield engine
    engine.dispose()


@pytest.fixture
def calendar_page(monkeypatch):
    """Serve the made-up page in place of the Voedingscentrum page; set `.page` to change it."""

    class Calendar:
        page = FIXTURE.read_text()

    monkeypatch.setattr(pickled.seasonal, "download_calendar", lambda: Calendar.page)
    return Calendar


def names(engine, month) -> list[str]:
    with Session(engine) as session:
        return [item.ingredient.name for item in seasonal_for(session, month)]


def test_seasonal_import_loads_the_calendar(database, calendar_page, capsys):
    main(["seasonal", "import"])

    assert names(database, 5) == ["aardbei", "asperge", "spinazie"]
    assert "Seasonal Produce" in capsys.readouterr().out


def test_seasonal_import_fails_loudly_and_keeps_the_old_seasonal_produce(database, calendar_page):
    main(["seasonal", "import"])
    calendar_page.page = calendar_page.page.replace('"name": "Mei"', '"name": "Mai"')

    with pytest.raises(SystemExit, match="'Mai' is not a month"):
        main(["seasonal", "import"])

    assert names(database, 5) == ["aardbei", "asperge", "spinazie"]
