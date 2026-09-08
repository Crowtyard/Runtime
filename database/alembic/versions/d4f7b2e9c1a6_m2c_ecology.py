# -*- coding: utf-8 -*-
"""m2c_ecology

Revision ID: d4f7b2e9c1a6
Revises: b7d2f4e9c1a5

- resource_nodes 扩展：reserve_ceiling_minor（可再生储量上限，NULL=非可
  再生/无上限）/ regeneration_carry（亚年再生进位，整数）
- 新表：ecology_zones / ecology_state / ecology_feedback_state
- 生态权威状态一律 BigInteger fixed-point（0..ECOLOGY_STATE_SCALE，
  SQLite INTEGER 64-bit / PostgreSQL BIGINT）；无 float 权威列。
- 只 ADD，不改旧 migration。
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "d4f7b2e9c1a6"
down_revision = "b7d2f4e9c1a5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("resource_nodes",
                  sa.Column("reserve_ceiling_minor", sa.BigInteger(),
                            nullable=True))
    op.add_column("resource_nodes",
                  sa.Column("regeneration_carry", sa.BigInteger(),
                            nullable=False, server_default="0"))

    op.create_table(
        "ecology_zones",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("world_id", sa.String(32), nullable=False, index=True),
        sa.Column("zone_id", sa.String(32), nullable=False),
        sa.Column("region_ref", sa.String(64), nullable=True),
        sa.Column("settlement_relation", sa.String(64), nullable=True),
        sa.Column("profile_ref", sa.String(64), nullable=True),
        sa.Column("semantic_version", sa.String(32), nullable=True),
        sa.UniqueConstraint("world_id", "zone_id",
                            name="uq_ecology_zones_world_zone"),
    )

    op.create_table(
        "ecology_state",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("world_id", sa.String(32), nullable=False, index=True),
        sa.Column("zone_ref", sa.String(32), nullable=False),
        sa.Column("habitat_quality", sa.BigInteger(), nullable=False,
                  server_default="0"),
        sa.Column("regeneration_capacity", sa.BigInteger(), nullable=False,
                  server_default="0"),
        sa.Column("ecological_stress", sa.BigInteger(), nullable=False,
                  server_default="0"),
        sa.Column("population_pressure", sa.BigInteger(), nullable=False,
                  server_default="0"),
        sa.Column("extraction_pressure", sa.BigInteger(), nullable=False,
                  server_default="0"),
        sa.Column("production_pressure", sa.BigInteger(), nullable=False,
                  server_default="0"),
        sa.Column("depletion_pressure", sa.BigInteger(), nullable=False,
                  server_default="0"),
        sa.Column("external_pressure", sa.BigInteger(), nullable=False,
                  server_default="0"),
        sa.Column("degradation_carry", sa.BigInteger(), nullable=False,
                  server_default="0"),
        sa.Column("recovery_carry", sa.BigInteger(), nullable=False,
                  server_default="0"),
        sa.Column("quality_min_seen", sa.BigInteger(), nullable=False,
                  server_default="0"),
        sa.Column("quality_max_seen", sa.BigInteger(), nullable=False,
                  server_default="0"),
        sa.Column("engine_version", sa.String(32), nullable=True),
        sa.Column("updated_blessed_tick", sa.BigInteger(), nullable=True),
        sa.UniqueConstraint("world_id", "zone_ref",
                            name="uq_ecology_state_world_zone"),
    )

    op.create_table(
        "ecology_feedback_state",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("world_id", sa.String(32), nullable=False, index=True),
        sa.Column("zone_ref", sa.String(32), nullable=False),
        sa.Column("regeneration_capacity_minor_per_year", sa.BigInteger(),
                  nullable=False, server_default="0"),
        sa.Column("yield_modifier_num", sa.BigInteger(), nullable=False,
                  server_default="1"),
        sa.Column("yield_modifier_den", sa.BigInteger(), nullable=False,
                  server_default="1"),
        sa.Column("extraction_modifier_num", sa.BigInteger(), nullable=False,
                  server_default="1"),
        sa.Column("extraction_modifier_den", sa.BigInteger(), nullable=False,
                  server_default="1"),
        sa.Column("habitat_stress_level", sa.String(16), nullable=False,
                  server_default="NONE"),
        sa.Column("environmental_stress_num", sa.BigInteger(), nullable=False,
                  server_default="0"),
        sa.Column("environmental_stress_den", sa.BigInteger(), nullable=False,
                  server_default="1"),
        sa.Column("engine_version", sa.String(32), nullable=True),
        sa.Column("updated_blessed_tick", sa.BigInteger(), nullable=True),
        sa.UniqueConstraint("world_id", "zone_ref",
                            name="uq_ecology_feedback_state_world_zone"),
    )


def downgrade() -> None:
    op.drop_table("ecology_feedback_state")
    op.drop_table("ecology_state")
    op.drop_table("ecology_zones")
    op.drop_column("resource_nodes", "regeneration_carry")
    op.drop_column("resource_nodes", "reserve_ceiling_minor")
