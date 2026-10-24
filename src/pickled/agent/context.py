"""What one run of the agent works on: a Meal Plan, the database and the prices to plan with."""

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy.orm import Session, sessionmaker

from pickled.ingredients import ProductPicker
from pickled.planning import MealPlan, Prices
from pickled.stores import AMSTERDAM


@dataclass(frozen=True)
class Work:
    """One tool call's unit of work: a transaction on the Meal Plan."""

    session: Session
    meal_plan: MealPlan
    prices: Prices
    now: datetime

    @property
    def today(self) -> date:
        return self.now.astimezone(AMSTERDAM).date()


@dataclass(frozen=True)
class PlanContext:
    """The runtime context of an agent run on Meal Plan `meal_plan_id`.

    `prices` gives the prices to plan with; the app's are each store's chosen Product, picked by
    `picker`, which `set_product` also needs (`draft_with_the_app` shows the wiring).
    """

    meal_plan_id: int
    sessions: sessionmaker[Session]
    prices: Callable[[Session, MealPlan], Prices]
    picker: ProductPicker | None = None
    clock: Callable[[], datetime] = lambda: datetime.now(AMSTERDAM)
    # The model can call several tools at once, and they run in threads: one at a time keeps
    # each tool's change to the plan whole.
    lock: threading.Lock = field(default_factory=threading.Lock, compare=False, repr=False)

    @contextmanager
    def work(self) -> Iterator[Work]:
        """A transaction on the Meal Plan, committed if the block finishes."""
        with self.lock, self.sessions.begin() as session:
            meal_plan = session.get_one(MealPlan, self.meal_plan_id)
            yield Work(session, meal_plan, self.prices(session, meal_plan), self.clock())
