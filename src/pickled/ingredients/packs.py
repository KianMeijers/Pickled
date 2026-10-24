"""How much a Product's pack holds, read from the size text a store lists ("500 g", "4 x 300 g").

Planning needs it to round to whole packs. Volumes are kept in millilitres; a text with no
amount in it ("los", "per bos") gives None.
"""

import re
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class PackUnit(StrEnum):
    G = "g"
    ML = "ml"
    PIECE = "piece"


@dataclass(frozen=True)
class PackSize:
    amount: Decimal
    unit: PackUnit


# Each unit a store writes, with what one of it is in grams, millilitres or pieces.
UNITS = {
    "g": (PackUnit.G, 1),
    "gr": (PackUnit.G, 1),
    "gram": (PackUnit.G, 1),
    "kg": (PackUnit.G, 1000),
    "kilo": (PackUnit.G, 1000),
    "ml": (PackUnit.ML, 1),
    "cl": (PackUnit.ML, 10),
    "dl": (PackUnit.ML, 100),
    "l": (PackUnit.ML, 1000),
    "liter": (PackUnit.ML, 1000),
    "st": (PackUnit.PIECE, 1),
    "stuk": (PackUnit.PIECE, 1),
    "stuks": (PackUnit.PIECE, 1),
}

SIZE = re.compile(
    r"(?:ca\.?|per)?\s*(?:(?P<count>\d+)\s*x\s*)?(?P<amount>\d+(?:[.,]\d+)?)?\s*(?P<unit>[a-z]+)"
)


def parse_pack_size(text: str | None) -> PackSize | None:
    """The amount a pack with size `text` holds, or None if the text doesn't say."""
    if not text:
        return None
    match = SIZE.fullmatch(" ".join(text.lower().split()))
    if match is None or match["unit"] not in UNITS:
        return None
    unit, factor = UNITS[match["unit"]]
    amount = Decimal(match["amount"].replace(",", ".")) if match["amount"] else Decimal(1)
    count = int(match["count"]) if match["count"] else 1
    return PackSize(amount * factor * count, unit)
