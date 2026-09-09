# -*- coding: utf-8 -*-
"""m2d_social

Revision ID: e8a1c5d7f2b4
Revises: d4f7b2e9c1a6

- lineages（M0 表）扩展：lineage_id / origin_settlement /
  represented_population / household_count / generation / status /
  founded_tick / parent_lineage_ref / semantic_version /
  updated_blessed_tick（M0 锚点列保留）
- institutions（M0 表）扩展：institution_id / founded_tick /
  profile_ref / updated_blessed_tick（state 列复用生命周期）
- 新表：households / settlement_social_state / social_feedback_state
- 社会权威状态一律 BigInteger（整数 fixed-point；SQLite INTEGER 64-bit /
  PostgreSQL BIGINT）；确定性 id 字符串，无 UUID。
- 只 ADD，不改旧 migration。
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "e8a1c5d7f2b4"
down_revision = "d4f7b2e9c1a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("lineages",
                  sa.Column("lineage_id", sa.String(32), nullable=True))
    op.add_column("lineages",
                  sa.Column("origin_settlement", sa.String(64), nullable=True))
    op.add_column("lineages",
                  sa.Column("represented_population", sa.BigInteger(),
                            nullable=False, server_default="0"))
    op.add_column("lineages",
                  sa.Column("household_count", sa.BigInteger(),
                            nullable=False, server_default="0"))
    op.add_column("lineages",
                  sa.Column("generation", sa.BigInteger(), nullable=False,
                            server_default="1"))
    op.add_column("lineages",
                  sa.Column("status", sa.String(12), nullable=True))
    op.add_column("lineages",
                  sa.Column("founded_tick", sa.BigInteger(), nullable=True))
    op.add_column("lineages",
                  sa.Column("parent_lineage_ref", sa.String(32), nullable=True))
    op.add_column("lineages",
                  sa.Column("semantic_version", sa.String(16), nullable=True))
    op.add_column("lineages",
                  sa.Column("updated_blessed_tick", sa.BigInteger(),
                            nullable=True))

    op.add_column("institutions",
                  sa.Column("institution_id", sa.String(32), nullable=True))
    op.add_column("institutions",
                  sa.Column("founded_tick", sa.BigInteger(), nullable=True))
    op.add_column("institutions",
                  sa.Column("profile_ref", sa.String(64), nullable=True))
    op.add_column("institutions",
                  sa.Column("updated_blessed_tick", sa.BigInteger(),
                            nullable=True))

    op.create_table(
        "households",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("world_id", sa.String(32), nullable=False, index=True),
        sa.Column("household_id", sa.String(32), nullable=False),
        sa.Column("settlement_ref", sa.String(64), nullable=False),
        sa.Column("species", sa.String(32), nullable=False),
        sa.Column("represented_population", sa.BigInteger(), nullable=False,
                  server_default="0"),
        sa.Column("generation", sa.BigInteger(), nullable=False,
                  server_default="1"),
        sa.Column("lineage_ref", sa.String(32), nullable=True),
        sa.Column("anchor_group_ref", sa.String(16), nullable=True),
        sa.Column("state", sa.String(12), nullable=False,
                  server_default="ACTIVE"),
        sa.Column("formation_version", sa.String(16), nullable=True),
        sa.Column("updated_blessed_tick", sa.BigInteger(), nullable=True),
        sa.UniqueConstraint("world_id", "household_id",
                            name="uq_households_world_id"),
    )

    op.create_table(
        "settlement_social_state",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("world_id", sa.String(32), nullable=False, index=True),
        sa.Column("settlement_ref", sa.String(64), nullable=False),
        sa.Column("social_stress", sa.BigInteger(), nullable=False,
                  server_default="0"),
        sa.Column("social_cohesion", sa.BigInteger(), nullable=False,
                  server_default="1000000"),
        sa.Column("household_stability", sa.BigInteger(), nullable=False,
                  server_default="1000000"),
        sa.Column("mobility_pressure", sa.BigInteger(), nullable=False,
                  server_default="0"),
        sa.Column("unallocated_population", sa.BigInteger(), nullable=False,
                  server_default="0"),
        sa.Column("stress_min_seen", sa.BigInteger(), nullable=False,
                  server_default="0"),
        sa.Column("stress_max_seen", sa.BigInteger(), nullable=False,
                  server_default="0"),
        sa.Column("engine_version", sa.String(32), nullable=True),
        sa.Column("updated_blessed_tick", sa.BigInteger(), nullable=True),
        sa.UniqueConstraint("world_id", "settlement_ref",
                            name="uq_settlement_social_state_world_settlement"),
    )

    op.create_table(
        "social_feedback_state",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("world_id", sa.String(32), nullable=False, index=True),
        sa.Column("settlement_ref", sa.String(64), nullable=False),
        sa.Column("migration_modifier_num", sa.BigInteger(), nullable=False,
                  server_default="1"),
        sa.Column("migration_modifier_den", sa.BigInteger(), nullable=False,
                  server_default="1"),
        sa.Column("fertility_context_num", sa.BigInteger(), nullable=False,
                  server_default="1"),
        sa.Column("fertility_context_den", sa.BigInteger(), nullable=False,
                  server_default="1"),
        sa.Column("social_support_num", sa.BigInteger(), nullable=False,
                  server_default="1"),
        sa.Column("social_support_den", sa.BigInteger(), nullable=False,
                  server_default="1"),
        sa.Column("social_stress_num", sa.BigInteger(), nullable=False,
                  server_default="0"),
        sa.Column("social_stress_den", sa.BigInteger(), nullable=False,
                  server_default="1"),
        sa.Column("engine_version", sa.String(32), nullable=True),
        sa.Column("updated_blessed_tick", sa.BigInteger(), nullable=True),
        sa.UniqueConstraint("world_id", "settlement_ref",
                            name="uq_social_feedback_state_world_settlement"),
    )


def downgrade() -> None:
    op.drop_table("social_feedback_state")
    op.drop_table("settlement_social_state")
    op.drop_table("households")
    op.drop_column("institutions", "updated_blessed_tick")
    op.drop_column("institutions", "profile_ref")
    op.drop_column("institutions", "founded_tick")
    op.drop_column("institutions", "institution_id")
    op.drop_column("lineages", "updated_blessed_tick")
    op.drop_column("lineages", "semantic_version")
    op.drop_column("lineages", "parent_lineage_ref")
    op.drop_column("lineages", "founded_tick")
    op.drop_column("lineages", "status")
    op.drop_column("lineages", "generation")
    op.drop_column("lineages", "household_count")
    op.drop_column("lineages", "represented_population")
    op.drop_column("lineages", "origin_settlement")
    op.drop_column("lineages", "lineage_id")
