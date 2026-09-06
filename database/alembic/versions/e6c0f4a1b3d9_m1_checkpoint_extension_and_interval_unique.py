"""m1_checkpoint_extension_and_interval_unique

M1 CHECKPOINT 扩展 + COMMITTED 区间唯一索引：
1. simulation_checkpoints 增加 last_committed_real_us / rate_id /
   rate_remainder / simulation_version / last_committed_run_id /
   writer_id / fencing_token（crash 后仅依赖 DB 恢复时钟状态）。
2. simulation_run 上建部分唯一索引（status='COMMITTED'）：
   (world_id, simulation_version, real_interval_start_us, real_interval_end_us)
   → 同一现实时间区间只允许一个 COMMITTED run（DB 层幂等防线；
   NULL 区间行不受影响）。

Revision ID: e6c0f4a1b3d9
Revises: d5b9e3f0a2c8
Create Date: 2026-09-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e6c0f4a1b3d9'
down_revision: Union[str, Sequence[str], None] = 'd5b9e3f0a2c8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INTERVAL_IDX = "uq_simulation_run_committed_interval"


def upgrade() -> None:
    with op.batch_alter_table("simulation_checkpoints") as b:
        b.add_column(sa.Column("last_committed_real_us", sa.BigInteger(),
                               nullable=True))
        b.add_column(sa.Column("rate_id", sa.Integer(), nullable=True))
        b.add_column(sa.Column("rate_remainder", sa.BigInteger(),
                               nullable=False, server_default="0"))
        b.add_column(sa.Column("simulation_version", sa.String(32),
                               nullable=True))
        b.add_column(sa.Column("last_committed_run_id", sa.String(64),
                               nullable=True))
        b.add_column(sa.Column("writer_id", sa.String(64), nullable=True))
        b.add_column(sa.Column("fencing_token", sa.String(64), nullable=True))

    op.create_index(
        _INTERVAL_IDX,
        "simulation_run",
        ["world_id", "simulation_version",
         "real_interval_start_us", "real_interval_end_us"],
        unique=True,
        sqlite_where=sa.text("status = 'COMMITTED'"),
        postgresql_where=sa.text("status = 'COMMITTED'"),
    )


def downgrade() -> None:
    op.drop_index(_INTERVAL_IDX, table_name="simulation_run")
    with op.batch_alter_table("simulation_checkpoints") as b:
        for col in ("fencing_token", "writer_id", "last_committed_run_id",
                    "simulation_version", "rate_remainder", "rate_id",
                    "last_committed_real_us"):
            b.drop_column(col)
