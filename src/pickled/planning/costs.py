"""What a Meal Plan's Meals need, and what that costs at a store.

Two prices come out of it (ADR 0006): a Meal's **meal cost**, the price of the amount its Recipe
uses, pantry Ingredients included; and the **shopping cost**, whole packs at their price, pantry
Ingredients left out.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from typing import Protocol

from sqlalchemy.orm import Session

from pickled.deals import Deal, DiscountKind
from pickled.ingredients import (
    Ingredient,
    PackSize,
    PackUnit,
    Price,
    ProductPicker,
    parse_pack_size,
    price_for,
)
from pickled.planning.models import Meal, RecipeIngredient, Unit
from pickled.stores import Store

# Spoons are measured as millilitres.
SPOON_ML = {Unit.TBSP: Decimal(15), Unit.TSP: Decimal(5)}
MEASURES = {Unit.G: PackUnit.G, Unit.ML: PackUnit.ML, Unit.PIECE: PackUnit.PIECE}


class Prices(Protocol):
    """Where the plan summary gets regular prices: `price_for` with a ProductPicker in the app."""

    def regular(self, ingredient: Ingredient, store: Store) -> Price | None: ...


@dataclass(frozen=True)
class PickedPrices:
    """The app's Prices: each store's chosen Product, priced by `price_for` on the Shopping Day."""

    session: Session
    on: date
    picker: ProductPicker

    def regular(self, ingredient: Ingredient, store: Store) -> Price | None:
        return price_for(self.session, ingredient, store, on=self.on, picker=self.picker)


@dataclass(frozen=True)
class Amount:
    """An amount of an Ingredient in grams, millilitres or pieces; None for a pinch or to taste."""

    quantity: Decimal | None
    unit: PackUnit | None


@dataclass(frozen=True)
class Need:
    """An amount of an Ingredient the plan's Meals need, all together."""

    ingredient: Ingredient
    amount: Amount


@dataclass(frozen=True)
class Offer:
    """One way to buy an Ingredient at a store: a pack at a price, regular or on a Deal."""

    cents: int
    pack: PackSize | None
    rough: bool
    deal: Deal | None = None


@dataclass(frozen=True)
class Bought:
    """A Need bought at one store: how many packs, at what price, of which Offer."""

    need: Need
    offer: Offer | None
    packs: int | None
    cents: int | None
    rough: bool

    @property
    def priced(self) -> bool:
        return self.cents is not None


def line_amount(line: RecipeIngredient, factor: Decimal) -> Amount:
    """What `line` uses, in grams, millilitres or pieces, for `factor` times its Recipe."""
    if line.quantity is None or line.unit not in (*MEASURES, *SPOON_ML):
        return Amount(None, None)
    if line.unit in SPOON_ML:
        return Amount(line.quantity * SPOON_ML[line.unit] * factor, PackUnit.ML)
    return Amount(line.quantity * factor, MEASURES[line.unit])


def meal_factor(meal: Meal) -> Decimal:
    """How many times its Recipe a Meal eats: its servings over the Recipe's."""
    recipe = meal.recipe or (meal.leftovers_of.recipe if meal.leftovers_of else None)
    assert recipe is not None and meal.servings is not None
    return Decimal(meal.servings) / recipe.servings


def needs(meals: list[Meal]) -> list[Need]:
    """Everything the filled `meals` need, one per Ingredient (and unit, where the units can't
    be added up)."""
    amounts: dict[Ingredient, list[Amount]] = defaultdict(list)
    for meal in meals:
        if meal.empty:
            continue
        factor = meal_factor(meal)
        recipe = meal.recipe or meal.leftovers_of.recipe
        for line in recipe.lines:
            amounts[line.ingredient].append(line_amount(line, factor))
    return [
        Need(ingredient, amount)
        for ingredient, found in amounts.items()
        for amount in _added_up(ingredient, found)
    ]


