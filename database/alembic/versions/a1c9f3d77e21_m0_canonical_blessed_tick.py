"""m0_canonical_blessed_tick

CANONICAL_BLESSED_TICK（M0 DSH 独立 QA）：世界时间坐标从"整数福地年"改为
整数 canonical tick（1 tick = 1 micro-blessed-year，µy），列统一 BigInteger
（SQLite 64-bit INTEGER / PostgreSQL BIGINT），列名以 *_tick 结尾，语义自明。

World Seed 尚未激活、无历史数据 → 直接 rename + 类型变更（SQLite batch；
PostgreSQL 直改，varchar → bigint 必须带显式 USING）。year/month/day 仅是
projection，历法 Canon 未定义不得发明。

Revision ID: a1c9f3d77e21
Revises: 5aef35f022b4
Create Date: 2026-09-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1c9f3d77e21'
down_revision: Union[str, Sequence[str], None] = '5aef35f022b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (table, old_col, new_col, existing_type)
_CORE = [
    ("world_runtime", "current_blessed_time", "current_blessed_tick", sa.Integer()),
    ("time_ratio_history", "blessed_effective_from", "blessed_effective_from_tick",
     sa.String(32)),
    ("simulation_run", "target_blessed_time", "target_blessed_tick", sa.Integer()),
    ("simulation_run", "committed_until", "committed_until_tick", sa.Integer()),
    ("simulation_checkpoints", "checkpoint_blessed_time", "checkpoint_blessed_tick",
     sa.Integer()),
    ("world_events", "blessed_time", "blessed_tick", sa.Integer()),
    ("world_state_changes", "blessed_time", "blessed_tick", sa.Integer()),
]

_WORLD = [
    ("population_groups", "updated_blessed_time", "updated_blessed_tick", sa.String(24)),
    ("persons", "birth_blessed_time", "birth_blessed_tick", sa.String(24)),
    ("tribulations", "start_blessed_time", "start_blessed_tick", sa.String(24)),
    ("tribulations", "end_blessed_time", "end_blessed_tick", sa.String(24)),
    ("timeline_entries", "blessed_time", "blessed_tick", sa.String(24)),
]


def _pg_using(column: str, target: object) -> str | None:
    """PostgreSQL 显式 USING 表达式（仅无赋值转换的类型变更需要）。

    batch_alter_table 在 PG 上直通原生 ``ALTER TABLE``：varchar → bigint /
    bigint → varchar 均无赋值转换，必须给出 USING；integer ↔ bigint 属赋值
    转换，返回 None（不加 USING，保持最小改动）。SQLite 走 batch 重建，
    方言专属参数不影响其行为。
    """
    if isinstance(target, sa.String):
        return f"{column}::varchar({target.length})"
    if isinstance(target, sa.BigInteger):
        return f"{column}::bigint"
    return None


def _alter(cols: list[tuple[str, str, str, object]], to_tick: bool) -> None:
    for table, old, new, existing in cols:
        with op.batch_alter_table(table) as b:
            if to_tick:
                b.alter_column(old, new_column_name=new, type_=sa.BigInteger(),
                               existing_type=existing, existing_nullable=True,
                               postgresql_using=_pg_using(old, sa.BigInteger()))
            else:
                b.alter_column(new, new_column_name=old, type_=existing,
                               existing_type=sa.BigInteger(), existing_nullable=True,
                               postgresql_using=_pg_using(new, existing))


def upgrade() -> None:
    """blessed 时间坐标 → canonical blessed tick（µy 整数，BigInteger）。"""
    _alter(_CORE + _WORLD, to_tick=True)


def downgrade() -> None:
    _alter(_CORE + _WORLD, to_tick=False)
