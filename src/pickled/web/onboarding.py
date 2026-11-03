"""First run: the Household's size, optional Food Goals and a few Taste notes, then planning."""

import logging
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from procrastinate.exceptions import AlreadyEnqueued
from sqlalchemy import text

from pickled.jobs.draft import QUEUEING_LOCK
from pickled.jobs.start import start_planning
from pickled.planning import upcoming_shopping_day
from pickled.taste import (
    Author,
    FoodGoalKind,
    TasteRefused,
    add_taste_note,
    household,
    set_food_goal,
    set_household,
)
from pickled.web.app import templates
from pickled.web.services import services_of

logger = logging.getLogger(__name__)

router = APIRouter()

# Onboardings one at a time, so a double submit can't onboard twice.
ONE_AT_A_TIME = text("LOCK TABLE household IN EXCLUSIVE MODE")


@router.get("/welkom", response_class=HTMLResponse)
async def welcome(request: Request):
    with services_of(request).sessions() as session:
        if household(session) is not None:
            return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "welcome.html")


@router.post("/welkom")
async def onboard(
    request: Request,
    people: int = Form(),
    budget_euros: str = Form(""),
    vegetarian_days: str = Form(""),
    protein_g: str = Form(""),
    taste_notes: str = Form(""),
):
    """Save the Household, then fetch both stores' Deals and draft the next week. A Food Goal
    left blank isn't set. Once onboarded, a form sent again changes nothing."""
    services = services_of(request)
    now = services.clock()
    try:
        budget, vegetarian, protein = (
            _number(field) for field in (budget_euros, vegetarian_days, protein_g)
        )
        with services.sessions.begin() as session:
            session.execute(ONE_AT_A_TIME)
            if household(session) is not None:
                return RedirectResponse("/", status_code=303)
            set_household(session, people=people)
            if budget:
                kind = FoodGoalKind.BUDGET_CENTS_PER_WEEK
                set_food_goal(session, kind, max=int(budget * 100), now=now)
            if vegetarian:
                kind = FoodGoalKind.VEGETARIAN_DAYS_PER_WEEK
                set_food_goal(session, kind, min=int(vegetarian), now=now)
            if protein:
                set_food_goal(session, FoodGoalKind.PROTEIN_G_PER_DAY, min=int(protein), now=now)
            for note in taste_notes.splitlines():
                if note.strip():
                    add_taste_note(session, note.strip(), Author.USER, now=now)
    except (TasteRefused, InvalidOperation) as refused:
        raise HTTPException(
            422, "Dat klopt niet helemaal: kijk de antwoorden nog eens na."
        ) from refused
    week_start = upcoming_shopping_day(services.today())
    try:
        await start_planning.configure(queueing_lock=QUEUEING_LOCK).defer_async(
            week=week_start.isoformat()
        )
    except AlreadyEnqueued:
        # Home shows the queued draft; it waits for the Deals as a scheduled draft does.
        logger.info("Onboarded with a draft already queued; not starting planning")
    return RedirectResponse("/", status_code=303)


def _number(field: str) -> Decimal | None:
    """A form's number, in Dutch or English notation; None if left blank."""
    field = field.strip().replace(",", ".")
    return Decimal(field) if field else None
