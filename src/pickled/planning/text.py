"""The plan summary as compact text, for tool results. Code and prompts are English; the names
of Recipes and Ingredients stay as saved, in Dutch."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from pickled.stores import Store
from pickled.taste import FoodGoalKind

if TYPE_CHECKING:
    from pickled.planning.checks import GoalCheck
    from pickled.planning.summary import DaySummary, PlanSummary, ShoppingLine, StoreCosts

STORE_NAMES = {Store.AH: "AH", Store.JUMBO: "Jumbo"}
GOAL_NAMES = {
    FoodGoalKind.KCAL_PER_DAY: "kcal per person per day",
    FoodGoalKind.PROTEIN_G_PER_DAY: "protein g per person per day",
    FoodGoalKind.VEGETARIAN_DAYS_PER_WEEK: "vegetarian days",
    FoodGoalKind.BUDGET_CENTS_PER_WEEK: "budget",
}


def render(summary: PlanSummary) -> str:
    end = summary.days[-1].date
    status = str(summary.status)
    if status == "draft" and not summary.drafted:
        status += " (partial)"
    store = STORE_NAMES[summary.store] if summary.store else "not chosen"
    lines = [
        f"Meal Plan {summary.week_start} to {end}: {status}, store {store}, "
        f"{summary.people} people",
        "Days:",
        *(f"  {day.date:%a} {day.date}: {_day(day)}" for day in summary.days),
        "Shopping cost: " + "; ".join(_shopping(costs) for costs in summary.costs.values()),
        "Meal cost: "
        + "; ".join(
            f"{STORE_NAMES[c.store]} {_money(c.meal_cents, c.meal_rough)}"
            for c in summary.costs.values()
        ),
    ]
    if summary.goals:
        lines += ["Food Goals:", *(f"  {_goal(check)}" for check in summary.goals)]
    if summary.warnings:
        lines += ["Warnings:", *(f"  - {warning.message}" for warning in summary.warnings)]
    lines.append(f"Shopping List ({store}):")
    for (_, aisle), group in summary.to_buy.items():
        lines.append(f"  {aisle}: " + "; ".join(_item(line) for line in group))
    if summary.check_you_have:
        lines.append("  check you have: " + ", ".join(line.name for line in summary.check_you_have))
    return "\n".join(lines)


def _day(day: DaySummary) -> str:
    if day.kind == "unfilled":
        return "not filled"
    if day.kind == "empty":
        return "left empty"
    what = f"{day.title} (recipe {day.recipe_id}), {day.servings} servings"
    if day.kind == "leftovers":
        what = f"leftovers of {day.leftovers_of}, {what}"
    costs = ", ".join(
        f"{STORE_NAMES[store]} {_money(cents, day.meal_rough[store])}"
        for store, cents in day.meal_cents.items()
    )
    return f"{what}: {costs}"


def _shopping(costs: StoreCosts) -> str:
    parts = [
        f"{STORE_NAMES[costs.store]} {_money(costs.shopping_cents, costs.rough or costs.unpriced)}"
    ]
    if costs.rough:
        parts.append(_count(costs.rough, "estimated"))
    if costs.unpriced:
        parts.append(_count(costs.unpriced, "unpriced"))
    return ", ".join(parts)


def _goal(check: GoalCheck) -> str:
    if check.kind == FoodGoalKind.OTHER:
        return f"other: {check.text} (not checked by code)"
    money = check.kind == FoodGoalKind.BUDGET_CENTS_PER_WEEK
    text = f"{GOAL_NAMES[check.kind]} {_bounds(check.min, check.max, money)}"
    if check.kind in (FoodGoalKind.KCAL_PER_DAY, FoodGoalKind.PROTEIN_G_PER_DAY):
        text += f", dinner target {_bounds(check.target_min, check.target_max, money)}"
    if check.met is None:
        return f"{text}: no Meals yet"
    actual = _money(check.actual) if money else _number(check.actual)
    return f"{text}: {actual}, {'met' if check.met else 'NOT met'}"


def _item(line: ShoppingLine) -> str:
    text = line.name
    if line.quantity is not None:
        text += f" {_number(line.quantity)} {_unit(line.unit, line.quantity)}"
    if line.manual:
        text += " (own item)"
    elif line.price_cents is not None:
        packs = f"{line.packs} pack" + ("s" if line.packs != 1 else "")
        text += f", {packs} {_money(line.price_cents, line.rough)}"
    else:
        text += ", no price"
    if line.deal:
        text += f" [Deal: {line.deal}]"
    if line.checked:
        text += " (ticked)"
    return text


def _bounds(low, high, money: bool) -> str:
    show = _money if money else _number
    if low is not None and high is not None:
        return f"{show(low)}–{show(high)}"
    return f"min {show(low)}" if low is not None else f"max {show(high)}"


def _money(cents, rough=False) -> str:
    return ("≈ " if rough else "") + f"€{Decimal(cents) / 100:.2f}"


def _number(value) -> str:
    rounded = Decimal(value).quantize(Decimal("0.1")).normalize()
    return f"{rounded:f}"


def _unit(unit: str | None, quantity) -> str:
    if unit == "piece":
        return "piece" if quantity == 1 else "pieces"
    return unit or ""


def _count(n: int, what: str) -> str:
    return f"{n} item{'s' if n != 1 else ''} {what}"
