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



def upgrade() -> None:
    """blessed 时间刻度统一为整数福地年（SQLite batch alter）。"""
    cols = [
        ("world_runtime", "current_blessed_time"),
        ("simulation_run", "target_blessed_time"),
        ("simulation_run", "committed_until"),
        ("simulation_checkpoints", "checkpoint_blessed_time"),
        ("world_events", "blessed_time"),
        ("world_state_changes", "blessed_time"),
    ]
    for table, col in cols:
        with op.batch_alter_table(table) as b:
            b.alter_column(col, type_=sa.Integer(),
                           existing_type=sa.String(32), existing_nullable=True)


def downgrade() -> None:
    for table, col in [
        ("world_runtime", "current_blessed_time"),
        ("simulation_run", "target_blessed_time"),
        ("simulation_run", "committed_until"),
        ("simulation_checkpoints", "checkpoint_blessed_time"),
        ("world_events", "blessed_time"),
        ("world_state_changes", "blessed_time"),
    ]:
        with op.batch_alter_table(table) as b:
            b.alter_column(col, type_=sa.String(32),
                           existing_type=sa.Integer(), existing_nullable=True)
