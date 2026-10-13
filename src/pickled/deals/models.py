from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pickled.db import Base, IdPk, pg_enum
from pickled.deals.discounts import DiscountKind
from pickled.deals.sources import Channel
from pickled.stores.store import STORE_TYPE, Store


class Deal(Base):
    """A Deal as stored. Never deleted: one the store stops listing gets `withdrawn_at`."""

    __tablename__ = "deal"
    __table_args__ = (UniqueConstraint("store", "source_id", "valid_from"),)

    id: Mapped[IdPk]
    store: Mapped[Store] = mapped_column(STORE_TYPE)
    source_id: Mapped[str]
    valid_from: Mapped[date]
    valid_to: Mapped[date]
    title: Mapped[str]
    description: Mapped[str | None]
    discount_text: Mapped[str]
    discount_kind: Mapped[DiscountKind] = mapped_column(pg_enum(DiscountKind, "discount_kind"))
    discount_percent: Mapped[int | None]
    discount_price_cents: Mapped[int | None]
    discount_n: Mapped[int | None]
    discount_m: Mapped[int | None]
    effective_fraction: Mapped[Decimal | None]
    channel: Mapped[Channel] = mapped_column(pg_enum(Channel, "deal_channel"))
    category: Mapped[str | None]
    price_cents: Mapped[int | None]
    was_price_cents: Mapped[int | None]
    unit_size: Mapped[str | None]
    first_seen_at: Mapped[datetime]
    last_seen_at: Mapped[datetime]
    withdrawn_at: Mapped[datetime | None]

    products: Mapped[list[DealProduct]] = relationship(
        back_populates="deal", order_by="DealProduct.id"
    )


class DealProduct(Base):
    """A product a Deal lists, where the source gives it."""

    __tablename__ = "deal_product"
    __table_args__ = (UniqueConstraint("deal_id", "sku"),)

    id: Mapped[IdPk]
    deal_id: Mapped[int] = mapped_column(ForeignKey("deal.id"))
    sku: Mapped[str]
    title: Mapped[str]
    price_cents: Mapped[int | None]
    was_price_cents: Mapped[int | None]
    unit_size: Mapped[str | None]

    deal: Mapped[Deal] = relationship(back_populates="products")


class DealFetch(Base):
    """One stored fetch: its raw payload and counts. Only the last few per store are kept."""

    __tablename__ = "deal_fetch"

    id: Mapped[IdPk]
    store: Mapped[Store] = mapped_column(STORE_TYPE, index=True)
    fetched_at: Mapped[datetime]
    valid_on: Mapped[date]
    raw: Mapped[Any] = mapped_column(JSONB)
    parsed_count: Mapped[int]
    skipped_count: Mapped[int]
    withdrawn_count: Mapped[int]
