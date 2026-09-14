# -*- coding: utf-8 -*-
"""PRE-M6 PG-006：world_events 在 PostgreSQL 上的 TRUNCATE 不可变保护。

- SQLite 无 TRUNCATE 语句 → 新 migration（f2a7c4e9b1d6）必须为 **no-op**，
  既有 UPDATE/DELETE 触发器与行为完全不变；
- PostgreSQL 必须存在**语句级 BEFORE TRUNCATE** 触发器（行级触发器不拦 TRUNCATE）；
- alembic 单头链与三处 head 常量必须一致（防止 head 漂移）。
"""
from __future__ import annotations

import ast
import re

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from XiaoguangBlessedLandRuntime.database.invariants import (
    MODIFY_TRIGGER_NAME, TRUNCATE_TRIGGER_NAME,
    event_immutability_triggers_present, event_truncate_protection_present,
    verify_event_immutability)
from XiaoguangBlessedLandRuntime.domain.errors import IntegrityError
from XiaoguangBlessedLandRuntime.services.repositories import EventRepository

from tests.conftest import HEAD_REVISION, PROJECT_ROOT, W
# 单一来源的 PG 集成守卫（库名必须含 "test" 且非 sqlite，否则 fail-closed）；
# 其自身行为由本模块复用 + 该模块的 test_pg_dsn_guard_* 断言。
from tests.test_pg_recovery_checkpoint_portability import _pg_dsn_or_skip

NEW_HEAD = "a9d4f2b7c1e8"      # pg_widen_tribulation_decision_policy
PREV_HEAD = "f2a7c4e9b1d6"     # pg truncate immutability（NEW_HEAD 的前一修订）
MIGRATION = (PROJECT_ROOT / "database" / "alembic" / "versions"
             / "f2a7c4e9b1d6_p1_pg_event_truncate_immutability.py")


def _script_directory() -> ScriptDirectory:
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location",
                        str(PROJECT_ROOT / "database" / "alembic"))
    return ScriptDirectory.from_config(cfg)


# --------------------------------------------------------------- alembic 链
def test_alembic_chain_has_single_head_at_new_revision():
    sd = _script_directory()
    assert sd.get_heads() == [NEW_HEAD]
    assert NEW_HEAD in sd.get_revision(PREV_HEAD).nextrev


def test_head_constants_consistent_across_runtime_and_scripts():
    assert HEAD_REVISION == NEW_HEAD  # tests/conftest.py
    for rel in ("plugin_shell/runtime_host.py",
                "scripts/migrate_db_to_plugin_data.py"):
        src = (PROJECT_ROOT / rel).read_text(encoding="utf-8")
        m = re.search(r'EXPECTED_SCHEMA_HEAD\s*=\s*"([0-9a-f]+)"', src)
        assert m is not None, f"{rel} 缺少 EXPECTED_SCHEMA_HEAD"
        assert m.group(1) == NEW_HEAD, f"{rel} head 漂移: {m.group(1)}"


# --------------------------------------------------------- migration 静态面
def test_migration_declares_expected_chain():
    src = MIGRATION.read_text(encoding="utf-8")
    assert re.search(r"revision:\s*str\s*=\s*'f2a7c4e9b1d6'", src)
    assert re.search(r"down_revision[^=]*=\s*'d7f9b1c3e5a7'", src)


def test_migration_pg_branch_is_statement_level_truncate_trigger():
    src = MIGRATION.read_text(encoding="utf-8")
    assert "BEFORE TRUNCATE" in src
    assert "FOR EACH STATEMENT" in src          # 行级触发器不拦 TRUNCATE
    assert "CREATE TRIGGER {TRUNCATE_TRIGGER}" in src   # f-string DDL 模板
    assert "LANGUAGE plpgsql" in src
    assert "RAISE EXCEPTION" in src
    # 迁移内触发器常量与 invariants 校验名必须一致（防名称漂移使校验失效）
    m = re.search(r'TRUNCATE_TRIGGER\s*=\s*"([^"]+)"', src)
    assert m is not None and m.group(1) == TRUNCATE_TRIGGER_NAME


def test_migration_sqlite_branch_is_noop():
    """SQLite 分支必须只有 return（不得建表/改表/建触发器）。"""
    tree = ast.parse(MIGRATION.read_text(encoding="utf-8"))
    upgrade = next(n for n in tree.body
                   if isinstance(n, ast.FunctionDef) and n.name == "upgrade")
    sqllite_branches = [
        n for n in ast.walk(upgrade)
        if isinstance(n, ast.If)
        and "sqlite" in ast.dump(n.test).lower()]
    assert sqllite_branches, "migration 缺少显式 sqlite 分支"
    for branch in sqllite_branches:
        assert len(branch.body) == 1 and isinstance(branch.body[0], ast.Return), \
            "SQLite 分支必须是 no-op"


