"""Tagging Deals: the match model links each Deal to Ingredients or marks it non-food (ADR 0006).

Deals go to the model in batches. Each batch is saved as soon as its answer comes back, so a run
that fails part-way keeps what it tagged, and the next run picks up the rest. Every name the
model gives goes through the Ingredient lookup, which matches the catalogue or adds to it.
"""

import logging
from datetime import date, datetime
from decimal import Decimal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field
from sqlalchemy import exists, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, selectinload, sessionmaker

from pickled.deals.models import Deal, DealIngredient
from pickled.deals.sources import Channel
from pickled.deals.storing import valid_on_conditions
from pickled.ingredients import (
    Aisle,
    Ingredient,
    NewIngredient,
    ingredient_names,
    resolve_ingredient,
)
from pickled.stores import Store

logger = logging.getLogger(__name__)

BATCH_SIZE = 50
PRODUCTS_SHOWN = 5

INSTRUCTIONS = """\
You tag supermarket Deals from Albert Heijn and Jumbo in the Netherlands for a meal planner.

For each Deal, say which Ingredients it sells: kinds of food a recipe would name, such as
"kipfilet", "rode kool" or "volle melk". Name each Ingredient in Dutch, in lowercase and in the
singular unless the plural is how it is always named. Leave out brands, pack sizes and
quality labels ("AH", "biologisch", "300 g").

- When the Deal sells an Ingredient that is in the catalogue below, use the catalogue's name.
- A Deal on a group of products ("Alle AH kip") can sell several Ingredients; list each one.
- A Deal on a ready meal, a snack or a drink sells that as one Ingredient ("pizza", "chips").
- A Deal on something that isn't food or drink (detergent, cosmetics, flowers, pet food) is
  non-food: set non_food and list no Ingredients.
- For an Ingredient that is not in the catalogue, also give its aisle, whether it is a pantry
  staple that keeps for months (oil, salt, spices, rice), roughly how many days it keeps after
  shopping, and, for something sold per piece, roughly how many grams one piece weighs.

Answer for every Deal, using the number in its square brackets.

The catalogue of Ingredients:
"""


class TaggedIngredient(BaseModel):
    name: str = Field(description="The Ingredient's Dutch name, lowercase")
    aisle: Aisle
    pantry: bool = Field(False, description="A staple that keeps for months")
    keeps_days: int | None = Field(None, description="Days it keeps after shopping")
    grams_per_piece: Decimal | None = Field(None, description="Grams per piece, if sold per piece")


class DealTag(BaseModel):
    deal: int = Field(description="The Deal's number, from its square brackets")
    non_food: bool
    ingredients: list[TaggedIngredient] = Field(default_factory=list)


class DealTags(BaseModel):
    """The Ingredients each Deal sells, or that it isn't food."""

    deals: list[DealTag]


def tag_deals(
    sessions: sessionmaker[Session],
    store: Store,
    model: BaseChatModel,
    *,
    on: date,
    now: datetime,
    batch_size: int = BATCH_SIZE,
) -> int:
    """Tag `store`'s untagged Deals that are still valid on or after `on`; return how many.

    A Deal the model leaves out stays untagged, and is asked about again on the next run.
    """
    tagger = model.with_structured_output(DealTags)
    asked: set[int] = set()
    tagged = 0
    while True:
        with sessions() as session:
            batch = _untagged(session, store, on, leaving_out=asked, limit=batch_size)
            if not batch:
                break
            messages = _messages(batch, ingredient_names(session))
        asked.update(batch)
        answer = tagger.invoke(messages)
        with sessions.begin() as session:
            tagged += _save(session, answer, batch=set(batch), now=now)
    if tagged < len(asked):
        logger.warning("tag_deals %s: %d Deals were left untagged", store, len(asked) - tagged)
    logger.info("tag_deals %s: %d Deals tagged", store, tagged)
    return tagged


def deals_by_ingredient(
    session: Session,
    on: date,
    store: Store | None = None,
    channel: Channel = Channel.IN_STORE,
) -> dict[Ingredient, list[Deal]]:
    """The Deals valid on `on` in `channel` for each Ingredient, in order of Ingredient name."""
    rows = session.execute(
        select(Ingredient, Deal)
        .join(DealIngredient, DealIngredient.ingredient_id == Ingredient.id)
        .join(Deal, Deal.id == DealIngredient.deal_id)
        .where(*valid_on_conditions(on, store, channel))
        .order_by(Ingredient.name, Deal.store, Deal.id)
    )
    found: dict[Ingredient, list[Deal]] = {}
    for ingredient, deal in rows:
        found.setdefault(ingredient, []).append(deal)
    return found


def _untagged(
    session: Session, store: Store, on: date, *, leaving_out: set[int], limit: int
) -> dict[int, Deal]:
    query = (
        select(Deal)
        .options(selectinload(Deal.products))
        .where(
            Deal.store == store,
            Deal.valid_to >= on,
            Deal.withdrawn_at.is_(None),
            ~exists().where(DealIngredient.deal_id == Deal.id),
            Deal.id.not_in(leaving_out),
        )
        .order_by(Deal.id)
        .limit(limit)
    )
    return {deal.id: deal for deal in session.scalars(query)}


def _messages(batch: dict[int, Deal], catalogue: list[str]) -> list:
    # The instructions and catalogue are the same for every batch of a run, so they are cached.
    system = INSTRUCTIONS + ("\n".join(catalogue) or "(empty)")
    return [
        SystemMessage(
            content=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
        ),
        HumanMessage(content="\n".join(_describe(deal) for deal in batch.values())),
    ]


def _describe(deal: Deal) -> str:
    parts = [f"[{deal.id}] {deal.title}"]
    if deal.description:
        parts.append(deal.description)
    if deal.category:
        parts.append(f"category: {deal.category}")
    if deal.unit_size:
        parts.append(f"size: {deal.unit_size}")
    if deal.products:
        titles = [product.title for product in deal.products[:PRODUCTS_SHOWN]]
        parts.append("products: " + "; ".join(titles))
    return " | ".join(parts)


def _save(session: Session, answer: DealTags, *, batch: set[int], now: datetime) -> int:
    tagged = set()
    for tag in answer.deals:
        if tag.deal not in batch:
            logger.warning("tag_deals: the model tagged Deal %s, which it wasn't sent", tag.deal)
            continue
        if tag.non_food:
            ingredient_ids: list[int | None] = [None]
        else:
            ingredient_ids = [_resolve(session, ingredient).id for ingredient in tag.ingredients]
        for ingredient_id in ingredient_ids:
            session.execute(
                insert(DealIngredient)
                .values(deal_id=tag.deal, ingredient_id=ingredient_id, tagged_at=now)
                .on_conflict_do_nothing()
            )
        if ingredient_ids:
            tagged.add(tag.deal)
    return len(tagged)


def _resolve(session: Session, ingredient: TaggedIngredient) -> Ingredient:
    return resolve_ingredient(
        session,
        ingredient.name,
        NewIngredient(
            aisle=ingredient.aisle,
            pantry=ingredient.pantry,
            grams_per_piece=ingredient.grams_per_piece,
            keeps_days=ingredient.keeps_days,
        ),
    )
