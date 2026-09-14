"""m0_blessed_time_integer

Revision ID: 5aef35f022b4
Revises: 7253f352f69e
Create Date: 2026-09-06 22:32:40.051439

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5aef35f022b4'
down_revision: Union[str, Sequence[str], None] = '7253f352f69e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None



#: (table, column) 对：M0 的文本 blessed 时间 → 整数福地年。
_COLS = [
    ("world_runtime", "current_blessed_time"),
    ("simulation_run", "target_blessed_time"),
    ("simulation_run", "committed_until"),
    ("simulation_checkpoints", "checkpoint_blessed_time"),
    ("world_events", "blessed_time"),
    ("world_state_changes", "blessed_time"),
]


def upgrade() -> None:
    """blessed 时间刻度统一为整数福地年（SQLite batch alter）。

    PostgreSQL 直改列类型（batch 在 PG 上直通原生 ALTER）需要显式 ``USING``：
    varchar → integer 无赋值转换。转换直接取自旧列文本 —— 世界此刻尚未播种、
    无历史数据；若真出现非数值历史数据，PG 会**报错中止本迁移**，
    而不是静默错转（与 e9f4b7c2d8a6 的审计口径一致）。
    """
    for table, col in _COLS:
        with op.batch_alter_table(table) as b:
            b.alter_column(col, type_=sa.Integer(),
                           existing_type=sa.String(32), existing_nullable=True,
                           postgresql_using=f"{col}::integer")


def downgrade() -> None:
    for table, col in _COLS:
        with op.batch_alter_table(table) as b:
            b.alter_column(col, type_=sa.String(32),
                           existing_type=sa.Integer(), existing_nullable=True,
                           postgresql_using=f"{col}::varchar(32)")
