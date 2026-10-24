"""The tools that read: the plan, Deals and saved Recipes."""

from langchain_core.tools import ToolException

from pickled import planning
from pickled.agent.prompt import STORE_NAMES, describe_off
from pickled.agent.tools.common import Runtime, agent_tool
from pickled.deals import Deal, deals_by_ingredient
from pickled.ingredients import Aisle, find_ingredient
from pickled.planning import Recipe
from pickled.stores import Store

DEALS_SHOWN = 40


@agent_tool
def get_plan(runtime: Runtime) -> str:
    """The plan summary: each day's Meal, the Shopping List, the costs at both stores, the Food
    Goal checks and the warnings."""
    with runtime.context.work() as work:
        return planning.plan_summary(work.session, work.meal_plan, prices=work.prices).text()


@agent_tool
def search_deals(
    runtime: Runtime,
    ingredient: str | None = None,
    aisle: Aisle | None = None,
    store: Store | None = None,
) -> str:
    """The Deals valid on the Shopping Day for one Ingredient (by its Dutch name) or for every
    Ingredient in an aisle, at one store or both: what is on offer, the discount, the price and
    pack size where the store gives them."""
    if (ingredient is None) == (aisle is None):
        raise ToolException("Give either an ingredient or an aisle.")
    with runtime.context.work() as work:
        found = deals_by_ingredient(work.session, work.meal_plan.week_start, store)
        if ingredient is not None:
            wanted = find_ingredient(work.session, ingredient)
            if wanted is None:
                return f"No Ingredient called {ingredient!r} is known, so it has no Deals."
            found = {wanted: found.get(wanted, [])}
        else:
            found = {known: deals for known, deals in found.items() if known.aisle == aisle}
        lines = [_deal(known.name, deal) for known, deals in found.items() for deal in deals]
    if not lines:
        return "No Deals found."
    if len(lines) > DEALS_SHOWN:
        lines = [*lines[:DEALS_SHOWN], f"… and {len(lines) - DEALS_SHOWN} more"]
    return "\n".join(lines)


@agent_tool
def search_recipes(query: str, runtime: Runtime) -> str:
    """Saved Recipes whose title is like `query`, or that are tagged `query` (such as
    "vegetarisch"), to reuse instead of writing a new one."""
    with runtime.context.work() as work:
        found = planning.search_recipes(work.session, query)
        if not found:
            return "No saved Recipes match."
        return "\n".join(_recipe_line(recipe) for recipe in found)


@agent_tool
def get_recipe(recipe_id: int, runtime: Runtime) -> str:
    """A saved Recipe in full: its servings, tags, nutrition per serving, Ingredients and steps."""
    with runtime.context.work() as work:
        recipe = planning.get_recipe(work.session, recipe_id)
        if recipe is None:
            raise ToolException(f"There is no Recipe {recipe_id}.")
        lines = [
            _recipe_line(recipe),
            "Ingredients:",
            *(
                f"- {line.ingredient.name}"
                + (f" {line.quantity.normalize():f}" if line.quantity is not None else "")
                + f" {line.unit}"
                + (f" ({line.note})" if line.note else "")
                for line in recipe.lines
            ),
            "Steps:",
            recipe.steps,
        ]
        return "\n".join(lines)


def _recipe_line(recipe: Recipe) -> str:
    tags = ", ".join(recipe.tags) or "no tags"
    return (
        f"[{recipe.id}] {recipe.title}: {recipe.servings} servings; {tags}; per serving "
        f"{recipe.kcal:.0f} kcal, {recipe.protein_g:.0f} g protein"
    )


def _deal(ingredient: str, deal: Deal) -> str:
    parts = [f"[{STORE_NAMES[deal.store]}] {ingredient}: {deal.title}", describe_off(deal)]
    if deal.description:
        parts.append(deal.description)
    if deal.price_cents is not None:
        price = f"€{deal.price_cents / 100:.2f}"
        if deal.was_price_cents is not None:
            price += f" (was €{deal.was_price_cents / 100:.2f})"
        parts.append(price)
    if deal.unit_size:
        parts.append(deal.unit_size)
    parts.append(f"until {deal.valid_to}")
    return " | ".join(parts)
