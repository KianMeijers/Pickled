"""LLM spend and Deal tags: llm_call and deal_ingredient

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

llm_role = postgresql.ENUM(
    "chat",
    "draft",
    "reflect",
    "tag_deals",
    "pick_product",
    "eval_judge",
    name="llm_role",
    create_type=False,
)


def upgrade() -> None:
    llm_role.create(op.get_bind())
    op.create_table(
        "llm_call",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("called_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("role", llm_role, nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("job", sa.String(), nullable=True),
        sa.Column("meal_plan_id", sa.BigInteger(), nullable=True),
        sa.Column("input_tokens", sa.BigInteger(), nullable=False),
        sa.Column("cache_write_tokens", sa.BigInteger(), nullable=False),
        sa.Column("cache_read_tokens", sa.BigInteger(), nullable=False),
        sa.Column("output_tokens", sa.BigInteger(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_call")),
    )
    op.create_index(op.f("ix_llm_call_called_at"), "llm_call", ["called_at"], unique=False)
    op.create_table(
        "deal_ingredient",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("deal_id", sa.BigInteger(), nullable=False),
        sa.Column("ingredient_id", sa.BigInteger(), nullable=True),
        sa.Column("tagged_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["deal_id"], ["deal.id"], name=op.f("fk_deal_ingredient_deal_id_deal")
        ),
        sa.ForeignKeyConstraint(
            ["ingredient_id"],
            ["ingredient.id"],
            name=op.f("fk_deal_ingredient_ingredient_id_ingredient"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_deal_ingredient")),
        sa.UniqueConstraint(
            "deal_id",
            "ingredient_id",
            name=op.f("uq_deal_ingredient_deal_id"),
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index(
        op.f("ix_deal_ingredient_ingredient_id"), "deal_ingredient", ["ingredient_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_deal_ingredient_ingredient_id"), table_name="deal_ingredient")
    op.drop_table("deal_ingredient")
    op.drop_index(op.f("ix_llm_call_called_at"), table_name="llm_call")
    op.drop_table("llm_call")
    llm_role.drop(op.get_bind())
