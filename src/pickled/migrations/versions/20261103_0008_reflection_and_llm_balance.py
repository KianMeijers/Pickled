"""Reflection and the Runware balance: meal_plan.reflected_at and llm_balance

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("meal_plan", sa.Column("reflected_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "llm_balance",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("balance_usd", sa.Numeric(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_balance")),
    )
    op.create_index(op.f("ix_llm_balance_checked_at"), "llm_balance", ["checked_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_llm_balance_checked_at"), table_name="llm_balance")
    op.drop_table("llm_balance")
    op.drop_column("meal_plan", "reflected_at")
