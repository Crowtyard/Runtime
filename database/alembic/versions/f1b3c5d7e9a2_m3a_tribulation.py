# -*- coding: utf-8 -*-
"""m3a_tribulation

Revision ID: f1b3c5d7e9a2
Revises: e8a1c5d7f2b4

- 新表 9 张：tribulation_profiles / tribulation_schedules /
  tribulation_episodes / tribulation_decisions / tribulation_impact_plans /
  tribulation_recovery_states / tribulation_residual_changes /
  resource_succession_candidates / tribulation_causal_links
- 关键索引与状态全部结构化列（BigInteger fixed-point + JSON payload）；
  避免单一巨大 JSON Blob 充当灾劫真值；SQLite+PG 双兼容。
- 只 ADD，不改旧 migration。正式 DB 迁移后 0 行（测试 profile 绝不自动创建）。
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "f1b3c5d7e9a2"
down_revision = "e8a1c5d7f2b4"
branch_labels = None
depends_on = None


def _risk_cols() -> list[sa.Column]:
    cols = []
    for name in ("population_risk", "resource_damage", "inventory_damage",
                 "production_disruption", "social_displacement",
                 "institution_disruption"):
        cols.append(sa.Column(f"{name}_num", sa.BigInteger(), nullable=False,
                              server_default="0"))
        cols.append(sa.Column(f"{name}_den", sa.BigInteger(), nullable=False,
                              server_default="1"))
    return cols


def upgrade() -> None:
    op.create_table(
        "tribulation_profiles",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("world_id", sa.String(32), nullable=False, index=True),
        sa.Column("profile_id", sa.String(64), nullable=False),
        sa.Column("tier", sa.String(16), nullable=False),
        sa.Column("theme", sa.String(32), nullable=False),
        sa.Column("intensity_min", sa.BigInteger(), nullable=False,
                  server_default="0"),
        sa.Column("intensity_max", sa.BigInteger(), nullable=False,
                  server_default="100"),
        sa.Column("precursor_steps", sa.BigInteger(), nullable=False,
                  server_default="1"),
        sa.Column("preparation_steps", sa.BigInteger(), nullable=False,
                  server_default="1"),
        sa.Column("impact_steps", sa.BigInteger(), nullable=False,
                  server_default="1"),
        *_risk_cols(),
        sa.Column("ecology_pressure", sa.BigInteger(), nullable=False,
                  server_default="0"),
        sa.Column("recovery_steps", sa.BigInteger(), nullable=False,
                  server_default="2"),
        sa.Column("targeting_rules", sa.JSON(), nullable=True),
        sa.Column("succession_rules", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(24), nullable=False,
                  server_default="TEST_FIXTURE_ONLY"),
        sa.Column("source_refs", sa.JSON(), nullable=True),
        sa.Column("semantic_version", sa.String(32), nullable=True),
        sa.UniqueConstraint("world_id", "profile_id",
                            name="uq_tribulation_profiles_world"),
    )

    op.create_table(
        "tribulation_schedules",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("world_id", sa.String(32), nullable=False, index=True),
        sa.Column("schedule_id", sa.String(64), nullable=False),
        sa.Column("tier", sa.String(16), nullable=False),
        sa.Column("period_years", sa.BigInteger(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("semantic_version", sa.String(32), nullable=True),
        sa.UniqueConstraint("world_id", "schedule_id", "tier",
                            name="uq_tribulation_schedules_world"),
    )

    op.create_table(
        "tribulation_episodes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("world_id", sa.String(32), nullable=False, index=True),
        sa.Column("episode_id", sa.String(32), nullable=False),
        sa.Column("window_tier", sa.String(16), nullable=False),
        sa.Column("schedule_ref", sa.String(64), nullable=True),
        sa.Column("profile_ref", sa.String(64), nullable=True),
        sa.Column("current_stage", sa.String(24), nullable=False),
        sa.Column("entered_tick", sa.BigInteger(), nullable=True),
        sa.Column("transition_tick", sa.BigInteger(), nullable=True),
        sa.Column("target_regions", sa.JSON(), nullable=True),
        sa.Column("target_settlements", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(12), nullable=False,
                  server_default="ACTIVE"),
        sa.Column("decision_policy", sa.String(24), nullable=True),
        sa.Column("semantic_version", sa.String(32), nullable=True),
        sa.Column("updated_blessed_tick", sa.BigInteger(), nullable=True),
        sa.UniqueConstraint("world_id", "episode_id",
                            name="uq_tribulation_episodes_world"),
    )

    op.create_table(
        "tribulation_decisions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("world_id", sa.String(32), nullable=False, index=True),
        sa.Column("decision_id", sa.String(32), nullable=False),
        sa.Column("episode_id", sa.String(32), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("submitted_tick", sa.BigInteger(), nullable=True),
        sa.Column("effective_before_tick", sa.BigInteger(), nullable=True),
        sa.Column("target_priorities", sa.JSON(), nullable=True),
        sa.Column("resource_allocation", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(12), nullable=False,
                  server_default="ACTIVE"),
        sa.Column("supersedes_decision_id", sa.String(32), nullable=True),
        sa.Column("source", sa.String(32), nullable=True),
        sa.Column("semantic_version", sa.String(32), nullable=True),
        sa.UniqueConstraint("world_id", "decision_id",
                            name="uq_tribulation_decisions_world"),
    )

    op.create_table(
        "tribulation_impact_plans",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("world_id", sa.String(32), nullable=False, index=True),
        sa.Column("plan_id", sa.String(32), nullable=False),
        sa.Column("episode_id", sa.String(32), nullable=False),
        sa.Column("profile_ref", sa.String(64), nullable=True),
        sa.Column("tier", sa.String(16), nullable=False),
        sa.Column("intensity", sa.BigInteger(), nullable=False),
        sa.Column("affected_regions", sa.JSON(), nullable=True),
        sa.Column("affected_settlements", sa.JSON(), nullable=True),
        *_risk_cols(),
        sa.Column("ecology_pressure", sa.BigInteger(), nullable=False,
                  server_default="0"),
        sa.Column("mitigation_applied", sa.JSON(), nullable=True),
        sa.Column("residual_changes", sa.JSON(), nullable=True),
        sa.Column("recovery_requirements", sa.JSON(), nullable=True),
        sa.Column("succession_candidates", sa.JSON(), nullable=True),
        sa.Column("semantic_version", sa.String(32), nullable=True),
        sa.UniqueConstraint("world_id", "plan_id",
                            name="uq_tribulation_impact_plans_world"),
    )

    op.create_table(
        "tribulation_recovery_states",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("world_id", sa.String(32), nullable=False, index=True),
        sa.Column("episode_id", sa.String(32), nullable=False),
        sa.Column("recovery_need_num", sa.BigInteger(), nullable=False,
                  server_default="100"),
        sa.Column("recovery_need_den", sa.BigInteger(), nullable=False,
                  server_default="100"),
        sa.Column("progress_num", sa.BigInteger(), nullable=False,
                  server_default="0"),
        sa.Column("progress_den", sa.BigInteger(), nullable=False,
                  server_default="100"),
        sa.Column("resource_requirement", sa.BigInteger(), nullable=False,
                  server_default="0"),
        sa.Column("population_requirement", sa.BigInteger(), nullable=False,
                  server_default="0"),
        sa.Column("ecology_requirement", sa.BigInteger(), nullable=False,
                  server_default="0"),
        sa.Column("social_requirement", sa.BigInteger(), nullable=False,
                  server_default="0"),
        sa.Column("status", sa.String(16), nullable=False,
                  server_default="IN_PROGRESS"),
        sa.Column("started_tick", sa.BigInteger(), nullable=True),
        sa.Column("semantic_version", sa.String(32), nullable=True),
        sa.Column("updated_blessed_tick", sa.BigInteger(), nullable=True),
        sa.UniqueConstraint("world_id", "episode_id",
                            name="uq_tribulation_recovery_states_world"),
    )

    op.create_table(
        "tribulation_residual_changes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("world_id", sa.String(32), nullable=False, index=True),
        sa.Column("episode_id", sa.String(32), nullable=False),
        sa.Column("change_kind", sa.String(32), nullable=False),
        sa.Column("region_ref", sa.String(64), nullable=True),
        sa.Column("settlement_ref", sa.String(64), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("persistent", sa.Boolean(), nullable=False,
                  server_default="1"),
        sa.Column("semantic_version", sa.String(32), nullable=True),
    )

    op.create_table(
        "resource_succession_candidates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("world_id", sa.String(32), nullable=False, index=True),
        sa.Column("candidate_id", sa.String(32), nullable=False),
        sa.Column("episode_id", sa.String(32), nullable=False),
        sa.Column("region_ref", sa.String(64), nullable=True),
        sa.Column("resource_category", sa.String(32), nullable=True),
        sa.Column("environment_conditions", sa.JSON(), nullable=True),
        sa.Column("maturation_requirement", sa.BigInteger(), nullable=False,
                  server_default="1"),
        sa.Column("observation_progress", sa.BigInteger(), nullable=False,
                  server_default="0"),
        sa.Column("stability_progress", sa.BigInteger(), nullable=False,
                  server_default="0"),
        sa.Column("discovery_status", sa.String(16), nullable=False,
                  server_default="UNOBSERVED"),
        sa.Column("development_status", sa.String(16), nullable=False,
                  server_default="NONE"),
        sa.Column("semantic_version", sa.String(32), nullable=True),
        sa.UniqueConstraint("world_id", "candidate_id",
                            name="uq_resource_succession_candidates_world"),
    )

    op.create_table(
        "tribulation_causal_links",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("world_id", sa.String(32), nullable=False, index=True),
        sa.Column("episode_id", sa.String(32), nullable=False),
        sa.Column("correlation_id", sa.String(32), nullable=True),
        sa.Column("cause_event_ids", sa.JSON(), nullable=True),
        sa.Column("trigger_event_id", sa.String(64), nullable=True),
        sa.Column("decision_event_ids", sa.JSON(), nullable=True),
        sa.Column("impact_plan_id", sa.String(32), nullable=True),
        sa.Column("result_event_ids", sa.JSON(), nullable=True),
        sa.Column("affected_entity_ids", sa.JSON(), nullable=True),
        sa.Column("state_change_ids", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("tribulation_causal_links")
    op.drop_table("resource_succession_candidates")
    op.drop_table("tribulation_residual_changes")
    op.drop_table("tribulation_recovery_states")
    op.drop_table("tribulation_impact_plans")
    op.drop_table("tribulation_decisions")
    op.drop_table("tribulation_episodes")
    op.drop_table("tribulation_schedules")
    op.drop_table("tribulation_profiles")
