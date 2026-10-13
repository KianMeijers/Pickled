"""Deals: deal, deal_product and deal_fetch

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

store = postgresql.ENUM("ah", "jumbo", name="store", create_type=False)
discount_kind = postgresql.ENUM(
    "percent_off",
    "fixed_price",
    "n_for_price",
    "buy_n_get_m_free",
    "nth_half_price",
    "other",
    name="discount_kind",
    create_type=False,
)
deal_channel = postgresql.ENUM("in_store", "online", "both", name="deal_channel", create_type=False)


def upgrade() -> None:
    for enum in (discount_kind, deal_channel):
        enum.create(op.get_bind())

    op.create_table(
        "deal",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("store", store, nullable=False),
        sa.Column("source_id", sa.String(), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("discount_text", sa.String(), nullable=False),
        sa.Column("discount_kind", discount_kind, nullable=False),
        sa.Column("discount_percent", sa.BigInteger(), nullable=True),
        sa.Column("discount_price_cents", sa.BigInteger(), nullable=True),
        sa.Column("discount_n", sa.BigInteger(), nullable=True),
        sa.Column("discount_m", sa.BigInteger(), nullable=True),
        sa.Column("effective_fraction", sa.Numeric(), nullable=True),
        sa.Column("channel", deal_channel, nullable=False),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("price_cents", sa.BigInteger(), nullable=True),
        sa.Column("was_price_cents", sa.BigInteger(), nullable=True),
        sa.Column("unit_size", sa.String(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_deal")),
        sa.UniqueConstraint("store", "source_id", "valid_from", name=op.f("uq_deal_store")),
    )
    op.create_table(
        "deal_fetch",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("store", store, nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_on", sa.Date(), nullable=False),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("parsed_count", sa.BigInteger(), nullable=False),
        sa.Column("skipped_count", sa.BigInteger(), nullable=False),
        sa.Column("withdrawn_count", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_deal_fetch")),
    )
    op.create_index(op.f("ix_deal_fetch_store"), "deal_fetch", ["store"], unique=False)
    op.create_table(
        "deal_product",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("deal_id", sa.BigInteger(), nullable=False),
        sa.Column("sku", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("price_cents", sa.BigInteger(), nullable=True),
        sa.Column("was_price_cents", sa.BigInteger(), nullable=True),
        sa.Column("unit_size", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["deal_id"], ["deal.id"], name=op.f("fk_deal_product_deal_id_deal")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_deal_product")),
        sa.UniqueConstraint("deal_id", "sku", name=op.f("uq_deal_product_deal_id")),
    )


def downgrade() -> None:
    op.drop_table("deal_product")
    op.drop_index(op.f("ix_deal_fetch_store"), table_name="deal_fetch")
    op.drop_table("deal_fetch")
    op.drop_table("deal")
    for enum in (deal_channel, discount_kind):
        enum.drop(op.get_bind())
