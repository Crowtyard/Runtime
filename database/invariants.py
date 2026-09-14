"""数据库级不变量的校验入口（M0 DSH QA；PRE-M6 PG-006 扩展）。

Event History 不可变不是代码约定：由 migration b2d4e8f9a6c3 的 DB 触发器
（SQLite BEFORE UPDATE/DELETE → RAISE(ABORT)；PostgreSQL BEFORE UPDATE OR DELETE
trigger → RAISE EXCEPTION）在数据库层强制执行。
本模块提供触发器存在性校验，供 init_db 与测试使用。

PRE-M6 PG-006：PostgreSQL 的行级 BEFORE UPDATE OR DELETE 触发器**不拦截
``TRUNCATE``**（TRUNCATE 不产生行事件），因此额外要求语句级
``BEFORE TRUNCATE`` 触发器（migration f2a7c4e9b1d6）。
SQLite 无 TRUNCATE 语句 → 该项恒为在位（DELETE 已由既有触发器拦截），
SQLite 行为与扩展前完全一致。
"""
from __future__ import annotations

from sqlalchemy import Engine, text

from ..domain.errors import IntegrityError

MODIFY_TRIGGER_NAME = "blr_world_events_no_modify"
TRUNCATE_TRIGGER_NAME = "blr_world_events_no_truncate"


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
                f"WHERE tgname='{MODIFY_TRIGGER_NAME}' "
                "AND NOT tgisinternal")).scalar()
        return bool(n)
    return False


def event_truncate_protection_present(engine: Engine) -> bool:
    """TRUNCATE 保护在位性（PG-006）。

    - SQLite：无 TRUNCATE 语句，恒为 True（不可变由 DELETE 触发器保证）；
    - PostgreSQL：要求语句级 BEFORE TRUNCATE 触发器在位。
    """
    dialect = engine.dialect.name
    if dialect == "sqlite":
        return True
    if dialect == "postgresql":
        with engine.connect() as conn:
            n = conn.execute(text(
                "SELECT COUNT(*) FROM pg_trigger "
                f"WHERE tgname='{TRUNCATE_TRIGGER_NAME}' "
                "AND NOT tgisinternal")).scalar()
        return bool(n)
    return False


def verify_event_immutability(engine: Engine) -> None:
    if not event_immutability_triggers_present(engine):
        raise IntegrityError(
            "world_events 不可变触发器缺失（DB 层事件历史不可变被破坏）",
            detail=engine.dialect.name)
    if not event_truncate_protection_present(engine):
        raise IntegrityError(
            "world_events TRUNCATE 保护缺失（PostgreSQL 上历史可被整表清空）",
            detail=engine.dialect.name)
