"""数据库级不变量的校验入口（M0 DSH QA）。

Event History 不可变不是代码约定：由 migration b2d4e8f9a6c3 的 DB 触发器
（SQLite BEFORE UPDATE/DELETE → RAISE(ABORT)；PostgreSQL BEFORE UPDATE OR DELETE
trigger → RAISE EXCEPTION）在数据库层强制执行。
本模块提供触发器存在性校验，供 init_db 与测试使用。
"""
from __future__ import annotations

from sqlalchemy import Engine, text

from domain.errors import IntegrityError


def event_immutability_triggers_present(engine: Engine) -> bool:
    dialect = engine.dialect.name
    if dialect == "sqlite":
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT name FROM sqlite_master "
                "WHERE type='trigger' AND tbl_name='world_events'")).fetchall()
        return len(rows) >= 2
    if dialect == "postgresql":
        with engine.connect() as conn:
            n = conn.execute(text(
                "SELECT COUNT(*) FROM pg_trigger "
                "WHERE tgname='blr_world_events_no_modify' "
                "AND NOT tgisinternal")).scalar()
        return bool(n)
    return False


def verify_event_immutability(engine: Engine) -> None:
    if not event_immutability_triggers_present(engine):
        raise IntegrityError(
            "world_events 不可变触发器缺失（DB 层事件历史不可变被破坏）",
            detail=engine.dialect.name)
