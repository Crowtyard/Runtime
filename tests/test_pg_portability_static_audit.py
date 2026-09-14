# -*- coding: utf-8 -*-
"""PRE-M6 PG-002：全生产路径 PostgreSQL portability 静态门禁。

原 ``test_ta59_postgresql_contract_audit`` 只扫描 3 个 simulation 文件，
漏掉了 ``services/simulation/recovery.py`` 的 ``json_extract``（PG-001）。
本文件把审计扩到全部授权生产路径，并要求 SQLite 专有构造只能出现在
**显式方言分支**内（tests/pg_portability_scan.py）。
"""
from __future__ import annotations

import ast
from pathlib import Path

from tests.pg_portability_scan import (ALLOWLIST, ALLOWLIST_GUARDS,
                                       PROJECT_ROOT, production_files,
                                       scan_file, scan_repository, scan_source)

RECOVERY = PROJECT_ROOT / "services" / "simulation" / "recovery.py"
BACKUP_SERVICE = PROJECT_ROOT / "services" / "backup_service.py"

#: 覆盖面的最小期望集合（权威生产文件必须被扫到）
REQUIRED_COVERAGE = {
    "main.py",
    "database/db.py",
    "database/invariants.py",
    "database/models_core.py",
    "services/backup_service.py",
    "services/fencing.py",
    "services/writer_lock.py",
    "services/history/service.py",
    "services/simulation/coordinator.py",
    "services/simulation/recovery.py",
    "services/scheduler/core.py",
    "plugin_shell/runtime_host.py",
}


def test_no_sqlite_only_sql_in_production_paths():
    violations, scanned = scan_repository()
    assert scanned >= 80, f"扫描面过小（{scanned} 个文件），覆盖可能失效"
    assert violations == [], "\n".join(str(v) for v in violations)


def test_scan_covers_authoritative_paths():
    rels = {str(p.relative_to(PROJECT_ROOT)).replace("\\", "/")
            for p in production_files()}
    assert REQUIRED_COVERAGE <= rels, sorted(REQUIRED_COVERAGE - rels)
    # migrations 属生产面（方言分支必须显式）
    assert any(r.startswith("database/alembic/versions/") for r in rels)
    # 排除面不得混入
    assert not any(r.startswith(("tests/", "docs/", "scripts/")) for r in rels)


def test_scanner_flags_pg001_shape_unguarded_json_extract():
    """扫描器必须能抓到 PG-001 的真实代码形态（否则门禁是空的）。"""
    old_code = (
        "from sqlalchemy import select, text\n"
        "def f(session, world_id):\n"
        "    return session.execute(\n"
        "        select(C)\n"
        "        .where(C.world_id == world_id,\n"
        "               C.complete.is_(True),\n"
        "               text(\"json_extract(meta, '$.checkpoint_kind') = \"\n"
        "                    f\"'{KIND}'\"))\n"
        "    ).scalar_one_or_none()\n"
    )
    found = scan_source(old_code, path="<pg001-shape>")
    assert "json_extract" in {v.token for v in found}


def test_scanner_flags_other_sqlite_only_constructs():
    cases = {
        "PRAGMA": 'q = "PRAGMA journal_mode=WAL"\n',
        "sqlite_master": 'q = "SELECT name FROM sqlite_master WHERE type=\'table\'"\n',
        "INSERT OR REPLACE": 'q = "INSERT OR REPLACE INTO t (a) VALUES (1)"\n',
        "AUTOINCREMENT": 'q = "id INTEGER PRIMARY KEY AUTOINCREMENT"\n',
        "rowid": 'q = "SELECT * FROM t ORDER BY rowid"\n',
        "strftime(": 'q = "SELECT strftime(\'%Y\', real_time) FROM t"\n',
        "datetime(": 'q = "SELECT datetime(\'now\')"\n',
        "WITHOUT ROWID": 'q = "CREATE TABLE t (a INT) WITHOUT ROWID"\n',
        "RAISE(...)": 'q = "SELECT RAISE(ABORT, \'no\')"\n',
        "json_each": 'q = "SELECT * FROM json_each(meta)"\n',
    }
    for token, snippet in cases.items():
        found = {v.token for v in scan_source(snippet, path=f"<{token}>")}
        assert token in found, f"{token} 未被捕获: {sorted(found)}"


def test_scanner_allows_explicit_dialect_branch():
    """契约 §2/§7 许可的 adapter 形态：显式 sqlite 分支内的方言 SQL。"""
    ok_equals = ('if dialect == "sqlite":\n'
                 '    q = "PRAGMA integrity_check"\n')
    assert scan_source(ok_equals, path="<ok-equals>") == []
    ok_startswith = ('if url.startswith("sqlite"):\n'
                     '    @event.listens_for(engine, "connect")\n'
                     '    def _pragmas(conn, _rec):\n'
                     '        conn.execute("PRAGMA busy_timeout=30000")\n')
    assert scan_source(ok_startswith, path="<ok-startswith>") == []
    ok_call = ('if op.get_bind().dialect.name == "sqlite":\n'
               '    op.execute("CREATE TRIGGER t BEFORE DELETE ON x BEGIN SELECT RAISE(ABORT, \'no\'); END")\n')
    assert scan_source(ok_call, path="<ok-op>") == []
    # 同一构造若落在 PG 分支 / 无分支处，必须被捕获
    outside = ('if dialect == "postgresql":\n'
               '    q = "PRAGMA integrity_check"\n')
    assert [v.token for v in scan_source(outside, path="<outside>")] == ["PRAGMA"]
    top_level = 'q = "PRAGMA integrity_check"\n'
    assert [v.token for v in scan_source(top_level, path="<top>")] == ["PRAGMA"]


def test_scanner_ignores_comments_and_docstrings():
    doc = ('"""说明：禁止在生产 SQL 里使用 json_extract / PRAGMA / rowid。"""\n'
           "# 注释：历史实现曾用 json_extract(meta, '$.kind')\n"
           "VALUE = 1\n")
    assert scan_source(doc, path="<doc>") == []


def test_recovery_module_is_portable_and_free_of_raw_sql():
    """PG-001 回归：recovery 模块无 SQLite 专有 SQL，且不回退到手写 SQL。"""
    assert scan_file(RECOVERY) == []
    tree = ast.parse(RECOVERY.read_text(encoding="utf-8"))
    # 使用 SQLAlchemy 可移植的 JSON 比较（SQLite→JSON_EXTRACT、PG→->>）
    assert any(isinstance(n, ast.Call)
               and isinstance(n.func, ast.Attribute)
               and n.func.attr == "as_string" for n in ast.walk(tree))
    # 不得回退到手写 SQL（sqlalchemy.text 导入 / text(...) 调用）
    imported = {alias.name for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom) for alias in node.names}
    assert "text" not in imported
    assert not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                   and n.func.id == "text" for n in ast.walk(tree))


def test_allowlist_is_minimal_and_guarded():
    assert set(ALLOWLIST) == {"services/backup_service.py"}
    for rel, tokens in ALLOWLIST_GUARDS.items():
        src = (PROJECT_ROOT / rel).read_text(encoding="utf-8")
        for token in tokens:
            assert token in src, f"{rel} 缺少白名单防护符号: {token}"
    # 白名单模块本身确实命中方言 SQL（否则白名单没有存在意义）
    assert scan_file(BACKUP_SERVICE), "白名单模块不应为空命中"
