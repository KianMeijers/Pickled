"""Discount parsing: regexes over the store's deal text, never an LLM (spec §5)."""

from decimal import Decimal

import pytest

from pickled.deals import DiscountKind, parse_discount


def test_percent_off():
    discount = parse_discount("25% korting")

    assert discount.kind is DiscountKind.PERCENT_OFF
    assert discount.percent == 25
    assert discount.fraction == Decimal("0.25")


def test_fixed_price_with_a_regular_price_has_a_fraction():
    discount = parse_discount("voor 2,49", regular_cents=349)

    assert discount.kind is DiscountKind.FIXED_PRICE
    assert discount.price_cents == 249
    assert discount.fraction == Decimal("0.2865")


def test_fixed_price_without_a_regular_price_has_no_fraction():
    discount = parse_discount("VOOR 2.49")

    assert discount.kind is DiscountKind.FIXED_PRICE
    assert discount.price_cents == 249
    assert discount.fraction is None


def test_a_bare_price_is_a_fixed_price():
    assert parse_discount("4,99").kind is DiscountKind.FIXED_PRICE


def test_n_for_price():
    discount = parse_discount("2 voor 2,99", regular_cents=200)

    assert discount.kind is DiscountKind.N_FOR_PRICE
    assert (discount.n, discount.price_cents) == (2, 299)
    assert discount.fraction == Decimal("0.2525")


@pytest.mark.parametrize(
    ("text", "n", "m", "fraction"),
    [
        ("1+1 gratis", 1, 1, Decimal("0.5")),
        ("2 + 1 GRATIS", 2, 1, Decimal("0.3333")),
        ("10+2 gratis", 10, 2, Decimal("0.1667")),
    ],
)
def test_buy_n_get_m_free(text, n, m, fraction):
    discount = parse_discount(text)

    assert discount.kind is DiscountKind.BUY_N_GET_M_FREE
    assert (discount.n, discount.m) == (n, m)
    assert discount.fraction == fraction


def test_nth_half_price():
    discount = parse_discount("2e halve prijs")

    assert discount.kind is DiscountKind.NTH_HALF_PRICE
    assert discount.n == 2
    assert discount.fraction == Decimal("0.25")


@pytest.mark.parametrize(
    "text",
    [
        "1,00 korting",
        "1,99 per kilo",
        "1,09 per 500 gram",
        "100 GRAM VOOR 2.99",
        "Gratis glas bij 2 Leffe Packs",
        "OP=OP",
    ],
)
def test_real_texts_that_fit_no_kind_are_other(text):
    discount = parse_discount(text)

    assert discount.kind is DiscountKind.OTHER
    assert discount.fraction is None


def test_the_raw_text_is_always_kept():
    assert parse_discount("  2e Halve Prijs ").text == "  2e Halve Prijs "
