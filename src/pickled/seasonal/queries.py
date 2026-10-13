"""Reading Seasonal Produce."""

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, contains_eager

from pickled.ingredients import Ingredient
from pickled.seasonal.models import SeasonalProduce


def seasonal_for(session: Session, month: int) -> list[SeasonalProduce]:
    """The Seasonal Produce of `month` (1 to 12) with its Ingredients, fresh first, then by name.

    Empty until `pickled seasonal import` has run; planning goes ahead without it.
    """
    return list(
        session.scalars(
            select(SeasonalProduce)
            .join(SeasonalProduce.ingredient)
            .where(SeasonalProduce.month == month)
            .order_by(SeasonalProduce.freshness, Ingredient.name)
            .options(contains_eager(SeasonalProduce.ingredient))
        )
    )


def month_of_week(week_start: date) -> int:
    """The month most days of the 7-day week from `week_start` fall in: its Seasonal Produce.

    A month boundary can split a week only once, so the middle (4th) day is always on the side
    with at least four days.
    """
    return (week_start + timedelta(days=3)).month
