"""Choosing each store's Product for an Ingredient: the match model picks once from a shortlist.

The pick happens the first time an Ingredient needs a price at a store (ADR 0006). The choice
is stored and reused across Meal Plans.
"""

import logging
from collections.abc import Callable, Generator, Mapping
from contextlib import contextmanager
from datetime import datetime, timedelta

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from pickled.config import Settings
from pickled.ingredients.ah_search import AhSearchPriceSource
from pickled.ingredients.checkjebon import CheckjebonJumboPriceSource
from pickled.ingredients.models import Ingredient, PriceObservation, Product, ProductMiss
from pickled.ingredients.prices import PricesUnavailable, ProductCandidate, RegularPriceSource
from pickled.llm import Role, make_chat_model, runware_model
from pickled.stores import AMSTERDAM, Store, make_client

logger = logging.getLogger(__name__)

# How long a store found to have no Product for an Ingredient isn't asked again.
ASK_AGAIN_AFTER = timedelta(weeks=4)

INSTRUCTIONS = """\
You choose the one supermarket product a meal planner buys for an Ingredient, from a shortlist
of what Albert Heijn or Jumbo in the Netherlands sells.

Choose the product a home cook would buy to cook with that Ingredient:
- Prefer the plain or raw product: whole fillet over sandwich slices, a plain vegetable over a
  ready meal, a mix or a seasoned or marinated version.
- Then prefer the store's own house brand (AH or Jumbo) over other brands.
- Then prefer the best price per kg or per litre.
- Never choose a multipack bundle, a ready meal or a snack unless that is the Ingredient.

When the Household asks for a different product, choose the one that best fits what it asks,
even if the rules above would choose another.

Answer with the product's code from its square brackets. If none of the products is that
Ingredient, or none fits what the Household asks, answer with no code.
"""


class ProductChoice(BaseModel):
    """The product chosen for an Ingredient, or none."""

    sku: str | None = Field(description="The chosen product's code, or null if none fits")
    reason: str = Field(description="In a few words, why")


class ProductPicker:
    """Picks Products with the match model from each store's `RegularPriceSource` shortlist."""

    def __init__(
        self,
        sources: Mapping[Store, RegularPriceSource],
        model: BaseChatModel,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(AMSTERDAM),
    ):
        self.sources = sources
        self.model = model
        self.clock = clock

    def chosen(self, session: Session, ingredient: Ingredient, store: Store) -> Product | None:
        """The Product chosen for `ingredient` at `store`, picked now if it has none yet."""
        product = _current_product(session, ingredient, store)
        if product is not None or self._missed_recently(session, ingredient, store):
            return product
        return self._pick(session, ingredient, store)

    def set_product(
        self, session: Session, ingredient: Ingredient, store: Store, hint: str
    ) -> Product | None:
        """Choose again for `ingredient` at `store`, as `hint` asks; None keeps the choice."""
        return self._pick(
            session,
            ingredient,
            store,
            current=_current_product(session, ingredient, store),
            hint=hint,
        )

    def refresh(self, session: Session, product: Product) -> None:
        """Observe `product`'s current price if its last one is older than its source allows.

        If the source can't say, or no longer sells it, the last price is kept.
        """
        now = self.clock()
        last = session.scalar(
            select(func.max(PriceObservation.observed_at)).where(
                PriceObservation.product_id == product.id
            )
        )
        source = self.sources[product.store]
        if last is not None and now - last <= source.refresh_after:
            return
        try:
            current = source.current(session, product.sku)
        except PricesUnavailable as error:
            logger.warning("No fresh price for %s at %s: %s", product.name, product.store, error)
            return
        if current is None:
            logger.warning("%s at %s is no longer listed", product.name, product.store)
            return
        product.price_observations.append(
            PriceObservation(
                price_cents=current.price_cents, source=source.price_source, observed_at=now
            )
        )
        session.flush()

    def _missed_recently(self, session: Session, ingredient: Ingredient, store: Store) -> bool:
        asked_at = session.scalar(
            select(func.max(ProductMiss.asked_at)).where(
                ProductMiss.ingredient_id == ingredient.id, ProductMiss.store == store
            )
        )
        return asked_at is not None and self.clock() - asked_at < ASK_AGAIN_AFTER

    def _pick(
        self,
        session: Session,
        ingredient: Ingredient,
        store: Store,
        *,
        current: Product | None = None,
        hint: str | None = None,
    ) -> Product | None:
        """Pick a Product from the shortlist, replacing `current`. None if nothing fits.

        A store that sells nothing for `ingredient` isn't asked again for a while, unless a
        `hint` asks for something specific.
        """
        source = self.sources[store]
        now = self.clock()
        try:
            shortlist = source.shortlist(session, ingredient.name)
        except PricesUnavailable as error:
            logger.warning("pick_product %s at %s: no shortlist: %s", ingredient.name, store, error)
            return None
        candidates = {c.sku: c for c in shortlist}
        choice = None
        if candidates:
            choice = self.model.with_structured_output(ProductChoice).invoke(
                _messages(ingredient, store, list(candidates.values()), current, hint)
            )
            assert isinstance(choice, ProductChoice)
        if choice is None or choice.sku is None:
            logger.info("pick_product %s at %s: no Product", ingredient.name, store)
            if current is None:
                session.add(ProductMiss(ingredient_id=ingredient.id, store=store, asked_at=now))
            return None
        candidate = candidates.get(choice.sku)
        if candidate is None:
            logger.warning("pick_product: the model chose %r, which it wasn't sent", choice.sku)
            return None
        if current is not None:
            if current.sku == candidate.sku:
                return current
            current.replaced_at = now
            session.flush()
        product = Product(
            ingredient_id=ingredient.id,
            store=store,
            sku=candidate.sku,
            name=candidate.name,
            pack_size=candidate.pack_size,
            url=candidate.url,
            chosen_at=now,
        )
        product.price_observations.append(
            PriceObservation(
                price_cents=candidate.price_cents, source=source.price_source, observed_at=now
            )
        )
        session.add(product)
        session.flush()
        logger.info(
            "pick_product %s at %s: %s (%s)", ingredient.name, store, candidate.name, choice.reason
        )
        return product


