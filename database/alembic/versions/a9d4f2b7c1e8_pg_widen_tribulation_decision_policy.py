"""pg_widen_tribulation_decision_policy

PRE-M6 PostgreSQL FUNCTIONAL GATE 发现并修复的真实缺陷（PG-011）。

背景：``tribulation_episodes.decision_policy`` 建表时声明为 ``VARCHAR(24)``
（migration f1b3c5d7e9a2），但运行期写入的
``DEFAULT_AUTONOMOUS_RESPONSE_POLICY``（services.simulation.tribulation /
tribulation_contracts 的冻结常量）长度为 **33**。

- SQLite：``VARCHAR(N)`` 长度**不被强制**（亲和类型只有 TEXT），因此该写入
  一直"通过"，缺陷长期不可见；
- PostgreSQL：``character varying(24)`` 严格强制 →
  ``DataError: value too long for type character varying(24)``，
  仿真在 IMPACT 阶段写 decision_policy 时直接中止。

本 migration 将列加宽到 ``VARCHAR(64)``（覆盖现有与可预见的策略名长度），
并在模型侧同步 ``String(64)``。加宽类型在 PostgreSQL 上无需 ``USING``
（varchar 加宽是二进制的安全变更）；SQLite 侧走 batch 重建，数据保留、
语义不变（SQLite 不强制长度，行为本来就与加宽前一致）。

downgrade 回到 ``VARCHAR(24)``：若届时已存在 >24 字符的历史值，
PostgreSQL 会**报错中止**（fail-closed，不静默截断）——这是有意的。

Revision ID: a9d4f2b7c1e8
Revises: f2a7c4e9b1d6
Create Date: 2026-09-14
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a9d4f2b7c1e8'
down_revision: Union[str, Sequence[str], None] = 'f2a7c4e9b1d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "tribulation_episodes"
COLUMN = "decision_policy"
WIDENED_LENGTH = 64
ORIGINAL_LENGTH = 24


def upgrade() -> None:
    with op.batch_alter_table(TABLE) as b:
        b.alter_column(COLUMN, type_=sa.String(WIDENED_LENGTH),
                       existing_type=sa.String(ORIGINAL_LENGTH),
                       existing_nullable=True)


def downgrade() -> None:
    with op.batch_alter_table(TABLE) as b:
        b.alter_column(COLUMN, type_=sa.String(ORIGINAL_LENGTH),
                       existing_type=sa.String(WIDENED_LENGTH),
                       existing_nullable=True)
