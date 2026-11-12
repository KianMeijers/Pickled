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

# The most the forms take, so a slip of the hand is refused rather than planned around.
MOST_PEOPLE = 20
MOST_BUDGET_EUROS = 10_000
MOST_PROTEIN_G = 1_000


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
        check_people(people)
        budget, vegetarian, protein = form_goals(budget_euros, vegetarian_days, protein_g)
        with services.sessions.begin() as session:
            session.execute(ONE_AT_A_TIME)
            if household(session) is not None:
                return RedirectResponse("/", status_code=303)
            set_household(session, people=people)
            if budget:
                kind = FoodGoalKind.BUDGET_CENTS_PER_WEEK
                set_food_goal(session, kind, max=budget, now=now)
            if vegetarian:
                kind = FoodGoalKind.VEGETARIAN_DAYS_PER_WEEK
                set_food_goal(session, kind, min=vegetarian, now=now)
            if protein:
                set_food_goal(session, FoodGoalKind.PROTEIN_G_PER_DAY, min=protein, now=now)
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


def form_number(field: str, *, most: int, whole: bool = True) -> Decimal | None:
    """A form's number from 0 to `most`, in Dutch or English notation; None if left blank.
    Anything else raises `InvalidOperation`."""
    field = field.strip().replace(",", ".")
    if not field:
        return None
    number = Decimal(field)
    if not number.is_finite() or not 0 <= number <= most:
        raise InvalidOperation(f"{field} is not from 0 to {most}")
    if whole and number != number.to_integral_value():
        raise InvalidOperation(f"{field} is not a whole number")
    return number


def form_goals(
    budget_euros: str, vegetarian_days: str, protein_g: str
) -> tuple[int | None, int | None, int | None]:
    """The forms' Food Goals: the budget in cents, vegetarian days and grams of protein.
    None for one left blank or set to 0."""
    budget = form_number(budget_euros, most=MOST_BUDGET_EUROS, whole=False)
    vegetarian = form_number(vegetarian_days, most=7)
    protein = form_number(protein_g, most=MOST_PROTEIN_G)
    return (
        int((budget * 100).to_integral_value()) if budget else None,
        int(vegetarian) if vegetarian else None,
        int(protein) if protein else None,
    )


def check_people(people: int) -> int:
    if not 1 <= people <= MOST_PEOPLE:
        raise InvalidOperation(f"{people} people is not from 1 to {MOST_PEOPLE}")
    return people
