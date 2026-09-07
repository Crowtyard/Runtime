# -*- coding: utf-8 -*-
"""m2b_resource_economy

Revision ID: b7d2f4e9c1a5
Revises: a7b3e9f1c5d2

- resource_nodes 扩展：resource_profile_ref / settlement_relation /
  remaining_reserve / extraction_capacity / extraction_carry /
  last_extracted_minor / engine_version / state_version / updated_blessed_tick
- 新表：resource_profiles / resource_stocks / production_recipes /
  production_state / economic_pressure_state
- 权威数量一律 BigInteger minor units（SQLite INTEGER 64-bit / PostgreSQL
  BIGINT）；无 float 权威列。只 ADD，不改旧 migration。
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "b7d2f4e9c1a5"
down_revision = "a7b3e9f1c5d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("resource_nodes",
                  sa.Column("resource_profile_ref", sa.String(64), nullable=True))
    op.add_column("resource_nodes",
                  sa.Column("settlement_relation", sa.String(64), nullable=True))
    op.add_column("resource_nodes",
                  sa.Column("remaining_reserve", sa.BigInteger(), nullable=True))
    op.add_column("resource_nodes",
                  sa.Column("extraction_capacity", sa.BigInteger(), nullable=True))
    op.add_column("resource_nodes",
                  sa.Column("extraction_carry", sa.BigInteger(), nullable=False,
                            server_default="0"))
    op.add_column("resource_nodes",
                  sa.Column("last_extracted_minor", sa.BigInteger(), nullable=False,
                            server_default="0"))
    op.add_column("resource_nodes",
                  sa.Column("engine_version", sa.String(32), nullable=True))
    op.add_column("resource_nodes",
                  sa.Column("state_version", sa.BigInteger(), nullable=False,
                            server_default="0"))
    op.add_column("resource_nodes",
                  sa.Column("updated_blessed_tick", sa.BigInteger(), nullable=True))

    op.create_table(
        "resource_profiles",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("world_id", sa.String(32), nullable=False, index=True),
        sa.Column("resource_id", sa.String(32), nullable=False),
        sa.Column("unit", sa.String(16), nullable=False, server_default="unit"),
        sa.Column("quantity_scale", sa.BigInteger(), nullable=False,
                  server_default="1000000"),
        sa.Column("renewability", sa.String(16), nullable=False,
                  server_default="FINITE"),
        sa.Column("extractability", sa.String(16), nullable=True),
        sa.Column("consumption_category", sa.String(32), nullable=True),
        sa.Column("production_usability", sa.String(32), nullable=True),
        sa.Column("semantic_version", sa.String(32), nullable=True),
        sa.UniqueConstraint("world_id", "resource_id",
                            name="uq_resource_profiles_world_resource"),
    )

    op.create_table(
        "resource_stocks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("world_id", sa.String(32), nullable=False, index=True),
        sa.Column("settlement_ref", sa.String(64), nullable=False),
        sa.Column("resource_profile_ref", sa.String(64), nullable=False),
        sa.Column("quantity", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("consumption_carry", sa.BigInteger(), nullable=False,
                  server_default="0"),
        sa.Column("cum_extracted_minor", sa.BigInteger(), nullable=False,
                  server_default="0"),
        sa.Column("cum_produced_minor", sa.BigInteger(), nullable=False,
                  server_default="0"),
        sa.Column("cum_input_minor", sa.BigInteger(), nullable=False,
                  server_default="0"),
        sa.Column("cum_imported_minor", sa.BigInteger(), nullable=False,
                  server_default="0"),
        sa.Column("cum_exported_minor", sa.BigInteger(), nullable=False,
                  server_default="0"),
        sa.Column("cum_consumed_minor", sa.BigInteger(), nullable=False,
                  server_default="0"),
        sa.Column("cum_lost_minor", sa.BigInteger(), nullable=False,
                  server_default="0"),
        sa.Column("engine_version", sa.String(32), nullable=True),
        sa.Column("updated_blessed_tick", sa.BigInteger(), nullable=True),
        sa.UniqueConstraint("world_id", "settlement_ref", "resource_profile_ref",
                            name="uq_resource_stocks_world_settlement_resource"),
    )

    op.create_table(
        "production_recipes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("world_id", sa.String(32), nullable=False, index=True),
        sa.Column("recipe_id", sa.String(32), nullable=False),
        sa.Column("input_resource_ref", sa.String(64), nullable=True),
        sa.Column("input_qty_minor", sa.BigInteger(), nullable=True),
        sa.Column("output_resource_ref", sa.String(64), nullable=True),
        sa.Column("output_qty_minor", sa.BigInteger(), nullable=True),
        sa.Column("capacity_batches_per_year", sa.BigInteger(), nullable=True),
        sa.Column("labor_per_batch", sa.BigInteger(), nullable=False,
                  server_default="0"),
        sa.Column("loss_num", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("loss_den", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("semantic_version", sa.String(32), nullable=True),
        sa.UniqueConstraint("world_id", "recipe_id",
                            name="uq_production_recipes_world_recipe"),
    )

    op.create_table(
        "production_state",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("world_id", sa.String(32), nullable=False, index=True),
        sa.Column("settlement_ref", sa.String(64), nullable=False),
        sa.Column("recipe_ref", sa.String(32), nullable=False),
        sa.Column("production_carry", sa.BigInteger(), nullable=False,
                  server_default="0"),
        sa.Column("engine_version", sa.String(32), nullable=True),
        sa.Column("updated_blessed_tick", sa.BigInteger(), nullable=True),
        sa.UniqueConstraint("world_id", "settlement_ref", "recipe_ref",
                            name="uq_production_state_world_settlement_recipe"),
    )

    op.create_table(
        "economic_pressure_state",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("world_id", sa.String(32), nullable=False, index=True),
        sa.Column("settlement_ref", sa.String(64), nullable=False),
        sa.Column("resource_profile_ref", sa.String(64), nullable=False),
        sa.Column("demand_minor", sa.BigInteger(), nullable=False,
                  server_default="0"),
        sa.Column("fulfilled_minor", sa.BigInteger(), nullable=False,
                  server_default="0"),
        sa.Column("unmet_minor", sa.BigInteger(), nullable=False,
                  server_default="0"),
        sa.Column("shortage_ratio_num", sa.BigInteger(), nullable=False,
                  server_default="0"),
        sa.Column("shortage_ratio_den", sa.BigInteger(), nullable=False,
                  server_default="1"),
        sa.Column("sustained_shortage_steps", sa.BigInteger(), nullable=False,
                  server_default="0"),
        sa.Column("stress_level", sa.String(16), nullable=False,
                  server_default="NONE"),
        sa.Column("engine_version", sa.String(32), nullable=True),
        sa.Column("updated_blessed_tick", sa.BigInteger(), nullable=True),
        sa.UniqueConstraint(
            "world_id", "settlement_ref", "resource_profile_ref",
            name="uq_economic_pressure_state_world_settlement_resource"),
    )


def downgrade() -> None:
    op.drop_table("economic_pressure_state")
    op.drop_table("production_state")
    op.drop_table("production_recipes")
    op.drop_table("resource_stocks")
    op.drop_table("resource_profiles")
    op.drop_column("resource_nodes", "updated_blessed_tick")
    op.drop_column("resource_nodes", "state_version")
    op.drop_column("resource_nodes", "engine_version")
    op.drop_column("resource_nodes", "last_extracted_minor")
    op.drop_column("resource_nodes", "extraction_carry")
    op.drop_column("resource_nodes", "extraction_capacity")
    op.drop_column("resource_nodes", "remaining_reserve")
    op.drop_column("resource_nodes", "settlement_relation")
    op.drop_column("resource_nodes", "resource_profile_ref")
