"""`refresh_checkjebon` keeps our copy of Jumbo's regular prices from Checkjebon (spec §6)."""

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

import httpx
from procrastinate import RetryStrategy
from sqlalchemy.orm import Session, sessionmaker

from pickled.db import default_sessions
from pickled.ingredients import download_checkjebon, refresh_checkjebon
from pickled.jobs.app import app, schedule
from pickled.stores import AMSTERDAM

logger = logging.getLogger(__name__)

# Weekly, before Thursday's Deal fetch (17:00) and draft (18:00).
SCHEDULE = "0 16 * * 4"
DOWNLOAD_TIMEOUT_SECONDS = 120


def download() -> Any:
    """Checkjebon's data from GitHub: no request to any store, so it isn't counted."""
    with httpx.Client(timeout=DOWNLOAD_TIMEOUT_SECONDS, follow_redirects=True) as client:
        return download_checkjebon(client)


def refresh_checkjebon_now(
    sessions: sessionmaker[Session],
    *,
    now: datetime,
    download: Callable[[], Any] = download,
) -> None:
    """Replace our Jumbo prices with Checkjebon's, or raise and keep the last copy."""
    data = download()
    with sessions.begin() as session:
        refresh = refresh_checkjebon(session, data, now=now)
    logger.info(
        "refresh_checkjebon: %d Jumbo products, %d skipped, %s",
        refresh.products,
        refresh.skipped,
        "changed" if refresh.changed else "unchanged",
    )
    if refresh.stale:
        logger.warning("refresh_checkjebon: Jumbo's data hasn't changed in over 3 days: stale")


@app.task(name="refresh_checkjebon", retry=RetryStrategy(max_attempts=2, wait=1800))
def refresh_checkjebon_job() -> None:
    logger.info("refresh_checkjebon: start")
    refresh_checkjebon_now(default_sessions(), now=datetime.now(AMSTERDAM))


def run_refresh_checkjebon() -> None:
    """Run `refresh_checkjebon` here and now."""
    refresh_checkjebon_job()


schedule(
    refresh_checkjebon_job,
    cron=SCHEDULE,
    periodic_id="weekly",
    queueing_lock="refresh_checkjebon",
)
