"""Regular prices: product_miss, and the Checkjebon copy of Jumbo's prices

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

store = postgresql.ENUM("ah", "jumbo", name="store", create_type=False)


def upgrade() -> None:
    op.create_table(
        "product_miss",
        sa.Column("ingredient_id", sa.BigInteger(), nullable=False),
        sa.Column("store", store, nullable=False),
        sa.Column("asked_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["ingredient_id"],
            ["ingredient.id"],
            name=op.f("fk_product_miss_ingredient_id_ingredient"),
        ),
        sa.PrimaryKeyConstraint("ingredient_id", "store", name=op.f("pk_product_miss")),
    )

    op.create_table(
        "checkjebon_product",
        sa.Column("sku", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("price_cents", sa.BigInteger(), nullable=False),
        sa.Column("size", sa.String(), nullable=True),
        sa.Column("url", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("sku", name=op.f("pk_checkjebon_product")),
    )
    # For the trigram shortlist of Jumbo products by name.
    op.create_index(
        "ix_checkjebon_product_name_trgm",
        "checkjebon_product",
        [sa.text("lower(name) gin_trgm_ops")],
        postgresql_using="gin",
    )

    op.create_table(
        "checkjebon_state",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("product_count", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("id = 1", name=op.f("ck_checkjebon_state_single_row")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_checkjebon_state")),
    )


def downgrade() -> None:
    op.drop_table("checkjebon_state")
    op.drop_index("ix_checkjebon_product_name_trgm", table_name="checkjebon_product")
    op.drop_table("checkjebon_product")
    op.drop_table("product_miss")
