"""The agent's tools: thin wrappers over the domain modules (spec §7). The agent chooses through
them, and every write tool returns the plan summary that code calculates (ADR 0007)."""

from pickled.agent.tools.plan import (
    add_shopping_item,
    clear_meal,
    finish_draft,
    set_leftovers,
    set_meal,
    set_store,
)
from pickled.agent.tools.read import get_plan, get_recipe, search_deals, search_recipes
from pickled.agent.tools.recipes import save_recipe, set_product
from pickled.agent.tools.taste import (
    add_taste_note,
    archive_taste_note,
    clear_food_goal,
    set_food_goal,
    update_taste_note,
)

TOOLS = [
    get_plan,
    search_deals,
    search_recipes,
    get_recipe,
    set_store,
    set_meal,
    set_leftovers,
    clear_meal,
    finish_draft,
    save_recipe,
    set_product,
    add_shopping_item,
    add_taste_note,
    update_taste_note,
    archive_taste_note,
    set_food_goal,
    clear_food_goal,
]

__all__ = ["TOOLS"]
