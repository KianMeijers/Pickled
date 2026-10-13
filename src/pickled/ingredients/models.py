from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import ForeignKey, Index, Text, func, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pickled.db import Base, IdPk, pg_enum
from pickled.stores.store import STORE_TYPE, Store


class Aisle(StrEnum):
    """Where an Ingredient sits in the shop; the Shopping List is grouped by it."""

    GROENTE_FRUIT = "groente_fruit"
    VLEES_VIS_VEGA = "vlees_vis_vega"
    ZUIVEL_EIEREN = "zuivel_eieren"
    BROOD = "brood"
    VOORRAAD = "voorraad"
    DIEPVRIES = "diepvries"
    DRANKEN = "dranken"
    OVERIG = "overig"


class PriceSource(StrEnum):
    DEAL = "deal"
    AH_SEARCH = "ah_search"
    CHECKJEBON = "checkjebon"


class Ingredient(Base):
    __tablename__ = "ingredient"
    __table_args__ = (
        # Two Ingredients can't share a name once case, spaces and hyphens are ignored.
        Index("uq_ingredient_key", func.ingredient_key(text("name")), unique=True),
    )

    id: Mapped[IdPk]
    name: Mapped[str]
    aliases: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    aisle: Mapped[Aisle] = mapped_column(pg_enum(Aisle, "aisle"))
    pantry: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    grams_per_piece: Mapped[Decimal | None]
    keeps_days: Mapped[int | None]

    products: Mapped[list[Product]] = relationship(back_populates="ingredient")


class Product(Base):
    """Something a store sells for an Ingredient. A replaced choice is kept for its history."""

    __tablename__ = "product"
    __table_args__ = (
        Index(
            "uq_product_chosen",
            "ingredient_id",
            "store",
            unique=True,
            postgresql_where=text("replaced_at IS NULL"),
        ),
    )

    id: Mapped[IdPk]
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredient.id"), index=True)
    store: Mapped[Store] = mapped_column(STORE_TYPE)
    sku: Mapped[str]
    name: Mapped[str]
    pack_size: Mapped[str | None]
    url: Mapped[str | None]
    chosen_at: Mapped[datetime]
    replaced_at: Mapped[datetime | None]

    ingredient: Mapped[Ingredient] = relationship(back_populates="products")
    price_observations: Mapped[list[PriceObservation]] = relationship(
        back_populates="product", order_by="PriceObservation.observed_at"
    )


class PriceObservation(Base):
    __tablename__ = "price_observation"

    id: Mapped[IdPk]
    product_id: Mapped[int] = mapped_column(ForeignKey("product.id"), index=True)
    price_cents: Mapped[int]
    source: Mapped[PriceSource] = mapped_column(pg_enum(PriceSource, "price_source"))
    observed_at: Mapped[datetime]

    product: Mapped[Product] = relationship(back_populates="price_observations")


class ProductMiss(Base):
    """A time the match model found no Product for the Ingredient at the store. It isn't asked
    again until the latest of these is a few weeks old."""

    __tablename__ = "product_miss"
    __table_args__ = (Index("ix_product_miss_ingredient_id_store", "ingredient_id", "store"),)

    id: Mapped[IdPk]
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredient.id"))
    store: Mapped[Store] = mapped_column(STORE_TYPE)
    asked_at: Mapped[datetime]


class CheckjebonProduct(Base):
    """One Jumbo product in our copy of Checkjebon's data.

    The copy is replaced whenever Checkjebon's data changes; `price_observation` keeps the
    history of the prices we used.
    """

    __tablename__ = "checkjebon_product"
    __table_args__ = (
        Index(
            "ix_checkjebon_product_name_trgm",
            func.lower(text("name")),
            postgresql_using="gin",
            postgresql_ops={"lower(name)": "gin_trgm_ops"},
        ),
    )

    id: Mapped[IdPk]
    sku: Mapped[str] = mapped_column(unique=True)
    name: Mapped[str]
    price_cents: Mapped[int]
    size: Mapped[str | None]
    url: Mapped[str]


class CheckjebonCheck(Base):
    """One `refresh_checkjebon` run that read Checkjebon's data: whether it had changed, and
    whether it had gone stale."""

    __tablename__ = "checkjebon_check"

    id: Mapped[IdPk]
    checked_at: Mapped[datetime] = mapped_column(index=True)
    content_hash: Mapped[str]
    changed: Mapped[bool]
    stale: Mapped[bool]
    products: Mapped[int]
    skipped: Mapped[int]
