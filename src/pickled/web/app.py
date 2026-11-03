"""The FastAPI app: the Household's pages, chat over SSE, and the plan's buttons (spec §8)."""

import html
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from starlette.exceptions import HTTPException as StarletteHTTPException

from pickled import jobs
from pickled.agent import is_note
from pickled.config import Settings
from pickled.db import default_sessions
from pickled.ingredients import open_product_picker
from pickled.llm import Role, make_chat_model
from pickled.migrate import LANGGRAPH_SCHEMA, schema_conninfo
from pickled.planning import picked_prices
from pickled.web import text
from pickled.web.services import Services

HERE = Path(__file__).parent

templates = Jinja2Templates(directory=HERE / "templates")
templates.env.filters.update(
    day_label=text.day_label,
    weekday=text.weekday,
    euros=text.euros,
    amount=text.amount,
    goal=text.goal,
    warning=text.warning,
)
templates.env.globals.update(stores=text.STORES, aisles=text.AISLES, is_note=is_note)


def create_app(services: Services | None = None, *, lifespan=None) -> FastAPI:
    """The app on `services`, or on those its `lifespan` sets up."""
    from pickled.web import chat, onboarding, pages, plans

    app = FastAPI(title="Pickled", lifespan=lifespan)
    if services is not None:
        app.state.services = services
    app.state.turns = {}
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    app.include_router(pages.router)
    app.include_router(chat.router)
    app.include_router(plans.router)
    app.include_router(onboarding.router)
    app.add_exception_handler(StarletteHTTPException, refused)
    return app


def production_app() -> FastAPI:
    """The app on the app's database, chat model, Product picks, checkpointer and job queue.

    Run it with `uvicorn pickled.web.app:production_app --factory`.
    """
    logging.basicConfig(level=logging.INFO)
    return create_app(lifespan=_with_the_app)


@asynccontextmanager
async def _with_the_app(app: FastAPI) -> AsyncIterator[None]:
    sessions = default_sessions()
    conninfo = schema_conninfo(Settings().database_url, LANGGRAPH_SCHEMA)
    with open_product_picker(sessions) as picker:
        async with (
            AsyncPostgresSaver.from_conn_string(conninfo) as checkpointer,
            jobs.app.open_async(),
        ):
            app.state.services = Services(
                sessions=sessions,
                checkpointer=checkpointer,
                chat_model=lambda: make_chat_model(Role.CHAT, sessions=sessions),
                prices=lambda session, meal_plan: picked_prices(session, meal_plan, picker),
                shown_prices=lambda session, meal_plan: picked_prices(session, meal_plan, None),
                picker=picker,
            )
            yield


async def refused(request: Request, error: StarletteHTTPException) -> HTMLResponse:
    """Why a request was refused, as a line of Dutch HTMX can show."""
    return HTMLResponse(
        f'<p class="error">{html.escape(str(error.detail))}</p>', status_code=error.status_code
    )
