"""Building blocks for planning tests: Ingredients, Recipes, Meal Plans and a fake price book."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from pickled.deals import Channel, Deal, DealIngredient, parse_discount
from pickled.ingredients import Aisle, Ingredient, Price, Product
from pickled.planning import Nutrition, RecipeLine, save_recipe, start_meal_plan
from pickled.stores import Store
from pickled.taste import set_household

AMSTERDAM = ZoneInfo("Europe/Amsterdam")
SATURDAY = date(2026, 10, 17)
WEEK = [SATURDAY + timedelta(days=i) for i in range(7)]
NOW = datetime(2026, 10, 15, 18, 0, tzinfo=AMSTERDAM)
TODAY = NOW.date()


class FakePrices:
    """Regular pack prices set per (Ingredient name, store), as `price_for` would give them."""

    def __init__(self):
        self.prices: dict[tuple[str, Store], Price] = {}

    def set(self, name, store, cents, pack_size, *, rough=False, observed_at=NOW):
        product = Product(store=store, sku=f"{store}-{name}", name=name, pack_size=pack_size)
        self.prices[(name, store)] = Price(cents, product, observed_at, rough)
        return self

    def regular(self, ingredient, store):
        return self.prices.get((ingredient.name, store))


def ingredient(session, name, aisle=Aisle.OVERIG, **fields) -> Ingredient:
    found = Ingredient(name=name, aliases=[], aisle=aisle, **fields)
    session.add(found)
    session.flush()
    return found


def recipe(session, title, *lines, servings=2, tags=(), nutrition=None):
    """A Recipe whose `lines` are (Ingredient name, quantity, unit) of catalogue Ingredients."""
    return save_recipe(
        session,
        title=title,
        servings=servings,
        steps="1. Kook.",
        tags=list(tags),
        nutrition=nutrition or Nutrition(kcal=600, protein_g=30, carbs_g=60, fat_g=20),
        lines=[RecipeLine(name, quantity, unit) for name, quantity, unit in lines],
        now=NOW,
    )


def plan(session, week_start=SATURDAY, people=2):
    set_household(session, people=people)
    return start_meal_plan(session, week_start, now=NOW)


def cents(amount: str) -> int:
    return int(Decimal(amount) * 100)


def deal(session, store, on, discount_text, unit_size=None, *, channel=Channel.IN_STORE):
    """A Deal at `store` valid in the plan's week, tagged with the Ingredient `on`."""
    discount = parse_discount(discount_text)
    found = Deal(
        store=store,
        source_id=f"{store}-{on.name}-{discount_text}",
        valid_from=SATURDAY - timedelta(days=1),
        valid_to=SATURDAY + timedelta(days=1),
        title=on.name,
        discount_text=discount_text,
        discount_kind=discount.kind,
        discount_percent=discount.percent,
        discount_price_cents=discount.price_cents,
        discount_n=discount.n,
        discount_m=discount.m,
        effective_fraction=discount.fraction,
        channel=channel,
        unit_size=unit_size,
        first_seen_at=NOW,
        last_seen_at=NOW,
    )
    session.add(found)
    session.flush()
    session.add(DealIngredient(deal_id=found.id, ingredient_id=on.id, tagged_at=NOW))
    session.flush()
    return found
