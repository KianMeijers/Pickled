"""What the Household changes on a plan without the agent: a day left empty, accepting,
redrafting, drafting the next week, and the Shopping List."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date

from fastapi import APIRouter, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from procrastinate.exceptions import AlreadyEnqueued
from sqlalchemy.orm import Session

from pickled.agent import add_note
from pickled.jobs.draft import QUEUEING_LOCK, draft_meal_plan
from pickled.planning import (
    MealPlan,
    PlanRefused,
    PlanStatus,
    ShoppingListItem,
    accept_meal_plan,
    add_shopping_item,
    clear_meal,
    meal_plan_for,
    plan_lock,
    tick_shopping_item,
    upcoming_shopping_day,
)
from pickled.web import text
from pickled.web.app import templates
from pickled.web.chat import DRAFTING, chat_agent
from pickled.web.drafting import drafting
from pickled.web.services import Services, services_of

router = APIRouter()


@router.post("/plans/{week_start}/days/{day}/clear", response_class=HTMLResponse)
async def clear_day(request: Request, week_start: date, day: date):
    """Leave `day` empty, straight away, and note it in the Conversation for the agent."""
    services = services_of(request)
    if day < services.today():
        raise HTTPException(409, "Deze dag is al voorbij.")
    async with changing(services, week_start) as (session, meal_plan):
        try:
            summary = clear_meal(
                session,
                meal_plan,
                day,
                today=services.today(),
                prices=services.shown_prices(session, meal_plan),
            )
        except PlanRefused as refused:
            raise HTTPException(409, "Deze dag hoort niet bij dit plan.") from refused
        meal_plan_id = meal_plan.id
    note = f"{text.day_label(day).capitalize()} is leeg gelaten."
    await add_note(chat_agent(services), meal_plan_id, note)
    return templates.TemplateResponse(
        request, "_cleared.html", {"summary": summary, "note": note, "today": services.today()}
    )


@router.post("/plans/{week_start}/accept", response_class=HTMLResponse)
async def accept(request: Request, week_start: date):
    """Accept the plan once every day has a Meal or is left empty."""
    services = services_of(request)
    async with changing(services, week_start) as (session, meal_plan):
        if meal_plan.status == PlanStatus.ACCEPTED:
            raise HTTPException(409, "Dit plan is al geaccepteerd.")
        try:
            summary = accept_meal_plan(
                session,
                meal_plan,
                now=services.clock(),
                prices=services.shown_prices(session, meal_plan),
            )
        except PlanRefused as refused:
            raise HTTPException(
                409, "Vul eerst elke dag, of laat een dag bewust leeg, voor je accepteert."
            ) from refused
    return templates.TemplateResponse(
        request, "_plan.html", {"summary": summary, "today": services.today()}
    )


@router.post("/plans/draft")
async def draft_now(request: Request):
    """Queue the draft of the next Shopping Day's plan, while that week has none."""
    services = services_of(request)
    week_start = upcoming_shopping_day(services.today())
    with services.sessions() as session:
        if meal_plan_for(session, week_start) is not None:
            raise HTTPException(409, "Er is al een plan voor die week.")
    try:
        await draft_meal_plan.configure(queueing_lock=QUEUEING_LOCK).defer_async(
            week=week_start.isoformat()
        )
    except AlreadyEnqueued as queued:
        raise HTTPException(409, "Pickled is al aan het plannen.") from queued
    return Response(headers={"HX-Refresh": "true"})


@router.post("/plans/{week_start}/redraft")
async def redraft(request: Request, week_start: date, hint: str = Form("")):
    """Queue a fresh draft that replaces every Meal, while the plan is still a draft."""
    services = services_of(request)
    with services.sessions() as session:
        meal_plan = meal_plan_for(session, week_start)
        if meal_plan is None:
            raise HTTPException(404, "Er is geen plan voor deze week.")
        if meal_plan.status == PlanStatus.ACCEPTED:
            raise HTTPException(409, "Een geaccepteerd plan maak je niet opnieuw.")
    try:
        await draft_meal_plan.configure(queueing_lock=QUEUEING_LOCK).defer_async(
            week=week_start.isoformat(), redraft=True, hint=hint.strip() or None
        )
    except AlreadyEnqueued as queued:
        raise HTTPException(409, "Pickled is al aan het plannen.") from queued
    # The whole page shows the plan as being drafted.
    return Response(headers={"HX-Refresh": "true"})


@router.post("/plans/{week_start}/shopping/{item_id}")
async def tick(request: Request, week_start: date, item_id: int, checked: str | None = Form(None)):
    """Tick a Shopping List item off, or untick it."""
    services = services_of(request)
    with services.sessions.begin() as session:
        meal_plan = meal_plan_for(session, week_start)
        item = session.get(ShoppingListItem, item_id)
        if meal_plan is None or item is None or item.meal_plan_id != meal_plan.id:
            raise HTTPException(404, "Dit staat niet op de boodschappenlijst.")
        tick_shopping_item(session, item_id, checked is not None)
    return Response()


@router.post("/plans/{week_start}/shopping", response_class=HTMLResponse)
async def add_item(request: Request, week_start: date, name: str = Form()):
    """Add an item of the Household's own to the Shopping List."""
    services = services_of(request)
    async with changing(services, week_start) as (session, meal_plan):
        try:
            summary = add_shopping_item(
                session, meal_plan, name, prices=services.shown_prices(session, meal_plan)
            )
        except PlanRefused as refused:
            raise HTTPException(422, "Geef het een naam.") from refused
    return templates.TemplateResponse(request, "_shopping.html", {"summary": summary})


@asynccontextmanager
async def changing(services: Services, week_start: date) -> AsyncIterator[tuple[Session, MealPlan]]:
    """A transaction on the week's Meal Plan, holding its lock, committed if the block ends.
    Refused while a draft job is at work on it."""
    with services.sessions() as session:
        meal_plan = meal_plan_for(session, week_start)
        if meal_plan is None:
            raise HTTPException(404, "Er is geen plan voor deze week.")
        meal_plan_id = meal_plan.id
    if await drafting(services, week_start, meal_plan_id):
        raise HTTPException(409, DRAFTING)
    async with plan_lock(services.sessions, meal_plan_id):
        with services.sessions.begin() as session:
            yield session, session.get_one(MealPlan, meal_plan_id)
