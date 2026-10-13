"""`import_calendar`: replace all Seasonal Produce with what the calendar lists."""

import re
import tomllib
from collections.abc import Mapping, Set
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.orm import Session

from pickled.ingredients import Aisle, NewIngredient, resolve_ingredient
from pickled.seasonal.calendar import parse_calendar
from pickled.seasonal.models import Freshness, SeasonalProduce

PRODUCE = NewIngredient(aisle=Aisle.GROENTE_FRUIT)
STORAGE_CROPS_FILE = Path(__file__).parent / "storage_crops.toml"

# Produce sold all year is not Seasonal Produce, even if the calendar lists it.
YEAR_ROUND = {"aardappel", "aardappelen"}


@dataclass(frozen=True)
class ImportSummary:
    entries: int
    stored: int
    ingredients: int


def import_calendar(
    session: Session, page: str, *, storage_crops: Mapping[str, Set[int]] | None = None
) -> ImportSummary:
    """Replace all Seasonal Produce with the calendar on `page`, or raise `CalendarError`.

    The page is read in full before anything is replaced; the caller's transaction makes the
    replacement all or nothing.

    `storage_crops` maps a crop's name to its fresh-harvest months; by default, the committed
    `storage_crops.toml`.
    """
    entries = parse_calendar(page)
    if storage_crops is None:
        storage_crops = load_storage_crops()
    storage_crops = {crop_key(name): months for name, months in storage_crops.items()}
    session.execute(delete(SeasonalProduce))
    # Two names can be one Ingredient; it is fresh in a month if either name is.
    freshness: dict[tuple[int, int], Freshness] = {}
    for entry in entries:
        if crop_key(entry.name) in YEAR_ROUND:
            continue
        ingredient = resolve_ingredient(session, entry.name, PRODUCE)
        harvest = storage_crops.get(crop_key(entry.name))
        stored = harvest is not None and entry.month not in harvest
        key = (ingredient.id, entry.month)
        if not stored or key not in freshness:
            freshness[key] = Freshness.STORED if stored else Freshness.FRESH
    session.add_all(
        SeasonalProduce(ingredient_id=ingredient_id, month=month, freshness=tag)
        for (ingredient_id, month), tag in freshness.items()
    )
    session.flush()
    return ImportSummary(
        entries=len(freshness),
        stored=sum(tag is Freshness.STORED for tag in freshness.values()),
        ingredients=len({ingredient_id for ingredient_id, _month in freshness}),
    )


def load_storage_crops(path: Path = STORAGE_CROPS_FILE) -> dict[str, frozenset[int]]:
    """Each storage crop's fresh-harvest months, from a file like `storage_crops.toml`."""
    crops = tomllib.loads(path.read_text())["fresh_harvest_months"]
    return {name: frozenset(months) for name, months in crops.items()}


def crop_key(name: str) -> str:
    """`name` lowercased without spaces or hyphens, the same rule as `ingredient_key`."""
    return re.sub(r"[\s-]+", "", name.lower())
