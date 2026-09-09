# -*- coding: utf-8 -*-
"""m3b_causal_history

Revision ID: c5e7a9b1d3f5
Revises: f1b3c5d7e9a2

- 新表 5 张：causal_history_links / entity_history_index /
  history_state_changes / history_episode_index / history_index_state
- History Index 是对已发生事实的索引：不改任何模拟表语义、不进
  world_state_hash（v6 不变）；history_state_changes 为 M3b 自有账本
  （内联 provenance），绝不向 M0 world_state_changes 插行 —— 保证
  M3a 的 tribulation_causal_links.state_change_ids 等 id 引用逐字节不变。
- 只 ADD，不改旧 migration。正式 DB 迁移后 5 表 0 行。
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "c5e7a9b1d3f5"
down_revision = "f1b3c5d7e9a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "causal_history_links",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("world_id", sa.String(32), nullable=False, index=True),
        sa.Column("link_id", sa.String(32), nullable=False),
        sa.Column("relation_type", sa.String(24), nullable=False),
        sa.Column("source_kind", sa.String(24), nullable=False),
        sa.Column("source_id", sa.String(64), nullable=False),
        sa.Column("target_kind", sa.String(24), nullable=False),
        sa.Column("target_id", sa.String(64), nullable=False),
        sa.Column("source_tick", sa.BigInteger(), nullable=True),
        sa.Column("target_tick", sa.BigInteger(), nullable=True),
        sa.Column("episode_id", sa.String(32), nullable=True),
        sa.Column("entity_scope", sa.JSON(), nullable=True),
        sa.Column("owner_decision_id", sa.String(32), nullable=True),
        sa.Column("committed_tick", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(12), nullable=False,
                  server_default="ACTIVE"),
        sa.Column("semantic_version", sa.String(32), nullable=True),
        sa.UniqueConstraint("world_id", "link_id",
                            name="uq_causal_history_links_world"),
    )
    op.create_index("ix_hist_links_committed",
                    "causal_history_links", ["world_id", "committed_tick"])
    op.create_index("ix_hist_links_source",
                    "causal_history_links",
                    ["world_id", "source_kind", "source_id"])
    op.create_index("ix_hist_links_target",
                    "causal_history_links",
                    ["world_id", "target_kind", "target_id"])
    op.create_index("ix_hist_links_episode",
                    "causal_history_links", ["world_id", "episode_id"])
    op.create_index("ix_hist_links_relation",
                    "causal_history_links",
                    ["world_id", "relation_type", "committed_tick"])

    op.create_table(
        "entity_history_index",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("world_id", sa.String(32), nullable=False, index=True),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("entity_id", sa.String(64), nullable=False),
        sa.Column("link_id", sa.String(32), nullable=False),
        sa.Column("committed_tick", sa.BigInteger(), nullable=False),
        sa.Column("semantic_version", sa.String(32), nullable=True),
        sa.UniqueConstraint("world_id", "entity_type", "entity_id", "link_id",
                            name="uq_entity_history_index_world"),
    )
    op.create_index("ix_entity_history_scope",
                    "entity_history_index",
                    ["world_id", "entity_type", "entity_id",
                     "committed_tick"])

    op.create_table(
        "history_state_changes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("world_id", sa.String(32), nullable=False, index=True),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("entity_id", sa.String(64), nullable=False),
        sa.Column("field", sa.String(64), nullable=False),
        sa.Column("old_value", sa.JSON(), nullable=True),
        sa.Column("new_value", sa.JSON(), nullable=True),
        sa.Column("event_ref", sa.String(64), nullable=True),
        sa.Column("blessed_tick", sa.BigInteger(), nullable=True),
        # ---- provenance（内联；旧数据缺字段 = NULL，绝不伪造）----
        sa.Column("simulation_run_id", sa.String(64), nullable=True),
        sa.Column("engine_id", sa.String(32), nullable=True),
        sa.Column("trigger_event_id", sa.String(64), nullable=True),
        sa.Column("episode_id", sa.String(32), nullable=True),
        sa.Column("owner_decision_id", sa.String(32), nullable=True),
        sa.Column("semantic_version", sa.String(32), nullable=True),
    )
    op.create_index("ix_hist_sc_entity",
                    "history_state_changes",
                    ["world_id", "entity_type", "entity_id",
                     "blessed_tick"])
    op.create_index("ix_hist_sc_episode",
                    "history_state_changes", ["world_id", "episode_id"])

    op.create_table(
        "history_episode_index",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("world_id", sa.String(32), nullable=False, index=True),
        sa.Column("episode_id", sa.String(32), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False,
                  server_default="TRIBULATION"),
        sa.Column("status", sa.String(16), nullable=False,
                  server_default="ACTIVE"),
        sa.Column("stage", sa.String(24), nullable=True),
        sa.Column("entered_tick", sa.BigInteger(), nullable=True),
        sa.Column("transition_tick", sa.BigInteger(), nullable=True),
        sa.Column("completed_tick", sa.BigInteger(), nullable=True),
        sa.Column("profile_ref", sa.String(64), nullable=True),
        sa.Column("tier", sa.String(16), nullable=True),
        sa.Column("semantic_version", sa.String(32), nullable=True),
        sa.UniqueConstraint("world_id", "episode_id",
                            name="uq_history_episode_index_world"),
    )
    op.create_index("ix_history_episode_status",
                    "history_episode_index", ["world_id", "status"])

    op.create_table(
        "history_index_state",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("world_id", sa.String(32), nullable=False),
        sa.Column("indexed_through_tick", sa.BigInteger(), nullable=False,
                  server_default="0"),
        sa.Column("links_total", sa.BigInteger(), nullable=False,
                  server_default="0"),
        sa.Column("causal_history_hash", sa.String(64), nullable=True),
        sa.Column("semantic_version", sa.String(32), nullable=True),
        sa.UniqueConstraint("world_id", name="uq_history_index_state_world"),
    )


def downgrade() -> None:
    op.drop_table("history_index_state")
    op.drop_table("history_episode_index")
    op.drop_table("history_state_changes")
    op.drop_table("entity_history_index")
    op.drop_table("causal_history_links")
