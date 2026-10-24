"""The stored Shopping List: regenerated from the Meals, keeping manual items and ticks."""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from pickled.ingredients import Aisle, find_ingredient
from pickled.planning.costs import Bought, Need
from pickled.planning.errors import PlanRefused
from pickled.planning.models import ItemSource, MealPlan, ShoppingListItem
from pickled.stores import Store

AISLES = list(Aisle)


def regenerate(
    session: Session, meal_plan: MealPlan, needs: list[Need], bought: dict[Need, Bought] | None
) -> list[ShoppingListItem]:
    """Bring the Recipe lines in line with `needs`, priced as `bought` at the plan's store if it
    has one. A line is matched by name and kept, ticked or not; a line no longer needed goes."""
    items = _items(session, meal_plan)
    ticked = {item.name for item in items if item.source == ItemSource.RECIPE and item.checked}
    unused = {(item.name, item.unit): item for item in items if item.source == ItemSource.RECIPE}
    for need in needs:
        unit = need.amount.unit.value if need.amount.unit else None
        item = unused.pop((need.ingredient.name, unit), None)
        if item is None:
            item = ShoppingListItem(
                meal_plan_id=meal_plan.id,
                name=need.ingredient.name,
                unit=unit,
                source=ItemSource.RECIPE,
                checked=need.ingredient.name in ticked,
            )
            session.add(item)
        line = bought[need] if bought is not None else None
        item.ingredient_id = need.ingredient.id
        item.quantity = need.amount.quantity
        item.pantry = need.ingredient.pantry
        item.aisle = need.ingredient.aisle
        item.store = meal_plan.store
        item.deal_id = line.offer.deal.id if line and line.offer and line.offer.deal else None
        item.packs = line.packs if line else None
        item.est_price_cents = line.cents if line else None
        item.rough = line.rough if line else False
    for item in unused.values():
        session.delete(item)
    session.flush()
    items = _items(session, meal_plan)
    for item in items:
        # Its deal_id may have changed under the loaded Deal.
        session.expire(item, ["deal"])
    return sorted(items, key=_order)


def add_item(
    session: Session,
    meal_plan: MealPlan,
    name: str,
    quantity: Decimal | int | None = None,
    unit: str | None = None,
) -> ShoppingListItem:
    """Add an item of the Household's own, in the aisle of the Ingredient it names, if any."""
    name = " ".join(name.split())
    if not name:
        raise PlanRefused("A Shopping List item needs a name.")
    known = find_ingredient(session, name)
    item = ShoppingListItem(
        meal_plan_id=meal_plan.id,
        name=name,
        ingredient_id=known.id if known else None,
        quantity=quantity,
        unit=unit,
        source=ItemSource.MANUAL,
        store=meal_plan.store,
        aisle=known.aisle if known else Aisle.OVERIG,
    )
    session.add(item)
    session.flush()
    return item


def tick_shopping_item(session: Session, item_id: int, checked: bool = True) -> ShoppingListItem:
    """Tick an item off the Shopping List, or untick it."""
    item = session.get(ShoppingListItem, item_id)
    if item is None:
        raise PlanRefused(f"There is no Shopping List item {item_id}.")
    item.checked = checked
    session.flush()
    return item


def _items(session: Session, meal_plan: MealPlan) -> list[ShoppingListItem]:
    return list(
        session.scalars(
            select(ShoppingListItem).where(ShoppingListItem.meal_plan_id == meal_plan.id)
        )
    )


def _order(item: ShoppingListItem) -> tuple:
    """Pantry items last, in their "check you have" section; the rest by store and aisle."""
    return (item.pantry, str(item.store or Store.AH), AISLES.index(item.aisle), item.name, item.id)