def buy(need: Need, offers: list[Offer]) -> Bought:
    """The cheapest way to buy `need` from `offers`, in whole packs."""
    options = [_bought(need, offer) for offer in offers]
    if not options:
        return Bought(need, None, None, None, rough=False)
    return min(options, key=lambda bought: (bought.cents, bought.rough))


def used_cents(amount: Amount, bought: Bought) -> Decimal:
    """The price of `amount` of an Ingredient, at the price per unit it was bought at."""
    if bought.offer is None or amount.quantity is None:
        return Decimal(0)
    size = _in_unit(amount, bought.offer.pack, bought.need.ingredient)
    if size is None:
        # Without a size to divide by, the amount used costs the whole pack.
        return Decimal(bought.offer.cents)
    return Decimal(bought.offer.cents) * size / bought.offer.pack.amount


def offers(regular: Price | None, deals: list[Deal]) -> list[Offer]:
    """The ways to buy an Ingredient at a store: its regular Product, and each of its Deals
    there that can be priced."""
    found = []
    pack = parse_pack_size(regular.product.pack_size) if regular is not None else None
    if regular is not None:
        found.append(Offer(regular.cents, pack, regular.rough or pack is None))
    for deal in deals:
        own_pack = parse_pack_size(deal.unit_size)
        if deal.discount_kind == DiscountKind.FIXED_PRICE and own_pack is not None:
            found.append(Offer(deal.discount_price_cents, own_pack, rough=False, deal=deal))
        elif regular is not None and deal.effective_fraction is not None:
            cents = _round(regular.cents * (1 - deal.effective_fraction))
            found.append(Offer(cents, pack, regular.rough or pack is None, deal=deal))
    return found


def round_cents(cents: Decimal) -> int:
    return _round(cents)


def _bought(need: Need, offer: Offer) -> Bought:
    size = _in_unit(need.amount, offer.pack, need.ingredient)
    if size is None:
        # Nothing to divide by: one pack, as a rough guess when an amount was asked for.
        rough = offer.rough or need.amount.quantity is not None
        return Bought(need, offer, 1, offer.cents, rough)
    packs = max(1, int((size / offer.pack.amount).to_integral_value(ROUND_CEILING)))
    return Bought(need, offer, packs, packs * offer.cents, offer.rough)


def _in_unit(amount: Amount, pack: PackSize | None, ingredient: Ingredient) -> Decimal | None:
    """`amount` in `pack`'s unit, or None if there's no amount, no pack, or no way across."""
    if amount.quantity is None or pack is None:
        return None
    if amount.unit == pack.unit or {amount.unit, pack.unit} == {PackUnit.G, PackUnit.ML}:
        return amount.quantity
    grams = ingredient.grams_per_piece
    if grams is None:
        return None
    if amount.unit == PackUnit.PIECE:
        return amount.quantity * grams
    if pack.unit == PackUnit.PIECE:
        return amount.quantity / grams
    return None


def _added_up(ingredient: Ingredient, amounts: list[Amount]) -> list[Amount]:
    """`amounts` added up per unit. Millilitres count as grams beside grams, and pieces as
    grams where the Ingredient's weight per piece is known."""
    totals: dict[PackUnit | None, Decimal] = defaultdict(Decimal)
    for amount in amounts:
        totals[amount.unit] += amount.quantity or 0
    if PackUnit.G in totals and PackUnit.ML in totals:
        totals[PackUnit.G] += totals.pop(PackUnit.ML)
    if PackUnit.PIECE in totals and ingredient.grams_per_piece is not None and len(totals) > 1:
        weight = totals.pop(PackUnit.PIECE) * ingredient.grams_per_piece
        totals[PackUnit.ML if PackUnit.ML in totals else PackUnit.G] += weight
    measured = [Amount(quantity, unit) for unit, quantity in totals.items() if unit is not None]
    # A pinch or "to taste" is only listed if nothing else asks for the Ingredient.
    return measured or [Amount(None, None)]


def _round(cents: Decimal | int) -> int:
    return int(Decimal(cents).to_integral_value(ROUND_HALF_UP))
