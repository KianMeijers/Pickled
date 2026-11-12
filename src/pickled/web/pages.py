"""The pages: a Meal Plan with its days, Conversation and Shopping List."""

from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from pickled.agent import conversation
from pickled.llm import spend_cap
from pickled.planning import (
    meal_plan_for,
    plan_lock_if_free,
    plan_summary,
    shopping_day_of,
    upcoming_shopping_day,
)
from pickled.taste import household
from pickled.web.app import templates
from pickled.web.drafting import drafting
from pickled.web.services import services_of
from pickled.web.status import status_line

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """The plan whose week contains today. Without one: the next week's plan, its draft in
    progress, or a button to draft it. Before anything, onboarding."""
    services = services_of(request)
    this_week = shopping_day_of(services.today())
    upcoming = upcoming_shopping_day(services.today())
    with services.sessions() as session:
        if household(session) is None:
            return RedirectResponse("/welkom", status_code=303)
        if meal_plan_for(session, this_week) is not None:
            return await plan_page(request, this_week)
        upcoming_plan = meal_plan_for(session, upcoming)
        upcoming_id = upcoming_plan.id if upcoming_plan else None
    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "upcoming": upcoming,
            "has_plan": upcoming_id is not None,
            "drafting": await drafting(services, upcoming, upcoming_id),
        },
    )


@router.get("/plans/{week_start}", response_class=HTMLResponse)
async def plan_page(request: Request, week_start: date):
    services = services_of(request)
    next_week = shopping_day_of(services.today()) + timedelta(days=7)
    with services.sessions() as session:
        meal_plan = meal_plan_for(session, week_start)
        if meal_plan is None:
            raise HTTPException(404, "Er is geen plan voor deze week.")
        meal_plan_id = meal_plan.id
        # The summary brings the stored Shopping List up to date, which is kept unless a job or
        # a chat turn is changing the plan. Then the list's new lines aren't stored, so none
        # can be ticked until the page shows it again.
        with plan_lock_if_free(services.sessions, meal_plan_id) as free:
            prices = services.shown_prices(session, meal_plan)
            summary = plan_summary(session, meal_plan, prices=prices)
            if free:
                session.commit()
        next_week_ready = week_start != next_week and meal_plan_for(session, next_week) is not None
        capped = spend_cap(session, now=services.clock()).reached
    messages = await conversation(services.checkpointer, meal_plan_id)
    return templates.TemplateResponse(
        request,
        "plan.html",
        {
            "summary": summary,
            "messages": messages,
            "next_week": next_week if next_week_ready else None,
            "drafting": await drafting(services, week_start, meal_plan_id),
            "today": services.today(),
            "unsaved": not free,
            "capped": capped,
        },
    )


@router.get("/plans/{week_start}/drafting")
async def still_drafting(request: Request, week_start: date):
    """Polled while a draft job works on the week: the page reloads once it is done."""
    services = services_of(request)
    with services.sessions() as session:
        meal_plan = meal_plan_for(session, week_start)
        meal_plan_id = meal_plan.id if meal_plan else None
    if await drafting(services, week_start, meal_plan_id):
        return Response()
    # 286 tells HTMX to stop polling.
    return Response(status_code=286, headers={"HX-Refresh": "true"})


@router.get("/status", response_class=HTMLResponse)
async def status(request: Request):
    """The status line, loaded by every page."""
    lines = await status_line(services_of(request))
    return templates.TemplateResponse(request, "_status.html", {"lines": lines})
