"""m0_explicit_utc_iso8601

Real Time 存储显式化：SQLite 中全部现实时间文本补显式 \"+00:00\" UTC 后缀
（ISO-8601 UTC，字典序安全、无时区歧义）；PostgreSQL 为原生 TIMESTAMPTZ，无需变更。
应用层配合 UtcDateTime 列类型（database/base.py）在边界强制 aware UTC。

Revision ID: d8e1b3a5c7f9
Revises: a1c9f3d77e21
Create Date: 2026-09-06
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd8e1b3a5c7f9'
down_revision: Union[str, Sequence[str], None] = 'a1c9f3d77e21'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DATETIME_COLS = [
    ("world_runtime", "created_at"),
    ("world_runtime", "last_simulated_real_time"),
    ("time_ratio_history", "real_effective_from"),
    ("time_ratio_history", "created_at"),
    ("simulation_run", "started_at"),
    ("simulation_run", "finished_at"),
    ("simulation_checkpoints", "created_at"),
    ("world_events", "real_time"),
    ("world_events", "created_at"),
    ("world_state_changes", "real_time"),
    ("narrative_records", "generated_at"),
    ("runtime_lock", "acquired_at"),
    ("runtime_lock", "expires_at"),
    ("system_configuration", "updated_at"),
    ("timeline_entries", "real_time"),
    ("timeline_entries", "created_at"),
]


def upgrade() -> None:
    """SQLite：显式 ISO-8601 UTC（+00:00）；PG：TIMESTAMPTZ 原生，no-op。"""
    if op.get_bind().dialect.name != "sqlite":
        return
    for table, col in _DATETIME_COLS:
        op.execute(
            f"UPDATE {table} SET {col} = {col} || '+00:00' "
            f"WHERE {col} IS NOT NULL "
            f"AND {col} NOT LIKE '%+00:00' AND {col} NOT LIKE '%Z'")


def downgrade() -> None:
    if op.get_bind().dialect.name != "sqlite":
        return
    for table, col in _DATETIME_COLS:
        op.execute(
            f"UPDATE {table} SET {col} = substr({col}, 1, length({col}) - 6) "
            f"WHERE {col} LIKE '%+00:00'")
