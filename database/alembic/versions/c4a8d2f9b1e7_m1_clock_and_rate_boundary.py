"""m1_clock_and_rate_boundary

M1 TIME ENGINE：
1. time_ratio_history 增加整数真实时间边界 real_effective_from_us（epoch µs）
   —— Offline Catch-up 分段积分的无歧义整数边界；由现有 real_effective_from
   精确换算回填（纯整数运算，无 float）。
2. world_runtime 增加持久化时钟：
   - last_committed_real_us：已提交现实游标（epoch µs）
   - time_rate_remainder：积分进位（绑定 current_time_ratio_id）

Revision ID: c4a8d2f9b1e7
Revises: e9f4b7c2d8a6
Create Date: 2026-09-06
"""
from datetime import datetime, timedelta, timezone
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4a8d2f9b1e7'
down_revision: Union[str, Sequence[str], None] = 'e9f4b7c2d8a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _epoch_us(value) -> int:
    if isinstance(value, str):
        dt = datetime.fromisoformat(value.replace(" ", "T"))
    else:
        dt = value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return (dt - _EPOCH) // timedelta(microseconds=1)


def upgrade() -> None:
    with op.batch_alter_table("time_ratio_history") as b:
        b.add_column(sa.Column("real_effective_from_us", sa.BigInteger(),
                               nullable=True))

    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT ratio_id, real_effective_from FROM time_ratio_history"
    )).fetchall()
    for ratio_id, value in rows:
        bind.execute(
            sa.text("UPDATE time_ratio_history SET real_effective_from_us = :us "
                    "WHERE ratio_id = :rid"),
            {"us": _epoch_us(value), "rid": ratio_id})

    with op.batch_alter_table("time_ratio_history") as b:
        b.alter_column("real_effective_from_us", existing_type=sa.BigInteger(),
                       existing_nullable=True, nullable=False)

    with op.batch_alter_table("world_runtime") as b:
        b.add_column(sa.Column("last_committed_real_us", sa.BigInteger(),
                               nullable=True))
        b.add_column(sa.Column("time_rate_remainder", sa.BigInteger(),
                               nullable=False, server_default="0"))


def downgrade() -> None:
    with op.batch_alter_table("world_runtime") as b:
        b.drop_column("time_rate_remainder")
        b.drop_column("last_committed_real_us")
    with op.batch_alter_table("time_ratio_history") as b:
        b.drop_column("real_effective_from_us")
