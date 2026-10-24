"""`parse_pack_size`: how much a store's pack holds, from the size text it lists."""

from decimal import Decimal

import pytest

from pickled.ingredients import PackSize, PackUnit, parse_pack_size


@pytest.mark.parametrize(
    ("text", "amount", "unit"),
    [
        ("500 g", "500", PackUnit.G),
        ("ca. 320 g", "320", PackUnit.G),
        ("4 x 300 g", "1200", PackUnit.G),
        ("1 kg", "1000", PackUnit.G),
        ("1,5 l", "1500", PackUnit.ML),
        ("750 ml", "750", PackUnit.ML),
        ("33 cl", "330", PackUnit.ML),
        ("1 stuk", "1", PackUnit.PIECE),
        ("6 stuks", "6", PackUnit.PIECE),
        ("per stuk", "1", PackUnit.PIECE),
        ("Per 500 gram", "500", PackUnit.G),
    ],
)
def test_a_listed_size_is_parsed_into_grams_millilitres_or_pieces(text, amount, unit):
    assert parse_pack_size(text) == PackSize(Decimal(amount), unit)


@pytest.mark.parametrize("text", [None, "", "los", "per bos", "2 personen"])
def test_a_size_that_says_no_amount_is_none(text):
    assert parse_pack_size(text) is None
