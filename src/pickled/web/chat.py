"""Chat over SSE: a posted message becomes a turn, which the browser then streams.

A turn is posted first and streamed after, because the browser's EventSource can only GET. The
posted turn waits in memory until its stream starts, so a reconnecting EventSource can't run
it twice. Being in memory, it needs the app to run as one process, as the Dockerfile runs it.
"""

import html
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import date
from uuid import uuid4

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage

from pickled.agent import CHAT_CALL_LIMIT, PlanContext, make_agent, thread, unanswered_calls
from pickled.llm import llm_context
from pickled.planning import meal_plan_for, plan_lock, plan_summary
from pickled.web.app import templates
from pickled.web.drafting import drafting
from pickled.web.services import Services, services_of
from pickled.web.text import day_label

logger = logging.getLogger(__name__)

router = APIRouter()

# What the Household sees while each tool runs.
STATUS = {
    "get_plan": "Plan bekijken…",
    "search_deals": "Aanbiedingen zoeken…",
    "search_recipes": "Recepten zoeken…",
    "get_recipe": "Recept bekijken…",
    "set_store": "Winkel kiezen…",
    "set_meal": "Maaltijd inplannen…",
    "set_leftovers": "Restjes inplannen…",
    "clear_meal": "Dag leegmaken…",
    "finish_draft": "Plan afronden…",
    "save_recipe": "Recept opslaan…",
    "set_product": "Product kiezen…",
    "add_shopping_item": "Boodschap toevoegen…",
    "add_taste_note": "Smaakprofiel bijwerken…",
    "update_taste_note": "Smaakprofiel bijwerken…",
    "archive_taste_note": "Smaakprofiel bijwerken…",
    "set_food_goal": "Doelen bijwerken…",
    "clear_food_goal": "Doelen bijwerken…",
}
DRAFTING = "Pickled is aan het plannen… Even geduld."
FAILED = "Er ging iets mis. Probeer het nog eens."
# How long a posted turn waits for its stream; one whose stream never came is then dropped.
TURN_EXPIRES = 300
# Tools that change nothing the plan panel shows.
READ_ONLY = {"get_plan", "search_deals", "search_recipes", "get_recipe", "save_recipe"}


@dataclass(frozen=True)
class Turn:
    week_start: date
    message: str
    posted: float = field(default_factory=time.monotonic)


def turns_of(request: Request) -> dict[str, Turn]:
    return request.app.state.turns


@router.post("/plans/{week_start}/chat", response_class=HTMLResponse)
async def post_message(request: Request, week_start: date, message: str = Form()):
    message = message.strip()
    if not message:
        raise HTTPException(422, "Typ eerst een bericht.")
    return await start_turn(request, week_start, message)


@router.post("/plans/{week_start}/days/{day}/replace", response_class=HTMLResponse)
async def replace_day(request: Request, week_start: date, day: date):
    """The "Vervang" button: the agent chooses another Meal."""
    message = f"Kun je {day_label(day)} door iets anders vervangen?"
    return await start_turn(request, week_start, message)


@router.post("/plans/{week_start}/days/{day}/leftovers", response_class=HTMLResponse)
async def leftovers_day(request: Request, week_start: date, day: date):
    """The "Restjes" button: the agent chooses which earlier Meal to eat again."""
    message = f"Kun je op {day_label(day)} restjes van een eerdere maaltijd eten?"
    return await start_turn(request, week_start, message)


async def start_turn(request: Request, week_start: date, message: str) -> HTMLResponse:
    """Keep `message` as a turn for the stream to run, and show it with the reply to come."""
    services = services_of(request)
    with services.sessions() as session:
        meal_plan = meal_plan_for(session, week_start)
        if meal_plan is None:
            raise HTTPException(404, "Er is geen plan voor deze week.")
        meal_plan_id = meal_plan.id
    if await drafting(services, week_start, meal_plan_id):
        raise HTTPException(409, DRAFTING)
    turns = turns_of(request)
    for expired in [key for key, turn in turns.items() if _expired(turn)]:
        del turns[expired]
    turn_id = uuid4().hex
    turns[turn_id] = Turn(week_start, message)
    return templates.TemplateResponse(
        request,
        "_turn.html",
        {"message": message, "stream_url": f"/plans/{week_start}/chat/{turn_id}"},
    )


