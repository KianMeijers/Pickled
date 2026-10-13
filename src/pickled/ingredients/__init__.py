"""The Ingredient catalogue that Recipes, Deals and Seasonal Produce all point to (ADR 0006).

Every name reaches an Ingredient through one lookup chain: `find_ingredient` to match, and
`resolve_ingredient` to match or create.
"""

from pickled.ingredients.lookup import (
    TRIGRAM_THRESHOLD,
    NewIngredient,
    find_ingredient,
    resolve_ingredient,
)
from pickled.ingredients.models import Aisle, Ingredient, PriceObservation, PriceSource, Product
from pickled.ingredients.prices import ProductCandidate, RegularPriceSource

__all__ = [
    "TRIGRAM_THRESHOLD",
    "Aisle",
    "Ingredient",
    "NewIngredient",
    "PriceObservation",
    "PriceSource",
    "Product",
    "ProductCandidate",
    "RegularPriceSource",
    "find_ingredient",
    "resolve_ingredient",
]
