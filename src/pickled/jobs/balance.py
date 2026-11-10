"""`check_llm_balance`: reads the Runware account balance once a day (spec §6, §9)."""

import logging
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal

import httpx
from sqlalchemy.orm import Session, sessionmaker

from pickled.config import Settings
from pickled.db import default_sessions
from pickled.jobs.app import app, schedule
from pickled.jobs.deals import LlmJobRetry
from pickled.llm import LlmBalance, read_runware_balance
from pickled.stores import AMSTERDAM

logger = logging.getLogger(__name__)

SCHEDULE = "0 8 * * *"
TIMEOUT_SECONDS = 30


def read_from_runware() -> Decimal:
    settings = Settings()
    with httpx.Client(base_url=settings.runware_base_url, timeout=TIMEOUT_SECONDS) as client:
        return read_runware_balance(client, api_key=settings.runware_api_key.get_secret_value())


def check_llm_balance_now(
    sessions: sessionmaker[Session],
    *,
    now: datetime,
    read: Callable[[], Decimal] = read_from_runware,
) -> None:
    """Store the balance with when it was read; the status line warns when it is low."""
    balance = read()
    with sessions.begin() as session:
        session.add(LlmBalance(checked_at=now, balance_usd=balance))
    if balance < Settings().llm_min_balance_usd:
        logger.warning("check_llm_balance: the Runware balance is low: $%.2f", balance)
    else:
        logger.info("check_llm_balance: $%.2f", balance)


@app.task(name="check_llm_balance", retry=LlmJobRetry(max_attempts=3, wait=1800))
def check_llm_balance() -> None:
    logger.info("check_llm_balance: start")
    check_llm_balance_now(default_sessions(), now=datetime.now(AMSTERDAM))


def run_check_llm_balance() -> None:
    """Run `check_llm_balance` here and now."""
    check_llm_balance()


schedule(check_llm_balance, cron=SCHEDULE, periodic_id="daily", queueing_lock="check_llm_balance")
