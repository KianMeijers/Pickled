"""Saving and reading Recipes. A saved Recipe never changes; a variation is a new one."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from pickled.ingredients import Ingredient, NewIngredient, find_ingredient, resolve_ingredient
from pickled.planning.errors import PlanRefused
from pickled.planning.models import Recipe, RecipeIngredient, Unit

# Units a Recipe may be written in that are stored as another: (stored unit, factor).
CONVERTED = {"kg": (Unit.G, 1000), "l": (Unit.ML, 1000)}
# Units whose lines need no quantity.
UNMEASURED = {Unit.PINCH, Unit.TO_TASTE}


@dataclass(frozen=True)
class Nutrition:
    """Estimated nutrition per serving."""

    kcal: Decimal | int
    protein_g: Decimal | int
    carbs_g: Decimal | int
    fat_g: Decimal | int


@dataclass(frozen=True)
class RecipeLine:
    """One ingredient line as written. `new` describes the Ingredient in case the catalogue
    doesn't know it yet."""

    ingredient: str
    quantity: Decimal | int | None
    unit: str
    note: str | None = None
    new: NewIngredient | None = None


def save_recipe(
    session: Session,
    *,
    title: str,
    servings: int,
    steps: str,
    tags: list[str],
    nutrition: Nutrition,
    lines: list[RecipeLine],
    derived_from: Recipe | None = None,
    now: datetime,
) -> Recipe:
    """Save a new Recipe. Every line is checked before anything is saved."""
    if servings < 1:
        raise PlanRefused("A Recipe is for at least one serving.")
    stored = [(_stored_amount(line), _known(session, line)) for line in lines]
    recipe = Recipe(
        title=title,
        servings=servings,
        steps=steps,
        tags=list(tags),
        kcal=nutrition.kcal,
        protein_g=nutrition.protein_g,
        carbs_g=nutrition.carbs_g,
        fat_g=nutrition.fat_g,
        derived_from_id=derived_from.id if derived_from is not None else None,
        created_at=now,
    )
    for line, ((quantity, unit), ingredient) in zip(lines, stored, strict=True):
        if ingredient is None:
            assert line.new is not None
            ingredient = resolve_ingredient(session, line.ingredient, line.new)
        recipe.lines.append(
            RecipeIngredient(ingredient=ingredient, quantity=quantity, unit=unit, note=line.note)
        )
    session.add(recipe)
    session.flush()
    return recipe


def get_recipe(session: Session, recipe_id: int) -> Recipe | None:
    return session.get(Recipe, recipe_id)


def _stored_amount(line: RecipeLine) -> tuple[Decimal | None, Unit]:
    quantity = Decimal(line.quantity) if line.quantity is not None else None
    if line.unit in CONVERTED:
        unit, factor = CONVERTED[line.unit]
        quantity = quantity * factor if quantity is not None else None
    else:
        try:
            unit = Unit(line.unit)
        except ValueError:
            units = ", ".join([*Unit, *CONVERTED])
            raise PlanRefused(
                f"Unknown unit {line.unit!r} for {line.ingredient}: use {units}."
            ) from None
    if quantity is None and unit not in UNMEASURED:
        raise PlanRefused(f"{line.ingredient} in {unit} needs a quantity.")
    if quantity is not None and quantity <= 0:
        raise PlanRefused(f"{line.ingredient} needs a quantity above zero.")
    return quantity, unit


def _known(session: Session, line: RecipeLine) -> Ingredient | None:
    """The catalogue's Ingredient for the line, or None if it can be created from `new`."""
    found = find_ingredient(session, line.ingredient)
    if found is None and line.new is None:
        raise PlanRefused(
            f"{line.ingredient} is a new Ingredient: give its aisle, whether it is pantry, "
            "its grams per piece and how many days it keeps."
        )
    return found
