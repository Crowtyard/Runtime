"""m0_event_immutability_triggers

Event History 数据库层不可变（17 节）：Committed Event 禁止原地 UPDATE/DELETE。
- SQLite：BEFORE UPDATE / BEFORE DELETE 触发器 → RAISE(ABORT)。
- PostgreSQL：BEFORE UPDATE OR DELETE FOR EACH ROW 触发器 → RAISE EXCEPTION。
纠错必须走新事件（supersedes/reverses + correction_reason）。

注意（SQLite）：Alembic batch_alter_table 重建表时会丢失触发器 ——
未来任何对 world_events 的 batch 结构变更后必须重新应用本触发器
（database/invariants.py 提供 verify_event_immutability 校验在位性）。

Revision ID: b2d4e8f9a6c3
Revises: d8e1b3a5c7f9
Create Date: 2026-09-06
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b2d4e8f9a6c3'
down_revision: Union[str, Sequence[str], None] = 'd8e1b3a5c7f9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建 world_events 不可变触发器（按方言分支）。"""
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute("""
            CREATE TRIGGER blr_world_events_no_update
            BEFORE UPDATE ON world_events
            BEGIN
                SELECT RAISE(ABORT, 'world_events is append-only: UPDATE forbidden');
            END
        """)
        op.execute("""
            CREATE TRIGGER blr_world_events_no_delete
            BEFORE DELETE ON world_events
            BEGIN
                SELECT RAISE(ABORT, 'world_events is append-only: DELETE forbidden');
            END
        """)
    elif dialect == "postgresql":
        op.execute("""
            CREATE OR REPLACE FUNCTION blr_world_events_no_modify() RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'world_events is append-only: % forbidden', TG_OP;
            END;
            $$ LANGUAGE plpgsql
        """)
        op.execute("""
            CREATE TRIGGER blr_world_events_no_modify
            BEFORE UPDATE OR DELETE ON world_events
            FOR EACH ROW EXECUTE FUNCTION blr_world_events_no_modify()
        """)
    else:
        raise NotImplementedError(f"world_events 不可变触发器未实现方言: {dialect}")


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS blr_world_events_no_update")
        op.execute("DROP TRIGGER IF EXISTS blr_world_events_no_delete")
    elif dialect == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS blr_world_events_no_modify ON world_events")
        op.execute("DROP FUNCTION IF EXISTS blr_world_events_no_modify()")