@router.get("/plans/{week_start}/chat/{turn_id}", response_class=EventSourceResponse)
async def stream_turn(
    request: Request, week_start: date, turn_id: str
) -> AsyncIterator[ServerSentEvent]:
    turn = turns_of(request).pop(turn_id, None)
    # A reconnecting EventSource finds its turn gone, and is only told it is done.
    if turn is not None and turn.week_start == week_start and not _expired(turn):
        try:
            async for event in run_turn(services_of(request), turn):
                yield event
        except Exception:
            logger.exception("Chat turn on the plan of %s failed", week_start)
            yield ServerSentEvent(event="status", raw_data="")
            yield ServerSentEvent(event="error", raw_data=FAILED)
    yield ServerSentEvent(event="done", raw_data="")


async def run_turn(services: Services, turn: Turn) -> AsyncIterator[ServerSentEvent]:
    """Run the agent on the turn's message: its reply tokens, a status line per tool step, and
    the plan panel again after each step that changed it."""
    with services.sessions() as session:
        meal_plan = meal_plan_for(session, turn.week_start)
        meal_plan_id = meal_plan.id
    agent = chat_agent(services)
    context = PlanContext(
        meal_plan_id, services.sessions, services.prices, services.picker, services.clock
    )
    config = thread(meal_plan_id)
    async with plan_lock(services.sessions, meal_plan_id):
        state = await agent.aget_state(config)
        stopped = unanswered_calls(state.values.get("messages", []))
        request = {"messages": [*stopped, HumanMessage(content=turn.message)]}
        with llm_context(meal_plan=meal_plan_id):
            async for mode, chunk in agent.astream(
                request,
                config,
                context=context,
                stream_mode=["messages", "updates"],
            ):
                if mode == "messages":
                    message, metadata = chunk
                    if _reply_token(message, metadata):
                        yield ServerSentEvent(event="token", raw_data=html.escape(message.text))
                    continue
                for update in chunk.values():
                    for message in (update or {}).get("messages", []):
                        if isinstance(message, AIMessage):
                            for call in message.tool_calls:
                                status = STATUS.get(call["name"], "Bezig…")
                                yield ServerSentEvent(event="status", raw_data=status)
                    tools = [
                        message
                        for message in (update or {}).get("messages", [])
                        if isinstance(message, ToolMessage)
                    ]
                    if any(tool.name not in READ_ONLY for tool in tools):
                        yield ServerSentEvent(event="plan", raw_data=plan_panel(services, turn))
    yield ServerSentEvent(event="status", raw_data="")


def chat_agent(services: Services):
    return make_agent(
        services.chat_model(), call_limit=CHAT_CALL_LIMIT, checkpointer=services.checkpointer
    )


def plan_panel(services: Services, turn: Turn) -> str:
    """The plan panel and the Shopping List as out-of-band swaps, replacing those on the page.
    The turn holds the plan's lock, so the Shopping List brought up to date is kept."""
    with services.sessions.begin() as session:
        meal_plan = meal_plan_for(session, turn.week_start)
        summary = plan_summary(session, meal_plan, prices=services.shown_prices(session, meal_plan))
    shown = {"summary": summary, "today": services.today(), "oob": True}
    return "".join(
        templates.get_template(name).render(shown) for name in ("_plan.html", "_shopping.html")
    )


def _expired(turn: Turn) -> bool:
    return time.monotonic() - turn.posted > TURN_EXPIRES


def _reply_token(message, metadata: dict) -> bool:
    return (
        isinstance(message, AIMessageChunk | AIMessage)
        and metadata.get("langgraph_node") == "model"
        and not message.tool_calls
        and bool(message.text)
    )
