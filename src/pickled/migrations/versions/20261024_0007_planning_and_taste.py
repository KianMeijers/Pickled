"""Planning and taste: Meal Plans, Meals, Recipes, the Shopping List, the Household, Taste
notes and Food Goals

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
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
food_goal_kind = postgresql.ENUM(
    "kcal_per_day",
    "protein_g_per_day",
    "vegetarian_days_per_week",
    "budget_cents_per_week",
    "other",
    name="food_goal_kind",
    create_type=False,
)
taste_note_author = postgresql.ENUM("agent", "user", name="taste_note_author", create_type=False)
plan_status = postgresql.ENUM("draft", "accepted", name="plan_status", create_type=False)
recipe_unit = postgresql.ENUM(
    "g", "ml", "piece", "tbsp", "tsp", "pinch", "to_taste", name="recipe_unit", create_type=False
)
shopping_item_source = postgresql.ENUM(
    "recipe", "manual", name="shopping_item_source", create_type=False
)
NEW_ENUMS = (food_goal_kind, taste_note_author, plan_status, recipe_unit, shopping_item_source)


def upgrade() -> None:
    for enum in NEW_ENUMS:
        enum.create(op.get_bind())

    op.create_table(
        "food_goal",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column(
            "kind",
            food_goal_kind,
            nullable=False,
        ),
        sa.Column("min", sa.Numeric(), nullable=True),
        sa.Column("max", sa.Numeric(), nullable=True),
        sa.Column("text", sa.String(), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("set_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind <> 'other' OR text IS NOT NULL", name=op.f("ck_food_goal_other_has_text")
        ),
        sa.CheckConstraint(
            "min IS NOT NULL OR max IS NOT NULL OR kind = 'other'",
            name=op.f("ck_food_goal_has_bound"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_food_goal")),
    )
    op.create_table(
        "household",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("people", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.CheckConstraint("people > 0", name=op.f("ck_household_people_positive")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_household")),
    )
    op.create_index("uq_household_single", "household", [sa.literal_column("(true)")], unique=True)
    op.create_table(
        "meal_plan",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("status", plan_status, nullable=False),
        sa.Column("store", store, nullable=True),
        sa.Column("people", sa.BigInteger(), nullable=False),
        sa.Column("est_cost_cents", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("drafted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(status = 'accepted') = (accepted_at IS NOT NULL)",
            name=op.f("ck_meal_plan_accepted_when_accepted"),
        ),
        sa.CheckConstraint(
            "extract(isodow FROM week_start) = 6", name=op.f("ck_meal_plan_week_starts_saturday")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_meal_plan")),
        sa.UniqueConstraint("week_start", name=op.f("uq_meal_plan_week_start")),
    )
    op.create_table(
        "recipe",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("servings", sa.BigInteger(), nullable=False),
        sa.Column("steps", sa.String(), nullable=False),
        sa.Column("tags", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column("kcal", sa.Numeric(), nullable=False),
        sa.Column("protein_g", sa.Numeric(), nullable=False),
        sa.Column("carbs_g", sa.Numeric(), nullable=False),
        sa.Column("fat_g", sa.Numeric(), nullable=False),
        sa.Column("derived_from_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("servings > 0", name=op.f("ck_recipe_servings_positive")),
        sa.ForeignKeyConstraint(
            ["derived_from_id"], ["recipe.id"], name=op.f("fk_recipe_derived_from_id_recipe")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recipe")),
    )
    op.create_table(
        "taste_note",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column("author", taste_note_author, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("char_length(text) <= 200", name=op.f("ck_taste_note_text_short")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_taste_note")),
    )
    op.create_table(
        "meal",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("meal_plan_id", sa.BigInteger(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("recipe_id", sa.BigInteger(), nullable=True),
        sa.Column("leftovers_of_id", sa.BigInteger(), nullable=True),
        sa.Column("servings", sa.BigInteger(), nullable=True),
        sa.CheckConstraint(
            "(recipe_id IS NULL OR leftovers_of_id IS NULL)"
            " AND ((recipe_id IS NULL AND leftovers_of_id IS NULL) = (servings IS NULL))"
            " AND servings > 0",
            name=op.f("ck_meal_filled_or_empty"),
        ),
        sa.ForeignKeyConstraint(
            ["leftovers_of_id"], ["meal.id"], name=op.f("fk_meal_leftovers_of_id_meal")
        ),
        sa.ForeignKeyConstraint(
            ["meal_plan_id"], ["meal_plan.id"], name=op.f("fk_meal_meal_plan_id_meal_plan")
        ),
        sa.ForeignKeyConstraint(
            ["recipe_id"], ["recipe.id"], name=op.f("fk_meal_recipe_id_recipe")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_meal")),
        sa.UniqueConstraint("meal_plan_id", "date", name=op.f("uq_meal_meal_plan_id")),
    )
    op.create_index(op.f("ix_meal_recipe_id"), "meal", ["recipe_id"])
    op.create_table(
        "recipe_ingredient",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("recipe_id", sa.BigInteger(), nullable=False),
        sa.Column("ingredient_id", sa.BigInteger(), nullable=False),
        sa.Column("quantity", sa.Numeric(), nullable=True),
        sa.Column(
            "unit",
            recipe_unit,
            nullable=False,
        ),
        sa.Column("note", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["ingredient_id"],
            ["ingredient.id"],
            name=op.f("fk_recipe_ingredient_ingredient_id_ingredient"),
        ),
        sa.ForeignKeyConstraint(
            ["recipe_id"], ["recipe.id"], name=op.f("fk_recipe_ingredient_recipe_id_recipe")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recipe_ingredient")),
    )
    op.create_index(
        op.f("ix_recipe_ingredient_ingredient_id"),
        "recipe_ingredient",
        ["ingredient_id"],
    )
    op.create_index(op.f("ix_recipe_ingredient_recipe_id"), "recipe_ingredient", ["recipe_id"])
    op.create_table(
        "shopping_list_item",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("meal_plan_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("ingredient_id", sa.BigInteger(), nullable=True),
        sa.Column("quantity", sa.Numeric(), nullable=True),
        sa.Column("unit", sa.String(), nullable=True),
        sa.Column("source", shopping_item_source, nullable=False),
        sa.Column("pantry", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("deal_id", sa.BigInteger(), nullable=True),
        sa.Column("store", store, nullable=True),
        sa.Column(
            "aisle",
            aisle,
            nullable=False,
        ),
        sa.Column("packs", sa.BigInteger(), nullable=True),
        sa.Column("est_price_cents", sa.BigInteger(), nullable=True),
        sa.Column("rough", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("checked", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.ForeignKeyConstraint(
            ["deal_id"], ["deal.id"], name=op.f("fk_shopping_list_item_deal_id_deal")
        ),
        sa.ForeignKeyConstraint(
            ["ingredient_id"],
            ["ingredient.id"],
            name=op.f("fk_shopping_list_item_ingredient_id_ingredient"),
        ),
        sa.ForeignKeyConstraint(
            ["meal_plan_id"],
            ["meal_plan.id"],
            name=op.f("fk_shopping_list_item_meal_plan_id_meal_plan"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shopping_list_item")),
    )
    op.create_index(
        op.f("ix_shopping_list_item_meal_plan_id"),
        "shopping_list_item",
        ["meal_plan_id"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_shopping_list_item_meal_plan_id"), table_name="shopping_list_item")
    op.drop_table("shopping_list_item")
    op.drop_index(op.f("ix_recipe_ingredient_recipe_id"), table_name="recipe_ingredient")
    op.drop_index(op.f("ix_recipe_ingredient_ingredient_id"), table_name="recipe_ingredient")
    op.drop_table("recipe_ingredient")
    op.drop_index(op.f("ix_meal_recipe_id"), table_name="meal")
    op.drop_table("meal")
    op.drop_table("taste_note")
    op.drop_table("recipe")
    op.drop_table("meal_plan")
    op.drop_index("uq_household_single", table_name="household")
    op.drop_table("household")
    op.drop_table("food_goal")
    for enum in reversed(NEW_ENUMS):
        enum.drop(op.get_bind())
