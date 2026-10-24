"""The tools that write Recipes and correct Product picks. Each returns the plan summary."""

from decimal import Decimal

from langchain_core.tools import ToolException
from pydantic import BaseModel, Field

from pickled import ingredients, planning
from pickled.agent.tools.common import Runtime, agent_tool, summarise
from pickled.ingredients import Aisle, NewIngredient
from pickled.stores import Store


class Nutrition(BaseModel):
    """Estimated nutrition per serving."""

    kcal: Decimal
    protein_g: Decimal
    carbs_g: Decimal
    fat_g: Decimal


class Line(BaseModel):
    """One Ingredient of a Recipe."""

    ingredient: str = Field(description='The Dutch name, lowercase and singular ("rode ui")')
    quantity: Decimal | None = Field(None, description="Leave out for pinch and to_taste")
    unit: str = Field(description="g, kg, ml, l, piece, tbsp, tsp, pinch or to_taste")
    note: str | None = Field(None, description='How it is prepared, such as "in blokjes"')
    aisle: Aisle | None = Field(
        None, description="For an Ingredient new to the catalogue: its aisle in the store"
    )
    pantry: bool = Field(
        False, description="For a new Ingredient: a staple that keeps for months (oil, spices)"
    )
    grams_per_piece: Decimal | None = Field(
        None, description="For a new Ingredient sold per piece: roughly what one weighs"
    )
    keeps_days: int | None = Field(
        None, description="For a new Ingredient: roughly how many days it keeps after shopping"
    )


@agent_tool
def save_recipe(
    title: str,
    servings: int,
    steps: str,
    tags: list[str],
    nutrition: Nutrition,
    lines: list[Line],
    runtime: Runtime,
    derived_from_id: int | None = None,
) -> str:
    """Save a new Recipe, in Dutch, to use with `set_meal`. `steps` are numbered markdown steps.
    Tag it with what helps find it again, and `vegetarisch` when it has no meat or fish. For
    an Ingredient the catalogue doesn't know yet, also give its aisle, whether it is pantry,
    its grams per piece and how many days it keeps; a refusal says which. A variation on a
    saved Recipe gives that Recipe as `derived_from_id`."""
    with runtime.context.work() as work:
        derived_from = None
        if derived_from_id is not None:
            derived_from = planning.get_recipe(work.session, derived_from_id)
            if derived_from is None:
                raise ToolException(f"There is no Recipe {derived_from_id}.")
        recipe = planning.save_recipe(
            work.session,
            title=title,
            servings=servings,
            steps=steps,
            tags=tags,
            nutrition=planning.Nutrition(**nutrition.model_dump()),
            lines=[_line(line) for line in lines],
            derived_from=derived_from,
            now=work.now,
        )
        return summarise(f"Saved Recipe {recipe.id}: {recipe.title}.", work)


@agent_tool
def set_product(ingredient: str, store: Store, hint: str, runtime: Runtime) -> str:
    """Choose a different product for an Ingredient at a store, as the Household asks in
    `hint` (such as "de biologische" or "een grotere verpakking")."""
    picker = runtime.context.picker
    if picker is None:
        raise ToolException("Products can't be chosen in this run.")
    with runtime.context.work() as work:
        found = ingredients.find_ingredient(work.session, ingredient)
        if found is None:
            raise ToolException(f"No Ingredient called {ingredient!r} is known.")
        product = ingredients.set_product(work.session, found, store, hint, picker=picker)
        if product is None:
            headline = f"Nothing at {store} fits that, so the product for {found.name} stays."
        else:
            headline = f"{found.name} at {store} is now {product.name} ({product.pack_size})."
        return summarise(headline, work)


def _line(line: Line) -> planning.RecipeLine:
    new = None
    if line.aisle is not None:
        new = NewIngredient(
            aisle=line.aisle,
            pantry=line.pantry,
            grams_per_piece=line.grams_per_piece,
            keeps_days=line.keeps_days,
        )
    return planning.RecipeLine(line.ingredient, line.quantity, line.unit, line.note, new)