def test_invariants_truncate_check_is_pg_gated_and_targets_trigger():
    src = (PROJECT_ROOT / "database" / "invariants.py").read_text(encoding="utf-8")
    assert TRUNCATE_TRIGGER_NAME in src
    assert "pg_trigger" in src
    assert MODIFY_TRIGGER_NAME != TRUNCATE_TRIGGER_NAME
    tree = ast.parse(src)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
              and n.name == "event_truncate_protection_present")
    sqlite_branch = [n for n in ast.walk(fn) if isinstance(n, ast.If)
                     and "sqlite" in ast.dump(n.test).lower()]
    assert sqlite_branch, "SQLite 分支缺失（SQLite 无 TRUNCATE，应恒为在位）"


# ------------------------------------------------------------- SQLite 行为
def test_sqlite_head_advanced_and_triggers_unchanged(migrated_db):
    with migrated_db["engine"].connect() as c:
        assert c.execute(text("SELECT version_num FROM alembic_version")).scalar() \
            == NEW_HEAD
        triggers = {r[0] for r in c.execute(text(
            "SELECT name FROM sqlite_master WHERE type='trigger' "
            "AND tbl_name='world_events'"))}
    assert triggers == {"blr_world_events_no_update", "blr_world_events_no_delete"}


def test_sqlite_update_delete_rejected_and_insert_allowed(seeded_session_factory):
    with seeded_session_factory() as s:
        EventRepository(s).append(world_id=W, event_type="PG6", source="SIM",
                                  blessed_tick=1)
        s.commit()
        engine = s.get_bind()
    with engine.connect() as c:
        with pytest.raises(sa.exc.IntegrityError):
            c.execute(text("UPDATE world_events SET event_type='MUT'"))
        with pytest.raises(sa.exc.IntegrityError):
            c.execute(text("DELETE FROM world_events"))
    with seeded_session_factory() as s:
        EventRepository(s).append(world_id=W, event_type="PG6B", source="SIM",
                                  blessed_tick=2)
        s.commit()


def test_sqlite_has_no_truncate_statement(migrated_db):
    """SQLite 无 TRUNCATE 语句 → 该攻击面在 SQLite 上不存在（migration no-op 的依据）。"""
    with migrated_db["engine"].connect() as c:
        with pytest.raises(sa.exc.OperationalError):
            c.execute(text("TRUNCATE TABLE world_events"))


def test_truncate_protection_present_and_verify_passes_on_sqlite(migrated_db):
    engine = migrated_db["engine"]
    assert event_immutability_triggers_present(engine) is True
    assert event_truncate_protection_present(engine) is True
    verify_event_immutability(engine)  # 不抛异常（SQLite 行为与扩展前一致）


def test_new_migration_downgrade_upgrade_cycle(migrated_db):
    """新 migration 自身的 downgrade/upgrade 往返（SQLite 两侧均为 no-op）。"""
    from alembic import command

    from XiaoguangBlessedLandRuntime.services.db_lifecycle import (
        build_embedded_migration_config)

    cfg = build_embedded_migration_config(migrated_db["url"],
                                          project_root=PROJECT_ROOT)
    command.downgrade(cfg, PREV_HEAD)
    with migrated_db["engine"].connect() as c:
        assert c.execute(text("SELECT version_num FROM alembic_version")).scalar() \
            == PREV_HEAD
        triggers = {r[0] for r in c.execute(text(
            "SELECT name FROM sqlite_master WHERE type='trigger' "
            "AND tbl_name='world_events'"))}
        assert triggers == {"blr_world_events_no_update", "blr_world_events_no_delete"}
    command.upgrade(cfg, "head")
    with migrated_db["engine"].connect() as c:
        assert c.execute(text("SELECT version_num FROM alembic_version")).scalar() \
            == NEW_HEAD
    verify_event_immutability(migrated_db["engine"])


# ------------------------------------------- PG 分支逻辑（stub engine，无需 PG）
class _StubResult:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value

    def fetchall(self):
        return [("t1",), ("t2",)] if self._value else []


class _StubConn:
    def __init__(self, value):
        self._value = value

    def execute(self, *_a, **_k):
        return _StubResult(self._value)

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


class _StubEngine:
    """最小 engine 替身：dialect.name + 按次消费的查询返回值。"""

    def __init__(self, dialect_name: str, values: list | None = None):
        self.dialect = type("D", (), {"name": dialect_name})()
        self._values = list(values or [])

    def connect(self):
        value = self._values.pop(0) if self._values else 0
        return _StubConn(value)


def test_pg_branch_requires_truncate_trigger(monkeypatch):
    """PG：pg_trigger 计数为 0 → 保护缺失；为 1 → 在位。"""
    assert event_truncate_protection_present(_StubEngine("postgresql", [0])) is False
    assert event_truncate_protection_present(_StubEngine("postgresql", [1])) is True


def test_pg_verify_fails_closed_without_truncate_trigger():
    """PG：UPDATE/DELETE 触发器在位但 TRUNCATE 触发器缺失 → 必须 fail-closed。"""
    with pytest.raises(IntegrityError) as exc:
        verify_event_immutability(_StubEngine("postgresql", [1, 0]))
    assert "TRUNCATE" in str(exc.value)
    # 两者都在位 → 通过（不抛）
    verify_event_immutability(_StubEngine("postgresql", [1, 1]))


