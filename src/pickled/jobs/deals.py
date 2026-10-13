"""`fetch_deals(source)` fetches one store's Deals and stores them; `tag_deals(source)` then
links them to Ingredients with the match model (spec §6)."""

import logging
from collections.abc import Callable
from datetime import datetime

import httpx
from langchain_core.language_models import BaseChatModel
from procrastinate import RetryStrategy
from procrastinate.exceptions import AlreadyEnqueued
from sqlalchemy.orm import Session, sessionmaker

from pickled.db import default_sessions
from pickled.deals import DealSource, save_fetch, source_for, tag_deals
from pickled.jobs.app import app, schedule
from pickled.llm import Role, llm_context, make_chat_model
from pickled.stores import (
    AMSTERDAM,
    REQUEST_BUDGET,
    RequestBudgetExceeded,
    Store,
    make_client,
    requests_this_week,
    week_start,
)

logger = logging.getLogger(__name__)

# AH's Bonus week starts on Monday and Jumbo's on Wednesday; both are refreshed on Thursday,
# before the Saturday Shopping Day.
SCHEDULES = [
    (Store.AH, "0 6 * * 1", "monday"),
    (Store.JUMBO, "0 6 * * 3", "wednesday"),
    (Store.AH, "0 17 * * 4", "thursday"),
    (Store.JUMBO, "0 17 * * 4", "thursday"),
]


class FetchRetry(RetryStrategy):
    """Retry a failed fetch with backoff, but not once the store's request budget is spent."""

    def get_retry_decision(self, *, exception, job):
        if isinstance(exception, RequestBudgetExceeded):
            return None
        return super().get_retry_decision(exception=exception, job=job)


def fetch_deals_now(
    store: Store,
    sessions: sessionmaker[Session],
    *,
    now: datetime,
    source_for: Callable[[Store, httpx.Client], DealSource] = source_for,
) -> None:
    """Fetch the Deals `store` lists today and store them, or raise without storing any.

    A run is not begun if the week's request budget can't cover it, so a failing run's retries
    don't spend the budget a whole fetch at a time.
    """
    with make_client(store, sessions) as client:
        source = source_for(store, client)
        with sessions() as session:
            used = requests_this_week(session, store, now=now)
        if used + source.requests_per_fetch > REQUEST_BUDGET:
            raise RequestBudgetExceeded(store, week_start(now))
        result = source.fetch(now.astimezone(AMSTERDAM).date())
    with sessions.begin() as session:
        deal_fetch = save_fetch(session, result, now=now)
        logger.info(
            "fetch_deals %s: %d Deals, %d skipped, %d withdrawn",
            store,
            deal_fetch.parsed_count,
            deal_fetch.skipped_count,
            deal_fetch.withdrawn_count,
        )


@app.task(name="fetch_deals", retry=FetchRetry(max_attempts=3, wait=600, linear_wait=1200))
def fetch_deals(source: str, timestamp: int | None = None) -> None:
    logger.info("fetch_deals %s: start", source)
    fetch_deals_now(Store(source), default_sessions(), now=datetime.now(AMSTERDAM))
    try:
        tag_deals_job.configure(queueing_lock=f"tag_deals:{source}").defer(source=source)
    except AlreadyEnqueued:
        logger.info("tag_deals %s: already queued", source)


def tag_deals_now(
    store: Store,
    sessions: sessionmaker[Session],
    *,
    now: datetime,
    model: BaseChatModel | None = None,
) -> None:
    """Link `store`'s untagged current Deals to Ingredients, or mark them non-food."""
    with llm_context(job="tag_deals"):
        tag_deals(
            sessions,
            store,
            model or make_chat_model(Role.TAG_DEALS, sessions=sessions),
            on=now.astimezone(AMSTERDAM).date(),
            now=now,
        )


@app.task(name="tag_deals", retry=RetryStrategy(max_attempts=2, wait=600))
def tag_deals_job(source: str) -> None:
    logger.info("tag_deals %s: start", source)
    tag_deals_now(Store(source), default_sessions(), now=datetime.now(AMSTERDAM))


def run_fetch_deals(source: str | None) -> None:
    """Run `fetch_deals` here and now for `source`, or for every store."""
    _run_for_stores(fetch_deals, source)


def run_tag_deals(source: str | None) -> None:
    """Run `tag_deals` here and now for `source`, or for every store."""
    _run_for_stores(tag_deals_job, source)


def _run_for_stores(job: Callable[..., None], source: str | None) -> None:
    """Run `job` for `source`, or for every store.

    One store failing doesn't stop the others; the first failure is raised once all have run.
    """
    errors = []
    for store in [Store(source)] if source else list(Store):
        try:
            job(source=store.value)
        except Exception as error:
            logger.exception("%s %s: failed", job.name, store)
            errors.append(error)
    if errors:
        raise errors[0]


for store, cron, day in SCHEDULES:
    schedule(
        fetch_deals,
        cron=cron,
        periodic_id=f"{store}-{day}",
        task_kwargs={"source": store.value},
        queueing_lock=f"fetch_deals:{store}",
    )
