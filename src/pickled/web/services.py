"""What the web app runs on, passed in so tests can swap the model, prices and clock."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime

from fastapi import Request
from langchain_core.language_models import BaseChatModel
from langgraph.types import Checkpointer
from sqlalchemy.orm import Session, sessionmaker

from pickled.ingredients import ProductPicker
from pickled.planning import MealPlan, Prices
from pickled.stores import AMSTERDAM


@dataclass(frozen=True)
class Services:
    sessions: sessionmaker[Session]
    checkpointer: Checkpointer
    # Builds the chat model for one chat turn.
    chat_model: Callable[[], BaseChatModel]
    # The prices the agent plans with, which may pick a Product or look up a price.
    prices: Callable[[Session, MealPlan], Prices]
    # The prices a page or a button shows the plan with: only what is already known, so
    # viewing a plan never calls a store or the match model.
    shown_prices: Callable[[Session, MealPlan], Prices]
    picker: ProductPicker | None = None
    clock: Callable[[], datetime] = lambda: datetime.now(AMSTERDAM)

    def today(self) -> date:
        return self.clock().astimezone(AMSTERDAM).date()


def services_of(request: Request) -> Services:
    return request.app.state.services
