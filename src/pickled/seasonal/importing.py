"""`import_calendar`: replace all Seasonal Produce with what the calendar lists."""

import tomllib
from collections.abc import Mapping, Set
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.orm import Session

from pickled.ingredients import Aisle, NewIngredient, find_ingredient, resolve_ingredient
from pickled.seasonal.calendar import parse_calendar
from pickled.seasonal.models import Freshness, SeasonalProduce

PRODUCE = NewIngredient(aisle=Aisle.GROENTE_FRUIT)
STORAGE_CROPS_FILE = Path(__file__).parent / "storage_crops.toml"

# Produce sold all year is not Seasonal Produce, even if the calendar lists it.
YEAR_ROUND = ("aardappel",)
# The harvest months of anything that isn't a storage crop: it is always fresh when listed.
ALL_YEAR = frozenset(range(1, 13))


@dataclass(frozen=True)
class ImportSummary:
    produce: int
    stored: int
    ingredients: int


def import_calendar(
    session: Session, page: str, *, storage_crops: Mapping[str, Set[int]] | None = None
) -> ImportSummary:
    """Replace all Seasonal Produce with the calendar on `page`, or raise `CalendarError`.

    The page is read in full before anything is replaced; the caller's transaction makes the
    replacement all or nothing.

    `storage_crops` maps a crop's name to its fresh-harvest months; by default, the committed
    `storage_crops.toml`. A storage crop listed outside them is stored.
    """
    entries = parse_calendar(page)
    if storage_crops is None:
        storage_crops = load_storage_crops()
    session.execute(delete(SeasonalProduce))
    # Two names can be one Ingredient, so rows are kept per (Ingredient, month).
    listed = {
        (resolve_ingredient(session, entry.name, PRODUCE).id, entry.month) for entry in entries
    }
    # Storage crops and staples are matched through the catalogue, so aliases count too.
    harvest_months = {
        ingredient.id: months
        for name, months in storage_crops.items()
        if (ingredient := find_ingredient(session, name)) is not None
    }
    year_round = {
        ingredient.id
        for name in YEAR_ROUND
        if (ingredient := find_ingredient(session, name)) is not None
    }
    rows = [
        SeasonalProduce(
            ingredient_id=ingredient_id,
            month=month,
            freshness=Freshness.STORED
            if month not in harvest_months.get(ingredient_id, ALL_YEAR)
            else Freshness.FRESH,
        )
        for ingredient_id, month in sorted(listed)
        if ingredient_id not in year_round
    ]
    session.add_all(rows)
    session.flush()
    return ImportSummary(
        produce=len(rows),
        stored=sum(row.freshness is Freshness.STORED for row in rows),
        ingredients=len({row.ingredient_id for row in rows}),
    )


def load_storage_crops() -> dict[str, frozenset[int]]:
    """Each storage crop's fresh-harvest months, from the committed `storage_crops.toml`."""
    crops = tomllib.loads(STORAGE_CROPS_FILE.read_text())["fresh_harvest_months"]
    return {name: frozenset(months) for name, months in crops.items()}
