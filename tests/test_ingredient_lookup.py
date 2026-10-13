"""The lookup chain: normalise, then exact name or alias, then trigram, otherwise create."""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from pickled.ingredients import (
    Aisle,
    Ingredient,
    NewIngredient,
    find_ingredient,
    resolve_ingredient,
)

VEGETABLE = NewIngredient(aisle=Aisle.GROENTE_FRUIT)


@pytest.fixture
def catalogue(db_session):
    db_session.add_all(
        [
            Ingredient(name="rode kool", aliases=["rodekool"], aisle=Aisle.GROENTE_FRUIT),
            Ingredient(name="kipfilet", aliases=["kipborstfilet"], aisle=Aisle.VLEES_VIS_VEGA),
            Ingredient(name="volle melk", aisle=Aisle.ZUIVEL_EIEREN),
            Ingredient(name="olijfolie", aisle=Aisle.VOORRAAD, pantry=True),
        ]
    )
    db_session.flush()
    return db_session


def names(session) -> set[str]:
    return set(session.scalars(select(Ingredient.name)))


def test_an_exact_name_finds_the_ingredient(catalogue):
    assert find_ingredient(catalogue, "kipfilet").name == "kipfilet"


def test_an_alias_finds_the_ingredient(catalogue):
    assert find_ingredient(catalogue, "kipborstfilet").name == "kipfilet"


@pytest.mark.parametrize("name", ["Rode Kool", "rodekool", "rode-kool", "  RODE  KOOL "])
def test_case_spaces_and_hyphens_are_ignored(catalogue, name):
    assert find_ingredient(catalogue, name).name == "rode kool"


def test_normalisation_applies_to_aliases_too(catalogue):
    assert find_ingredient(catalogue, "Kip-Borst Filet").name == "kipfilet"


@pytest.mark.parametrize("name", ["kipfilets", "kipfillet", "kip filets"])
def test_a_close_spelling_is_a_trigram_hit(catalogue, name):
    assert find_ingredient(catalogue, name).name == "kipfilet"


@pytest.mark.parametrize("name", ["halfvolle melk", "zonnebloemolie", "rode ui"])
def test_a_different_food_is_a_trigram_miss(catalogue, name):
    assert find_ingredient(catalogue, name) is None


def test_resolve_returns_the_existing_ingredient_without_creating_one(catalogue):
    before = names(catalogue)

    assert resolve_ingredient(catalogue, "Rode-Kool", VEGETABLE).name == "rode kool"
    assert names(catalogue) == before


def test_resolve_creates_a_new_ingredient_on_a_miss(catalogue):
    details = NewIngredient(
        aisle=Aisle.GROENTE_FRUIT, pantry=False, grams_per_piece=150, keeps_days=14
    )

    ingredient = resolve_ingredient(catalogue, "Rode Ui", details)

    assert ingredient.id is not None
    assert ingredient.name == "rode ui"
    assert ingredient.aliases == []
    assert ingredient.aisle is Aisle.GROENTE_FRUIT
    assert ingredient.grams_per_piece == 150
    assert ingredient.keeps_days == 14
    assert find_ingredient(catalogue, "rode ui") == ingredient


def test_two_ingredients_cannot_share_a_normalised_name(catalogue):
    catalogue.add(Ingredient(name="Rode-Kool", aisle=Aisle.GROENTE_FRUIT))
    with pytest.raises(IntegrityError):
        catalogue.flush()