def test_unknown_dialect_fails_closed():
    assert event_immutability_triggers_present(_StubEngine("mysql")) is False
    assert event_truncate_protection_present(_StubEngine("mysql")) is False


def test_sqlite_truncate_check_never_queries_db():
    """SQLite：无 TRUNCATE 语句 → 恒为 True，且不发起查询（行为与扩展前一致）。"""
    engine = _StubEngine("sqlite", [])
    assert event_truncate_protection_present(engine) is True
    assert engine._values == []


# ------------------------------------------- PG-006 真实 PostgreSQL 集成入口
def _attack_blocked(engine, sql: str, *, op: str) -> None:
    """单次攻击：必须使用独立连接。

    PostgreSQL 中出错即中止当前事务（InFailedSqlTransaction），
    同一连接上连续攻击无法区分「被触发器拒绝」与「事务已中止」。
    """
    with engine.connect() as c:
        with pytest.raises(sa.exc.DatabaseError) as exc:
            c.execute(text(sql))
    msg = str(exc.value)
    assert "append-only" in msg, msg
    assert op in msg, msg


def _purge_world(engine, world_id: str) -> None:
    """测试数据清理：以受控 DDL 暂停行级不可变触发器后按 world 删除。

    事件不可变的解除只能走 DDL + 受控运维流程（契约 §8）——测试清理即走该路径；
    ALTER/DELETE 在同一事务内完成（ACCESS EXCLUSIVE 锁），其他会话始终看到完整保护，
    提交前重新 ENABLE 触发器。
    """
    with engine.begin() as c:
        c.execute(text("LOCK TABLE world_events IN ACCESS EXCLUSIVE MODE"))
        c.execute(text("ALTER TABLE world_events DISABLE TRIGGER "
                       "blr_world_events_no_modify"))
        c.execute(text("DELETE FROM world_events WHERE world_id = :w"), {"w": world_id})
        c.execute(text("ALTER TABLE world_events ENABLE TRIGGER "
                       "blr_world_events_no_modify"))
        c.execute(text("DELETE FROM world_runtime WHERE world_id = :w"), {"w": world_id})


def test_pg_truncate_protection_integration_entrypoint():
    """PG-006 真实 PG：INSERT 允许，UPDATE / DELETE / TRUNCATE 全部被 DB 层拒绝。

    仅当 BLR_TEST_PG_DSN（库名必须含 "test"）+ BLR_TEST_PG_ALLOW=1 时执行；
    合成 world + 合成事件，用后清理；不触碰任何正式世界 / 正式库 / live plugin_data。
    """
    dsn = _pg_dsn_or_skip()
    from XiaoguangBlessedLandRuntime.database.db import (
        create_db_engine, make_session_factory)
    from XiaoguangBlessedLandRuntime.services.db_lifecycle import (
        migrate_database)
    from XiaoguangBlessedLandRuntime.services.repositories import (
        RuntimeRepository)

    migrate_database(dsn, project_root=PROJECT_ROOT)
    engine = create_db_engine(dsn)
    factory = make_session_factory(engine)
    world_id = "PG-TEST-PG006-0001"
    try:
        # 触发器在位（DB 层自证，不是代码约定）
        assert event_immutability_triggers_present(engine) is True
        assert event_truncate_protection_present(engine) is True
        verify_event_immutability(engine)

        _purge_world(engine, world_id)      # 幂等：清理上次中断运行的残留

        with factory() as s:
            RuntimeRepository(s).create_not_activated(
                world_id=world_id, world_bible_version="1.0",
                simulation_version="0.1.0-dev",
                world_bible_manifest_hash="pg006")
            s.commit()

        # append-only 语义：INSERT 允许
        with factory() as s:
            EventRepository(s).append(world_id=world_id, event_type="PG6",
                                      source="SIM", blessed_tick=1)
            EventRepository(s).append(world_id=world_id, event_type="PG6B",
                                      source="SIM", blessed_tick=2)
            s.commit()
        with factory() as s:
            inserted = s.execute(text(
                "SELECT COUNT(*) FROM world_events WHERE world_id = :w"),
                {"w": world_id}).scalar()
        assert inserted == 2

        # 攻击面：UPDATE / DELETE / TRUNCATE 必须全部被 DB 层拒绝
        _attack_blocked(engine, "UPDATE world_events SET event_type = 'MUT'",
                        op="UPDATE")
        _attack_blocked(engine, "DELETE FROM world_events", op="DELETE")
        _attack_blocked(engine, "TRUNCATE TABLE world_events", op="TRUNCATE")

        # 攻击之后数据未被改动（TRUNCATE 未生效、历史未被清空）
        with factory() as s:
            survived = s.execute(text(
                "SELECT COUNT(*) FROM world_events WHERE world_id = :w"),
                {"w": world_id}).scalar()
        assert survived == 2
        verify_event_immutability(engine)
    finally:
        _purge_world(engine, world_id)
        # 清理后保护必须仍在位（ENABLE 生效，未被测试清理静默削弱）
        verify_event_immutability(engine)
        engine.dispose()
