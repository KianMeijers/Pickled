"""Parsing a Deal's text into a kind of discount, with regexes and never an LLM (spec §5).

Both stores' texts go through the same rules: AH writes "VOOR 2.49", Jumbo "voor 2,49". Text
that fits no kind is OTHER, and the agent reads the raw text instead.
"""

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum


class DiscountKind(StrEnum):
    PERCENT_OFF = "percent_off"
    FIXED_PRICE = "fixed_price"
    N_FOR_PRICE = "n_for_price"
    BUY_N_GET_M_FREE = "buy_n_get_m_free"
    NTH_HALF_PRICE = "nth_half_price"
    OTHER = "other"


@dataclass(frozen=True)
class Discount:
    """A parsed discount. `fraction` is the share off the regular price, where it is known."""

    text: str
    kind: DiscountKind
    percent: int | None = None
    price_cents: int | None = None
    n: int | None = None
    m: int | None = None
    fraction: Decimal | None = None


PRICE = r"(\d+)[.,](\d{2})"
PERCENT_OFF = re.compile(r"(\d+)\s*%\s*korting")
BUY_N_GET_M_FREE = re.compile(r"(\d+)\s*\+\s*(\d+)\s*gratis")
NTH_HALF_PRICE = re.compile(r"(\d+)e\s+halve\s+prijs")
N_FOR_PRICE = re.compile(rf"(\d+)\s+voor\s+{PRICE}")
FIXED_PRICE = re.compile(rf"(?:voor\s+)?{PRICE}")


def parse_discount(text: str, regular_cents: int | None = None) -> Discount:
    """The discount `text` describes; `regular_cents` lets a price discount get a fraction."""
    normal = " ".join(text.lower().split())

    if match := PERCENT_OFF.fullmatch(normal):
        percent = int(match[1])
        return Discount(
            text, DiscountKind.PERCENT_OFF, percent=percent, fraction=_share(percent, 100)
        )
    if match := BUY_N_GET_M_FREE.fullmatch(normal):
        n, m = int(match[1]), int(match[2])
        return Discount(text, DiscountKind.BUY_N_GET_M_FREE, n=n, m=m, fraction=_share(m, n + m))
    if match := NTH_HALF_PRICE.fullmatch(normal):
        n = int(match[1])
        return Discount(text, DiscountKind.NTH_HALF_PRICE, n=n, fraction=_share(1, 2 * n))
    if match := N_FOR_PRICE.fullmatch(normal):
        n, price = int(match[1]), _cents(match[2], match[3])
        fraction = _price_share(price, n * regular_cents) if regular_cents else None
        return Discount(text, DiscountKind.N_FOR_PRICE, n=n, price_cents=price, fraction=fraction)
    if match := FIXED_PRICE.fullmatch(normal):
        price = _cents(match[1], match[2])
        fraction = _price_share(price, regular_cents) if regular_cents else None
        return Discount(text, DiscountKind.FIXED_PRICE, price_cents=price, fraction=fraction)
    return Discount(text, DiscountKind.OTHER)


def _cents(euros: str, cents: str) -> int:
    return int(euros) * 100 + int(cents)


def _share(part: int, whole: int) -> Decimal:
    return (Decimal(part) / Decimal(whole)).quantize(Decimal("0.0001"), ROUND_HALF_UP)


def _price_share(price_cents: int, regular_cents: int) -> Decimal | None:
    """The share off for paying `price_cents` instead of `regular_cents`; None if it isn't off."""
    if price_cents >= regular_cents:
        return None
    return _share(regular_cents - price_cents, regular_cents)
