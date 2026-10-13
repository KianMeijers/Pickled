"""The weekly `refresh_checkjebon` job: Jumbo's regular prices from Checkjebon."""

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import pickled.jobs.prices
from pickled.cli import main
from pickled.ingredients import CheckjebonJumboPriceSource
from pickled.jobs import app
from pickled.jobs.prices import refresh_checkjebon_job, refresh_checkjebon_now

AMSTERDAM = ZoneInfo("Europe/Amsterdam")
NOW = datetime(2026, 10, 15, 16, 0, tzinfo=AMSTERDAM)
FIXTURE = Path(__file__).parent / "fixtures" / "checkjebon_made_up.json"


def download():
    return json.loads(FIXTURE.read_text())


def test_a_run_downloads_and_stores_jumbos_prices(db_session, sessions):
    refresh_checkjebon_now(sessions, now=NOW, download=download)

    assert CheckjebonJumboPriceSource().current(db_session, "596629KGR").price_cents == 386


def test_a_run_on_stale_data_warns(sessions, caplog):
    refresh_checkjebon_now(sessions, now=NOW, download=download)

    refresh_checkjebon_now(sessions, now=NOW.replace(day=20), download=download)

    assert "stale" in caplog.text


def test_it_runs_weekly_before_thursdays_fetch_and_draft_in_amsterdam_time():
    [(periodic_id, task)] = [
        (periodic_id, task)
        for (name, periodic_id), task in app.periodic_registry.periodic_tasks.items()
        if name == refresh_checkjebon_job.name
    ]
    sunday = datetime(2026, 11, 1, 12, 0, tzinfo=AMSTERDAM)

    next_run = task.croniter.get_next(ret_type=float, start_time=sunday.timestamp())

    assert datetime.fromtimestamp(next_run, AMSTERDAM) == datetime(
        2026, 11, 5, 16, 0, tzinfo=AMSTERDAM
    )
    assert task.configure_kwargs["queueing_lock"] == "refresh_checkjebon"


def test_jobs_run_refresh_checkjebon(monkeypatch):
    runs = []
    monkeypatch.setattr(
        pickled.jobs.prices, "refresh_checkjebon_now", lambda sessions, now: runs.append(now)
    )

    main(["jobs", "run", "refresh_checkjebon"])

    assert len(runs) == 1


def test_jobs_run_refresh_checkjebon_refuses_a_source():
    with pytest.raises(SystemExit):
        main(["jobs", "run", "refresh_checkjebon", "--source", "ah"])
