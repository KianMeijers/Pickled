"""The status line: what may be wrong with the jobs and data planning depends on, in Dutch.

It shows warnings only; when all is well it is empty (spec §6, §9).
"""

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pickled.config import Settings
from pickled.deals import DealFetch, deals_valid_on
from pickled.ingredients import checkjebon_stale
from pickled.jobs import app
from pickled.llm import latest_balance, spend_cap
from pickled.planning import (
    PlanStatus,
    meal_plan_for,
    shopping_day_of,
    upcoming_shopping_day,
)
from pickled.seasonal import seasonal_for
from pickled.stores import AMSTERDAM, Store
from pickled.web.drafting import drafting
from pickled.web.services import Services
from pickled.web.text import STORES, day_label, dollars

# AH is fetched on Monday and Thursday, Jumbo on Wednesday and Thursday: a week without a fetch
# means the schedule has stopped.
FETCH_LATE = timedelta(days=7)
JOBS = {
    "fetch_deals": "Aanbiedingen ophalen",
    "tag_deals": "Aanbiedingen koppelen",
    "refresh_checkjebon": "Jumbo-prijzen bijwerken",
    "draft_meal_plan": "Plan maken",
    "start_planning": "Het eerste plan maken",
    "reflect_on_week": "Terugblikken op de week",
    "check_llm_balance": "Het Runware-tegoed controleren",
}


async def status_line(services: Services) -> list[str]:
    """The warnings to show on every page, most pressing first."""
    with services.sessions() as session:
        lines = [
            *_balance(session),
            *_spend(session, services),
            *_stores(session, services),
            *_checkjebon(session),
            *_seasonal(session, services),
        ]
        partial = _unfinished(session, services)
    for meal_plan_id, week_start in partial:
        if not await drafting(services, week_start, meal_plan_id):
            lines.append(
                f"Het plan voor de week van {day_label(week_start)} is maar half af: maak het af "
                "in de chat, of maak het opnieuw."
            )
    return [*lines, *await _failed_jobs()]


def _unfinished(session: Session, services: Services) -> list[tuple[int, date]]:
    """This week's and next week's plans that are drafts no run has finished."""
    today = services.today()
    weeks = sorted({shopping_day_of(today), upcoming_shopping_day(today)})
    plans = [meal_plan_for(session, week) for week in weeks]
    return [
        (meal_plan.id, meal_plan.week_start)
        for meal_plan in plans
        if meal_plan is not None
        and meal_plan.status == PlanStatus.DRAFT
        and meal_plan.drafted_at is None
    ]


async def _failed_jobs() -> list[str]:
    """Each job, per store, whose last finished run failed. A later success clears it."""
    last: dict[tuple[str, str | None], tuple[int, str]] = {}
    for status in ("succeeded", "failed"):
        for job in await app.job_manager.list_jobs_async(status=status):
            key = (job.task_name, job.task_kwargs.get("source"))
            if job.id is not None and (key not in last or job.id > last[key][0]):
                last[key] = (job.id, status)
    lines = []
    for (task, source), (_, status) in sorted(last.items(), key=lambda item: item[1][0]):
        if status == "failed":
            store = f" ({STORES[Store(source)]})" if source else ""
            lines.append(f"{JOBS.get(task, task)}{store} is mislukt; kijk in de logs.")
    return lines


def _stores(session: Session, services: Services) -> list[str]:
    """A store without Deals valid today, or one whose last fetch is over a week old."""
    found = {deal.store for deal in deals_valid_on(session, services.today())}
    last_fetched = dict(
        session.execute(
            select(DealFetch.store, func.max(DealFetch.fetched_at)).group_by(DealFetch.store)
        ).all()
    )
    lines = []
    for store in Store:
        last = last_fetched.get(store)
        if store not in found:
            lines.append(f"Er zijn geen aanbiedingen van {STORES[store]}.")
        elif last is None or services.clock() - last > FETCH_LATE:
            when = f" op {day_label(last.astimezone(AMSTERDAM).date())}" if last else ""
            lines.append(
                f"De aanbiedingen van {STORES[store]} zijn voor het laatst opgehaald{when}."
            )
    return lines


def _checkjebon(session: Session) -> list[str]:
    if checkjebon_stale(session):
        return [
            "De Jumbo-prijzen van Checkjebon zijn al dagen niet bijgewerkt; ze kunnen verouderd "
            "zijn."
        ]
    return []


def _seasonal(session: Session, services: Services) -> list[str]:
    if seasonal_for(session, services.today().month):
        return []
    return ["Er is geen seizoensgroente voor deze maand: draai `pickled seasonal import`."]


def _spend(session: Session, services: Services) -> list[str]:
    cap = spend_cap(session, now=services.clock())
    if cap.reached:
        return [
            f"Het maandbudget van {dollars(cap.cap)} voor LLM-kosten is op: plannen, "
            "aanbiedingen koppelen en terugblikken worden overgeslagen tot volgende maand. "
            "Chatten kan nog."
        ]
    if cap.warning:
        return [f"De LLM-kosten deze maand zijn {dollars(cap.spent)} van de {dollars(cap.cap)}."]
    return []


def _balance(session: Session) -> list[str]:
    balance = latest_balance(session)
    if balance is None:
        return []
    if balance.balance_usd <= 0:
        return [
            "Het Runware-tegoed is op: vul het aan, anders kan Pickled niet plannen of chatten."
        ]
    if balance.balance_usd < Settings().llm_min_balance_usd:
        return [f"Het Runware-tegoed is laag: {dollars(balance.balance_usd)}."]
    return []
