# -*- coding: utf-8 -*-
"""m3b_metric_audit_indexes

Revision ID: d7f9b1c3e5a7
Revises: c5e7a9b1d3f5

- 仅新增索引（不重构 schema、不新增表、不改数据语义）：
  ix_world_events_tick (world_id, blessed_tick) —— timeline 查询
  （ORDER BY blessed_tick, id + 时间窗过滤）避免全表扫描。
- SQLite + PostgreSQL 双兼容（标准 CREATE INDEX，无 SQLite-only 语法）。
- 不影响 world_state_hash / event_stream_hash（索引不进任何哈希域）。
"""
from __future__ import annotations

from alembic import op

revision = "d7f9b1c3e5a7"
down_revision = "c5e7a9b1d3f5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_world_events_tick", "world_events",
                    ["world_id", "blessed_tick"])


def downgrade() -> None:
    op.drop_index("ix_world_events_tick", table_name="world_events")
