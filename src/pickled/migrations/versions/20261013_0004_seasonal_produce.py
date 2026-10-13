"""Seasonal Produce: seasonal_produce

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

freshness = postgresql.ENUM("fresh", "stored", name="freshness", create_type=False)


def upgrade() -> None:
    freshness.create(op.get_bind())
    op.create_table(
        "seasonal_produce",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("ingredient_id", sa.BigInteger(), nullable=False),
        sa.Column("month", sa.SmallInteger(), nullable=False),
        sa.Column("freshness", freshness, nullable=False),
        sa.CheckConstraint("month BETWEEN 1 AND 12", name=op.f("ck_seasonal_produce_month")),
        sa.ForeignKeyConstraint(
            ["ingredient_id"],
            ["ingredient.id"],
            name=op.f("fk_seasonal_produce_ingredient_id_ingredient"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_seasonal_produce")),
        sa.UniqueConstraint(
            "ingredient_id", "month", name=op.f("uq_seasonal_produce_ingredient_id")
        ),
    )


def downgrade() -> None:
    op.drop_table("seasonal_produce")
    freshness.drop(op.get_bind())
