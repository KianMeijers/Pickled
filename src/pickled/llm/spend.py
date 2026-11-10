"""What the model calls cost this month, against the monthly spend cap (spec §9, ADR 0009).

Months are Europe/Amsterdam calendar months. Evals don't count toward the cap: their judge
calls, and every call made under an `llm_context` job named `eval…`.
"""

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.orm import Session

from pickled.config import Settings
from pickled.llm.models import LlmCall, Role

AMSTERDAM = ZoneInfo("Europe/Amsterdam")
# The status line warns from this share of the cap on.
WARN_AT = Decimal("0.8")
EVAL_JOBS = "eval"


@dataclass(frozen=True)
class SpendCap:
    spent: Decimal
    cap: Decimal

    @property
    def warning(self) -> bool:
        return self.spent >= self.cap * WARN_AT

    @property
    def reached(self) -> bool:
        return self.spent >= self.cap


def month_start(now: datetime) -> datetime:
    """The start of `now`'s month in Amsterdam."""
    day = now.astimezone(AMSTERDAM).date().replace(day=1)
    return datetime.combine(day, time(), AMSTERDAM)


def last_month_start(now: datetime) -> datetime:
    """The start of the month before `now`'s, in Amsterdam."""
    return month_start(month_start(now) - timedelta(days=1))


def counted() -> ColumnElement[bool]:
    """The calls that count toward the cap: all but the evals'."""
    return and_(
        LlmCall.role != Role.EVAL_JUDGE,
        or_(LlmCall.job.is_(None), LlmCall.job.not_like(f"{EVAL_JOBS}%")),
    )


def spend_cap(session: Session, *, now: datetime) -> SpendCap:
    """This month's spend so far against `PICKLED_LLM_MONTHLY_CAP_USD`."""
    spent = session.scalar(
        select(func.coalesce(func.sum(LlmCall.cost_usd), 0)).where(
            counted(), LlmCall.called_at >= month_start(now)
        )
    )
    return SpendCap(spent=Decimal(spent), cap=Settings().llm_monthly_cap_usd)


def spend_by_role(session: Session, *, start: datetime, end: datetime) -> dict[Role, Decimal]:
    """What each role's calls from `start` until `end` cost, evals too; a call of unknown cost
    counts as nothing."""
    rows = session.execute(
        select(LlmCall.role, func.coalesce(func.sum(LlmCall.cost_usd), 0))
        .where(LlmCall.called_at >= start, LlmCall.called_at < end)
        .group_by(LlmCall.role)
    ).all()
    return {role: Decimal(cost) for role, cost in rows}


def spend_per_meal_plan(session: Session) -> dict[int, Decimal]:
    """What the calls made for each Meal Plan cost: its draft, chat and reflection."""
    rows = session.execute(
        select(LlmCall.meal_plan_id, func.coalesce(func.sum(LlmCall.cost_usd), 0))
        .where(LlmCall.meal_plan_id.is_not(None))
        .group_by(LlmCall.meal_plan_id)
    ).all()
    return {meal_plan_id: Decimal(cost) for meal_plan_id, cost in rows}


def recorded_spend(session: Session, *, start: datetime, end: datetime) -> Decimal:
    """What every call from `start` until `end` cost, evals too: what came off the balance."""
    return Decimal(
        session.scalar(
            select(func.coalesce(func.sum(LlmCall.cost_usd), 0)).where(
                LlmCall.called_at >= start, LlmCall.called_at < end
            )
        )
    )
