"""Searching saved Recipes for reuse: trigram on the title, or a tag (spec §13)."""

from planning_helpers import ingredient, recipe

from pickled.ingredients import Aisle
from pickled.planning import search_recipes


def titles(found) -> list[str]:
    return [found_recipe.title for found_recipe in found]


def test_a_recipe_is_found_by_a_close_title(db_session):
    ingredient(db_session, "kipfilet", Aisle.VLEES_VIS_VEGA)
    recipe(db_session, "Kip tandoori met rijst", ("kipfilet", 300, "g"))
    recipe(db_session, "Linzensoep", ("kipfilet", 300, "g"))

    assert titles(search_recipes(db_session, "kip tandori")) == ["Kip tandoori met rijst"]


def test_a_recipe_is_found_by_one_of_its_tags(db_session):
    ingredient(db_session, "linzen", Aisle.VOORRAAD)
    recipe(db_session, "Linzensoep", ("linzen", 200, "g"), tags=["vegetarisch", "soep"])
    recipe(db_session, "Linzencurry", ("linzen", 200, "g"), tags=["curry"])

    assert titles(search_recipes(db_session, "Vegetarisch")) == ["Linzensoep"]
