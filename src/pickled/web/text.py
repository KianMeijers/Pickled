"""Dutch for the Household: dates, money, aisles, Food Goals and warnings.

Everything the Household reads is Dutch; the plan summary's own text is English, for the agent.
"""

from datetime import date
from decimal import Decimal

from pickled.planning import GoalCheck, PlanWarning, WarningKind
from pickled.stores import Store
from pickled.taste import FoodGoalKind

WEEKDAYS = ["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"]
MONTHS = ["jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"]
STORES = {Store.AH: "Albert Heijn", Store.JUMBO: "Jumbo"}
AISLES = {
    "groente_fruit": "Groente en fruit",
    "vlees_vis_vega": "Vlees, vis en vega",
    "zuivel_eieren": "Zuivel en eieren",
    "brood": "Brood",
    "voorraad": "Voorraadkast",
    "diepvries": "Diepvries",
    "dranken": "Dranken",
    "overig": "Overig",
}
GOALS = {
    FoodGoalKind.KCAL_PER_DAY: "Kcal per persoon per dag",
    FoodGoalKind.PROTEIN_G_PER_DAY: "Eiwit (g) per persoon per dag",
    FoodGoalKind.VEGETARIAN_DAYS_PER_WEEK: "Vegetarische dagen",
    FoodGoalKind.BUDGET_CENTS_PER_WEEK: "Budget per week",
}
UNITS = {"g": "g", "ml": "ml", "piece": "st", "tbsp": "el", "tsp": "tl", "pinch": "snufje"}


def weekday(day: date) -> str:
    return WEEKDAYS[day.weekday()]


def day_label(day: date) -> str:
    """Like "zaterdag 17 okt"."""
    return f"{weekday(day)} {day.day} {MONTHS[day.month - 1]}"


def euros(cents: int | Decimal | None, rough: bool = False) -> str:
    """Like "€ 12,50", with "≈ " in front if it is `rough`."""
    if cents is None:
        return "–"
    amount = f"{Decimal(cents) / 100:.2f}".replace(".", ",")
    return ("≈ " if rough else "") + f"€ {amount}"


def dollars(usd: Decimal | None) -> str:
    """Like "$ 3,20": LLM costs and the Runware balance are in USD."""
    if usd is None:
        return "–"
    return f"$ {Decimal(usd):.2f}".replace(".", ",")


def amount(quantity: Decimal | None, unit: str | None) -> str:
    """A Shopping List amount, like "300 g" or "2 st"; empty for "to taste"."""
    if quantity is None:
        return ""
    number = f"{quantity.normalize():f}".replace(".", ",")
    return f"{number} {UNITS.get(unit or '', unit or '')}".strip()


def goal(check: GoalCheck) -> str:
    """A Food Goal and how the plan does against it."""
    if check.kind == FoodGoalKind.OTHER:
        return check.text or ""
    money = check.kind == FoodGoalKind.BUDGET_CENTS_PER_WEEK
    show = euros if money else _number
    low, high = check.target_min, check.target_max
    if low is not None and high is not None:
        target = f"{show(low)}–{show(high)}"
    else:
        target = f"min {show(low)}" if low is not None else f"max {show(high)}"
    actual = show(check.actual) if check.actual is not None else "nog niets"
    return f"{GOALS[check.kind]}: {actual} (doel {target})"


def warning(found: PlanWarning) -> str:
    match found.kind:
        case WarningKind.PERISHABLE:
            return f"{found.ingredient} blijft niet goed tot {day_label(found.date)}."
        case WarningKind.REPEAT:
            return (
                f"Het recept van {day_label(found.date)} stond de afgelopen weken al op het menu."
            )
        case WarningKind.ROUGH:
            return f"De prijs van {found.ingredient} is geschat."
        case WarningKind.SPLIT:
            return (
                f"Bij de andere winkel scheelt {found.ingredient} samen {euros(found.cents)} "
                "in de aanbieding."
            )
    return found.message


def _number(value) -> str:
    return f"{Decimal(value):.0f}"
