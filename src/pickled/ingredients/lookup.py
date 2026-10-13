"""The lookup chain: normalise, then exact name or alias, then a trigram match, else create.

Normalising is the `ingredient_key` SQL function (lowercase, no whitespace or hyphens), so the
same rule applies to the query, the stored names and the unique index.
"""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from pickled.ingredients.models import Aisle, Ingredient

# Calibrated on Dutch names: plurals and typos of longer words score 0.69 to 0.77
# ("champignons", "brocoli"); different foods score 0.57 or less ("knoflookteen",
# "halfvolle melk" against "volle melk").
TRIGRAM_THRESHOLD = 0.6

# Each Ingredient's known names: its name first, then its aliases in order.
KNOWN_NAMES = """
    FROM ingredient
    CROSS JOIN LATERAL unnest(array_prepend(ingredient.name, ingredient.aliases))
        WITH ORDINALITY AS known(name, position)
"""

EXACT = text(f"""
    SELECT ingredient.* {KNOWN_NAMES}
    WHERE ingredient_key(known.name) = ingredient_key(:name)
    ORDER BY known.position, ingredient.id
    LIMIT 1
""")

TRIGRAM = text(f"""
    SELECT ingredient.* {KNOWN_NAMES}
    WHERE similarity(ingredient_key(known.name), ingredient_key(:name)) >= :threshold
    ORDER BY similarity(ingredient_key(known.name), ingredient_key(:name)) DESC, ingredient.id
    LIMIT 1
""")


@dataclass(frozen=True)
class NewIngredient:
    """What a caller knows about an Ingredient, used only if the lookup has to create it."""

    aisle: Aisle
    pantry: bool = False
    grams_per_piece: Decimal | int | None = None
    keeps_days: int | None = None


def find_ingredient(session: Session, name: str) -> Ingredient | None:
    """The Ingredient `name` refers to, by exact name or alias, then by trigram; else None."""
    for statement in (EXACT, TRIGRAM.bindparams(threshold=TRIGRAM_THRESHOLD)):
        found = session.scalars(
            select(Ingredient).from_statement(statement.bindparams(name=name))
        ).first()
        if found is not None:
            return found
    return None


def resolve_ingredient(session: Session, name: str, new: NewIngredient) -> Ingredient:
    """The Ingredient `name` refers to, created from `new` if the catalogue has no match."""
    found = find_ingredient(session, name)
    if found is not None:
        return found
    ingredient = Ingredient(
        name=" ".join(name.lower().split()),
        aliases=[],
        aisle=new.aisle,
        pantry=new.pantry,
        grams_per_piece=new.grams_per_piece,
        keeps_days=new.keeps_days,
    )
    session.add(ingredient)
    session.flush()
    return ingredient
