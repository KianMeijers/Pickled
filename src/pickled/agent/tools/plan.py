"""The tools that choose: the store, the Meals, the Household's own Shopping List items, and the
end of a draft. Each returns the plan summary."""

import datetime as dt
from decimal import Decimal

from langchain_core.tools import ToolException

from pickled import planning
from pickled.agent.tools.common import Runtime, agent_tool, with_summary
from pickled.stores import Store


@agent_tool
def set_store(store: Store, runtime: Runtime) -> str:
    """Choose the store the Household buys the Shopping List at."""
    with runtime.context.work() as work:
        summary = planning.set_store(
            work.session, work.meal_plan, store, today=work.today, prices=work.prices
        )
        return with_summary(f"The store is {store}.", summary)


@agent_tool
def set_meal(date: dt.date, recipe_id: int, servings: int, runtime: Runtime) -> str:
    """Cook saved Recipe `recipe_id` for `servings` on `date`, replacing that day's Meal.
    Servings are usually the Household's size."""
    with runtime.context.work() as work:
        recipe = planning.get_recipe(work.session, recipe_id)
        if recipe is None:
            raise ToolException(f"There is no Recipe {recipe_id}.")
        summary = planning.set_meal(
            work.session,
            work.meal_plan,
            date,
            recipe,
            servings,
            today=work.today,
            prices=work.prices,
        )
        return with_summary(f"{date}: {recipe.title}.", summary)


@agent_tool
def set_leftovers(
    date: dt.date, of_date: dt.date, runtime: Runtime, servings: int | None = None
) -> str:
    """Eat the leftovers of `of_date`'s Meal on the later `date`, for `servings` (the
    Household's size if left out). The Meal that is cooked grows by these servings."""
    with runtime.context.work() as work:
        summary = planning.set_leftovers(
            work.session,
            work.meal_plan,
            date,
            of_date,
            servings=servings,
            today=work.today,
            prices=work.prices,
        )
        return with_summary(f"{date}: leftovers of {of_date}.", summary)


@agent_tool
def clear_meal(date: dt.date, runtime: Runtime) -> str:
    """Leave `date` deliberately without a Meal: the Household eats elsewhere or plans it
    themselves. Days eating its leftovers become unfilled."""
    with runtime.context.work() as work:
        summary = planning.clear_meal(
            work.session, work.meal_plan, date, today=work.today, prices=work.prices
        )
        return with_summary(f"{date}: left empty.", summary)


@agent_tool
def add_shopping_item(
    name: str, runtime: Runtime, quantity: Decimal | None = None, unit: str | None = None
) -> str:
    """Add an item of the Household's own to the Shopping List, such as "wc-papier". It stays
    when the Meals change."""
    with runtime.context.work() as work:
        summary = planning.add_shopping_item(
            work.session, work.meal_plan, name, quantity, unit, prices=work.prices
        )
        return with_summary(f"Added {name} to the Shopping List.", summary)


@agent_tool
def finish_draft(summary: str, runtime: Runtime) -> str:
    """End the draft, once every day has a Meal or is deliberately left empty. `summary` is the
    first message the Household reads about the plan: a few sentences in Dutch on what you
    planned and why, quoting any costs from the plan summary."""
    with runtime.context.work() as work:
        finished = planning.finish_draft(
            work.session, work.meal_plan, now=work.now, prices=work.prices
        )
        return with_summary("The draft is finished.", finished)
