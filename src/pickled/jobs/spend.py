"""Skipping the background LLM jobs once the monthly spend cap is reached (spec §9)."""

import logging
from datetime import datetime

from sqlalchemy.orm import Session, sessionmaker

from pickled.llm import spend_cap

logger = logging.getLogger(__name__)


def at_the_cap(job: str, sessions: sessionmaker[Session], *, now: datetime) -> bool:
    """Whether this month's spend has reached the cap, so `job` is skipped. It isn't retried:
    `pickled jobs run` runs it by hand regardless."""
    with sessions() as session:
        cap = spend_cap(session, now=now)
    if cap.reached:
        logger.warning(
            "%s: skipped, this month's LLM spend $%.2f has reached the $%.2f cap",
            job,
            cap.spent,
            cap.cap,
        )
    return cap.reached