def set_product(
    session: Session, ingredient: Ingredient, store: Store, hint: str, *, picker: ProductPicker
) -> Product | None:
    """Correct the Product chosen for `ingredient` at `store`, as the Household's `hint` asks.

    Returns the newly chosen Product, or None if nothing on the shortlist fits the hint, in
    which case the choice stays as it was.
    """
    return picker.set_product(session, ingredient, store, hint)


def _current_product(session: Session, ingredient: Ingredient, store: Store) -> Product | None:
    return session.scalars(
        select(Product).where(
            Product.ingredient_id == ingredient.id,
            Product.store == store,
            Product.replaced_at.is_(None),
        )
    ).first()


def _messages(
    ingredient: Ingredient,
    store: Store,
    candidates: list[ProductCandidate],
    current: Product | None,
    hint: str | None,
) -> list:
    lines = [f"Ingredient: {ingredient.name}", f"Store: {store}"]
    if current is not None:
        lines.append(f"Currently chosen: [{current.sku}] {current.name}")
    if hint is not None:
        lines.append(f"The Household asks for a different product: {hint}")
    lines += ["", "Products:", *(_describe(candidate) for candidate in candidates)]
    return [SystemMessage(content=INSTRUCTIONS), HumanMessage(content="\n".join(lines))]


def _describe(candidate: ProductCandidate) -> str:
    parts = [f"[{candidate.sku}] {candidate.name}", f"€{candidate.price_cents / 100:.2f}"]
    if candidate.pack_size:
        parts.append(candidate.pack_size)
    return " | ".join(parts)


@contextmanager
def open_product_picker(
    sessions: sessionmaker[Session],
    *,
    build: Callable[[str, Settings], BaseChatModel] = runware_model,
) -> Generator[ProductPicker]:
    """The app's `ProductPicker`: AH search through a counted client, our Checkjebon copy for
    Jumbo, and the match model in its `pick_product` role. `build` makes the model, so tests
    can pass a fake one."""
    model = make_chat_model(Role.PICK_PRODUCT, sessions=sessions, build=build)
    with make_client(Store.AH, sessions) as client:
        sources = {Store.AH: AhSearchPriceSource(client), Store.JUMBO: CheckjebonJumboPriceSource()}
        yield ProductPicker(sources, model)
