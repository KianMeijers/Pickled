"""The settings page: the Household size, Food Goals, Taste notes and LLM-kosten (spec §8, §9)."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from pickled.config import Settings
from pickled.llm import (
    Role,
    compare_balance,
    last_month_start,
    latest_balance,
    month_start,
    spend_by_role,
    spend_per_meal_plan,
)
from pickled.planning import MealPlan
from pickled.taste import (
    MAX_ACTIVE_NOTES,
    MAX_NOTE_LENGTH,
    Author,
    FoodGoal,
    FoodGoalKind,
    TasteRefused,
    active_food_goals,
    active_taste_notes,
    add_taste_note,
    archive_taste_note,
    clear_food_goal,
    household,
    set_food_goal,
    set_household,
    update_taste_note,
)
from pickled.web.app import templates
from pickled.web.onboarding import form_number
from pickled.web.services import Services, services_of

router = APIRouter()

# How many Meal Plan weeks the spend per week shows, newest first.
WEEKS_SHOWN = 12


@router.get("/instellingen", response_class=HTMLResponse)
async def settings_page(request: Request):
    services = services_of(request)
    with services.sessions() as session:
        context = {**_taste(session), **_costs(session, services)}
    return templates.TemplateResponse(request, "settings.html", context)


@router.post("/instellingen/huishouden")
async def change_household(
    request: Request,
    people: int = Form(),
    budget_euros: str = Form(""),
    vegetarian_days: str = Form(""),
    protein_g: str = Form(""),
):
    """Set the Household size and the Food Goals the form has; a goal left blank is cleared."""
    services = services_of(request)
    now = services.clock()
    try:
        budget, vegetarian, protein = (
            form_number(field) for field in (budget_euros, vegetarian_days, protein_g)
        )
        wanted = {
            FoodGoalKind.BUDGET_CENTS_PER_WEEK: (None, budget * 100 if budget else None),
            FoodGoalKind.VEGETARIAN_DAYS_PER_WEEK: (vegetarian or None, None),
            FoodGoalKind.PROTEIN_G_PER_DAY: (protein or None, None),
        }
        with services.sessions.begin() as session:
            found = household(session)
            set_household(session, people=people, name=found.name if found else None)
            goals = {goal.kind: goal for goal in active_food_goals(session)}
            for kind, (low, high) in wanted.items():
                _set_goal(session, kind, goals.get(kind), low, high, now=now)
    except (TasteRefused, InvalidOperation) as refused:
        raise HTTPException(
            422, "Dat klopt niet helemaal: kijk de antwoorden nog eens na."
        ) from refused
    return _refresh()


def _set_goal(session: Session, kind: FoodGoalKind, goal: FoodGoal | None, low, high, *, now):
    """Set, keep or clear one Food Goal: an unchanged goal keeps its history as it is."""
    if low is None and high is None:
        if goal is not None:
            clear_food_goal(session, kind, now=now)
    elif goal is None or (goal.min, goal.max) != (low, high):
        set_food_goal(session, kind, min=low, max=high, now=now)


@router.post("/instellingen/smaak")
async def add_note(request: Request, text: str = Form()):
    services = services_of(request)
    with _taste_change():
        with services.sessions.begin() as session:
            add_taste_note(session, _note_text(text), Author.USER, now=services.clock())
    return _refresh()


@router.post("/instellingen/smaak/{note_id}")
async def rewrite_note(request: Request, note_id: int, text: str = Form()):
    """Rewrite a note: whoever wrote it, it is the Household's now."""
    services = services_of(request)
    with _taste_change():
        with services.sessions.begin() as session:
            update_taste_note(session, note_id, _note_text(text), Author.USER, now=services.clock())
    return _refresh()


@router.post("/instellingen/smaak/{note_id}/weg")
async def archive_note(request: Request, note_id: int):
    services = services_of(request)
    with _taste_change():
        with services.sessions.begin() as session:
            archive_taste_note(session, note_id, Author.USER, now=services.clock())
    return _refresh()


def _note_text(text: str) -> str:
    text = text.strip()
    if len(text) > MAX_NOTE_LENGTH:
        raise HTTPException(422, f"Een smaaknotitie is hooguit {MAX_NOTE_LENGTH} tekens.")
    return text


@contextmanager
def _taste_change() -> Iterator[None]:
    try:
        yield
    except TasteRefused as refused:
        raise HTTPException(
            422,
            f"Dat kan niet: er zijn al {MAX_ACTIVE_NOTES} notities, of de notitie bestaat niet "
            "meer. Haal er een weg of voeg er twee samen.",
        ) from refused


def _refresh() -> Response:
    """Done: HTMX reloads the page to show the change."""
    return Response(status_code=204, headers={"HX-Refresh": "true"})


def _taste(session: Session) -> dict:
    found = household(session)
    goals = {goal.kind: goal for goal in active_food_goals(session)}
    budget = goals.get(FoodGoalKind.BUDGET_CENTS_PER_WEEK)
    vegetarian = goals.get(FoodGoalKind.VEGETARIAN_DAYS_PER_WEEK)
    protein = goals.get(FoodGoalKind.PROTEIN_G_PER_DAY)
    return {
        "people": found.people if found else 2,
        "budget_euros": _plain(budget.max / 100) if budget and budget.max else "",
        "vegetarian_days": _plain(vegetarian.min) if vegetarian and vegetarian.min else "",
        "protein_g": _plain(protein.min) if protein and protein.min else "",
        "notes": active_taste_notes(session),
    }


def _costs(session: Session, services: Services) -> dict:
    now = services.clock()
    this_month, last_month = month_start(now), last_month_start(now)
    next_month = month_start(this_month + timedelta(days=32))
    spent_now = spend_by_role(session, start=this_month, end=next_month)
    spent_before = spend_by_role(session, start=last_month, end=this_month)
    per_plan = spend_per_meal_plan(session)
    weeks = session.execute(
        select(MealPlan.id, MealPlan.week_start)
        .where(MealPlan.id.in_(per_plan))
        .order_by(MealPlan.week_start.desc())
        .limit(WEEKS_SHOWN)
    ).all()
    return {
        "roles": [
            (role, spent_now.get(role, Decimal(0)), spent_before.get(role, Decimal(0)))
            for role in Role
        ],
        "total_now": sum(spent_now.values(), Decimal(0)),
        "total_before": sum(spent_before.values(), Decimal(0)),
        "weeks": [(week_start, per_plan[meal_plan_id]) for meal_plan_id, week_start in weeks],
        "balance": latest_balance(session),
        "cap": Settings().llm_monthly_cap_usd,
        "compared": [
            compare_balance(session, start=this_month, end=next_month),
            compare_balance(session, start=last_month, end=this_month),
        ],
    }


def _plain(number: Decimal) -> str:
    """A form's value: "70", or "7.5" with a decimal point as an input expects."""
    return f"{Decimal(number).normalize():f}"
