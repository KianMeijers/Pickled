"""Saving Recipes: structured lines on the Ingredient catalogue, in stored units."""

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from pickled.ingredients import Aisle, Ingredient, NewIngredient
from pickled.planning import (
    Nutrition,
    PlanRefused,
    RecipeLine,
    Unit,
    get_recipe,
    save_recipe,
)

NOW = datetime(2026, 10, 15, 18, 0, tzinfo=ZoneInfo("Europe/Amsterdam"))
NUTRITION = Nutrition(kcal=650, protein_g=40, carbs_g=60, fat_g=20)


def save(session, *lines, title="Kip met rijst", **options):
    return save_recipe(
        session,
        title=title,
        servings=2,
        steps="1. Kook de rijst.",
        tags=options.pop("tags", ["snel"]),
        nutrition=NUTRITION,
        lines=list(lines),
        now=NOW,
        **options,
    )


@pytest.fixture
def kipfilet(db_session):
    ingredient = Ingredient(name="kipfilet", aliases=["kippenfilet"], aisle=Aisle.VLEES_VIS_VEGA)
    db_session.add(ingredient)
    db_session.flush()
    return ingredient


def test_a_saved_recipe_reads_back_with_its_lines_on_catalogue_ingredients(db_session, kipfilet):
    saved = save(
        db_session,
        RecipeLine("kippenfilet", 300, "g", note="in blokjes"),
        RecipeLine("rijst", 150, "g", new=NewIngredient(aisle=Aisle.VOORRAAD, keeps_days=365)),
    )

    recipe = get_recipe(db_session, saved.id)
    assert [
        (line.ingredient.name, line.quantity, line.unit, line.note) for line in recipe.lines
    ] == [
        ("kipfilet", Decimal(300), Unit.G, "in blokjes"),
        ("rijst", Decimal(150), Unit.G, None),
    ]
    assert (recipe.kcal, recipe.protein_g) == (Decimal(650), Decimal(40))


def test_kilograms_and_litres_are_stored_as_grams_and_millilitres(db_session, kipfilet):
    recipe = save(
        db_session,
        RecipeLine("kipfilet", Decimal("0.5"), "kg"),
        RecipeLine("melk", Decimal("1.5"), "l", new=NewIngredient(aisle=Aisle.ZUIVEL_EIEREN)),
    )

    assert [(line.quantity, line.unit) for line in recipe.lines] == [
        (Decimal(500), Unit.G),
        (Decimal(1500), Unit.ML),
    ]


def test_an_unknown_ingredient_without_its_details_is_refused_and_nothing_is_saved(db_session):
    with pytest.raises(PlanRefused, match="tempeh"):
        save(db_session, RecipeLine("tempeh", 200, "g"))

    assert db_session.query(Ingredient).count() == 0


def test_a_measured_unit_needs_a_quantity_but_to_taste_does_not(db_session, kipfilet):
    with pytest.raises(PlanRefused, match="quantity"):
        save(db_session, RecipeLine("kipfilet", None, "g"))

    recipe = save(
        db_session,
        RecipeLine("zout", None, "to_taste", new=NewIngredient(aisle=Aisle.VOORRAAD, pantry=True)),
    )
    assert recipe.lines[0].unit == Unit.TO_TASTE


def test_an_unknown_unit_is_refused(db_session, kipfilet):
    with pytest.raises(PlanRefused, match="cup"):
        save(db_session, RecipeLine("kipfilet", 1, "cup"))


def test_a_variation_is_a_new_recipe_derived_from_the_first(db_session, kipfilet):
    first = save(db_session, RecipeLine("kipfilet", 300, "g"))

    variation = save(
        db_session, RecipeLine("kipfilet", 400, "g"), title="Kip met veel rijst", derived_from=first
    )

    assert variation.id != first.id
    assert variation.derived_from_id == first.id
    assert get_recipe(db_session, first.id).lines[0].quantity == Decimal(300)
