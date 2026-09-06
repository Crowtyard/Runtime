"""m1_simulation_run_interval_identity

M1 SIMULATION RUN 生命周期与区间幂等身份：
simulation_run 增加 real_interval_start_us / real_interval_end_us /
blessed_tick_before / blessed_tick_delta / real_cursor_after_us /
writer_id / fencing_token（旧行/旧 run_atomic_tick 行保持 NULL，不影响）。

Revision ID: d5b9e3f0a2c8
Revises: c4a8d2f9b1e7
Create Date: 2026-09-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd5b9e3f0a2c8'
down_revision: Union[str, Sequence[str], None] = 'c4a8d2f9b1e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("simulation_run") as b:
        b.add_column(sa.Column("real_interval_start_us", sa.BigInteger(),
                               nullable=True))
        b.add_column(sa.Column("real_interval_end_us", sa.BigInteger(),
                               nullable=True))
        b.add_column(sa.Column("blessed_tick_before", sa.BigInteger(),
                               nullable=True))
        b.add_column(sa.Column("blessed_tick_delta", sa.BigInteger(),
                               nullable=True))
        b.add_column(sa.Column("real_cursor_after_us", sa.BigInteger(),
                               nullable=True))
        b.add_column(sa.Column("writer_id", sa.String(64), nullable=True))
        b.add_column(sa.Column("fencing_token", sa.String(64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("simulation_run") as b:
        for col in ("fencing_token", "writer_id", "real_cursor_after_us",
                    "blessed_tick_delta", "blessed_tick_before",
                    "real_interval_end_us", "real_interval_start_us"):
            b.drop_column(col)
