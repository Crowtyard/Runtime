"""p1_pg_event_truncate_immutability

PRE-M6 PostgreSQL 门禁硬化（PG-006）：world_events 在 PostgreSQL 上必须
同时抵御 TRUNCATE。

背景（为什么需要新增本 migration）：
- SQLite 没有 TRUNCATE 语句，删除只能走 DELETE —— 已由 b2d4e8f9a6c3 的
  ``BEFORE DELETE`` 触发器拦截，因此 SQLite 侧本 migration 为 **no-op**。
- PostgreSQL 中 ``BEFORE UPDATE OR DELETE FOR EACH ROW`` 触发器**不会**被
  ``TRUNCATE`` 触发（TRUNCATE 不产生行事件），所以 b2d4e8f9a6c3 的 PG 触发器
  只覆盖 UPDATE/DELETE，``TRUNCATE TABLE world_events`` 会静默清空事件历史。
  本 migration 增加**语句级** ``BEFORE TRUNCATE`` 触发器补上该缺口。

方案选择：采用「BEFORE TRUNCATE 触发器」（方案 A），与既有 schema/migration
模型一致（触发器 + plpgsql 函数，同 b2d4e8f9a6c3 的写法），不采用
「REVOKE TRUNCATE」权限路线——后者依赖运行角色/属主，且会被属主与超级用户
绕过，无法作为 DB 层硬保证。

范围：仅 ``world_events``（当前 schema 中唯一具备 DB 层不可变保护的权威表）。
本 migration 不扩大保护面到其他历史表（那是独立设计决定，不得静默扩张）。

注意：不可变性的解除只能通过 DDL + 受控运维流程（迁移 downgrade / 显式
DROP TRIGGER），应用层「不调用 TRUNCATE」不构成保证。

Revision ID: f2a7c4e9b1d6
Revises: d7f9b1c3e5a7
Create Date: 2026-09-14
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f2a7c4e9b1d6'
down_revision: Union[str, Sequence[str], None] = 'd7f9b1c3e5a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "world_events"
TRUNCATE_FUNCTION = "blr_world_events_no_truncate"
TRUNCATE_TRIGGER = "blr_world_events_no_truncate"


def upgrade() -> None:
    """PostgreSQL：新增 world_events 的 BEFORE TRUNCATE 语句级触发器。"""
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        # SQLite 无 TRUNCATE 语句；DELETE 已由 b2d4e8f9a6c3 触发器拦截 → no-op。
        return
    if dialect == "postgresql":
        op.execute(f"""
            CREATE OR REPLACE FUNCTION {TRUNCATE_FUNCTION}() RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'world_events is append-only: % forbidden', TG_OP;
            END;
            $$ LANGUAGE plpgsql
        """)
        op.execute(f"""
            CREATE TRIGGER {TRUNCATE_TRIGGER}
            BEFORE TRUNCATE ON {TABLE}
            FOR EACH STATEMENT EXECUTE FUNCTION {TRUNCATE_FUNCTION}()
        """)
        return
    raise NotImplementedError(f"world_events TRUNCATE 不可变保护未实现方言: {dialect}")


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        return
    if dialect == "postgresql":
        op.execute(f"DROP TRIGGER IF EXISTS {TRUNCATE_TRIGGER} ON {TABLE}")
        op.execute(f"DROP FUNCTION IF EXISTS {TRUNCATE_FUNCTION}()")
        return
    raise NotImplementedError(f"world_events TRUNCATE 不可变保护未实现方言: {dialect}")
