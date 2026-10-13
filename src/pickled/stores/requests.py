"""The per-store weekly request counter: about 60 requests per store per week (ADR 0005).

A week runs Monday to Sunday in Europe/Amsterdam time, the same week as AH's Bonus.
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Mapped, Session, mapped_column

from pickled.db import Base
from pickled.stores.store import STORE_TYPE, Store

REQUEST_BUDGET = 60
AMSTERDAM = ZoneInfo("Europe/Amsterdam")


class RequestBudgetExceeded(Exception):
    """A store has had its weekly budget of requests; the request was not sent."""

    def __init__(self, store: Store, week_start: date):
        super().__init__(f"{store} has used its {REQUEST_BUDGET} requests this week ({week_start})")
        self.store = store
        self.week_start = week_start


class StoreRequest(Base):
    __tablename__ = "store_request"

    store: Mapped[Store] = mapped_column(STORE_TYPE, primary_key=True)
    week_start: Mapped[date] = mapped_column(primary_key=True)
    count: Mapped[int]


def week_start(now: datetime) -> date:
    """The Monday of the week `now` falls in, in Amsterdam time."""
    today = now.astimezone(AMSTERDAM).date()
    return today - timedelta(days=today.weekday())


def spend_request(session: Session, store: Store, *, now: datetime | None = None) -> None:
    """Count one request to `store`, or raise `RequestBudgetExceeded` if the week's are spent.

    The increment and the budget check are one statement, so concurrent callers can't overshoot.
    """
    week = week_start(now or datetime.now(AMSTERDAM))
    statement = insert(StoreRequest).values(store=store, week_start=week, count=1)
    statement = statement.on_conflict_do_update(
        index_elements=[StoreRequest.store, StoreRequest.week_start],
        set_={"count": StoreRequest.count + 1},
        where=StoreRequest.count < REQUEST_BUDGET,
    ).returning(StoreRequest.count)
    if session.execute(statement).scalar() is None:
        raise RequestBudgetExceeded(store, week)


def requests_this_week(session: Session, store: Store, *, now: datetime | None = None) -> int:
    week = week_start(now or datetime.now(AMSTERDAM))
    count = session.execute(
        select(StoreRequest.count).where(
            StoreRequest.store == store, StoreRequest.week_start == week
        )
    ).scalar()
    return count or 0
