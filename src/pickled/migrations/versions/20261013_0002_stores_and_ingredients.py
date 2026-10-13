"""Stores and the Ingredient catalogue

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

store = postgresql.ENUM("ah", "jumbo", name="store", create_type=False)
aisle = postgresql.ENUM(
    "groente_fruit",
    "vlees_vis_vega",
    "zuivel_eieren",
    "brood",
    "voorraad",
    "diepvries",
    "dranken",
    "overig",
    name="aisle",
    create_type=False,
)
price_source = postgresql.ENUM(
    "deal", "ah_search", "checkjebon", name="price_source", create_type=False
)


def upgrade() -> None:
    for enum in (store, aisle, price_source):
        enum.create(op.get_bind())

    # The normalised form of an Ingredient name: lowercase, without whitespace or hyphens.
    op.execute(
        """
        CREATE FUNCTION ingredient_key(name text) RETURNS text
        LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
        RETURN regexp_replace(lower(name), '[[:space:]-]+', '', 'g')
        """
    )

    op.create_table(
        "store_request",
        sa.Column("store", store, nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("count", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("store", "week_start", name=op.f("pk_store_request")),
    )

    op.create_table(
        "ingredient",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("aliases", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column("aisle", aisle, nullable=False),
        sa.Column("pantry", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("grams_per_piece", sa.Numeric(), nullable=True),
        sa.Column("keeps_days", sa.BigInteger(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ingredient")),
    )
    op.create_index(
        "uq_ingredient_key", "ingredient", [sa.text("ingredient_key(name)")], unique=True
    )

    op.create_table(
        "product",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("ingredient_id", sa.BigInteger(), nullable=False),
        sa.Column("store", store, nullable=False),
        sa.Column("sku", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("pack_size", sa.String(), nullable=True),
        sa.Column("url", sa.String(), nullable=True),
        sa.Column("chosen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("replaced_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["ingredient_id"],
            ["ingredient.id"],
            name=op.f("fk_product_ingredient_id_ingredient"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product")),
    )
    op.create_index(op.f("ix_product_ingredient_id"), "product", ["ingredient_id"])
    # At most one chosen Product per (Ingredient, store); replaced ones stay for their history.
    op.create_index(
        "uq_product_chosen",
        "product",
        ["ingredient_id", "store"],
        unique=True,
        postgresql_where=sa.text("replaced_at IS NULL"),
    )

    op.create_table(
        "price_observation",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("price_cents", sa.BigInteger(), nullable=False),
        sa.Column("source", price_source, nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["product.id"],
            name=op.f("fk_price_observation_product_id_product"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_price_observation")),
    )
    op.create_index(op.f("ix_price_observation_product_id"), "price_observation", ["product_id"])


def downgrade() -> None:
    op.drop_table("price_observation")
    op.drop_table("product")
    op.drop_table("ingredient")
    op.drop_table("store_request")
    op.execute("DROP FUNCTION ingredient_key(text)")
    for enum in (price_source, aisle, store):
        enum.drop(op.get_bind())
