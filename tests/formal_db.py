# -*- coding: utf-8 -*-
"""正式库（formal ``blessed_land.sqlite``）只读访问与 canonical 状态断言。

**CANONICAL CONTRACT（owner 2026-09-14 裁决，production 语义不得更改）**

```
world_runtime 0 行  ==  官方世界从未激活（NOT_ACTIVATED 的唯一 canonical 表示）
```

- **不得**为了让测试通过而向正式库 INSERT 一行 ``runtime_status='NOT_ACTIVATED'``；
- 「世界未激活」的断言必须写成 **行数 == 0**，而不是「存在一行 runtime_status=NOT_ACTIVATED」；
- 所有正式库连接必须**显式只读**（``file:...?mode=ro``，``uri=True``）：绝不写、
  绝不创建 ``-journal``/``-wal`` 副产物，因而「测试前后 SHA256 一致」才是有效证据；
- 本 helper 是全部 explicit formal-db guard 测试的单一来源，用于消除
  ``PRE_M6_TECH_DEBT = FORMAL_DB_NOT_ACTIVATED_REPRESENTATION_CONSISTENCY``。

口径修正历史：早期 6 处 guard 假设「正式库存在一行 NOT_ACTIVATED」，
在 canonical 0 行下 `fetchone()` 返回 None → `TypeError`/断言失败；
现统一为 row-count 断言。
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

#: 「官方世界未激活」时应当为空的核心表（canonical 快照口径）
CORE_EMPTY_TABLES: tuple[str, ...] = (
    "world_runtime", "world_events", "simulation_run", "runtime_lock",
    "time_ratio_history", "simulation_checkpoints", "persons",
    "population_groups", "settlements", "resource_nodes", "tribulations",
    "timeline_entries", "world_state_changes",
)


def formal_db_path() -> Path | None:
    """BLR_FORMAL_DB_PATH（未设置或不存在 → None）。"""
    raw = os.environ.get("BLR_FORMAL_DB_PATH", "")
    if not raw:
        return None
    path = Path(raw)
    return path if path.exists() else None


def readonly_connect(path: str | Path) -> sqlite3.Connection:
    """正式库**只读**连接（绝不写、绝不建 sidecar）。"""
    return sqlite3.connect(f"file:{Path(path)}?mode=ro", uri=True, timeout=10)


def sha256_of(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def world_runtime_rows(conn: sqlite3.Connection) -> int:
    """官方世界行数：**0 = 从未激活**（canonical）。"""
    return int(conn.execute("SELECT COUNT(*) FROM world_runtime").fetchone()[0])


def assert_unactivated_canonical(conn: sqlite3.Connection) -> None:
    """canonical 未激活断言：world_runtime **0 行**。"""
    rows = world_runtime_rows(conn)
    assert rows == 0, (
        "canonical NOT_ACTIVATED 表示 = world_runtime 0 行；"
        f"实际 {rows} 行 —— 正式库被写入或口径被破坏")


def assert_tables_empty(conn: sqlite3.Connection,
                        tables: tuple[str, ...] = CORE_EMPTY_TABLES) -> None:
    """所列表必须为空（表不存在则跳过 —— schema 版本差异允许）。"""
    existing = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    for table in tables:
        if table in existing:
            n = int(conn.execute(
                f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
            assert n == 0, f"正式库表 {table} 非空: {n}"


def integrity_ok(conn: sqlite3.Connection) -> bool:
    return str(conn.execute("PRAGMA integrity_check").fetchone()[0]) == "ok"


def alembic_head(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT version_num FROM alembic_version LIMIT 1").fetchone()
    return row[0] if row else None


def snapshot(path: str | Path | None = None) -> dict:
    """正式库 canonical 只读快照（供报告与 guard 取证）。"""
    p = Path(path) if path else formal_db_path()
    if p is None:
        return {"available": False}
    with readonly_connect(p) as conn:
        existing = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        counts = {}
        for table in CORE_EMPTY_TABLES:
            if table in existing:
                counts[table] = int(conn.execute(
                    f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
        rows = world_runtime_rows(conn)
        tick = None
        if rows:
            tick = conn.execute(
                "SELECT current_blessed_tick FROM world_runtime LIMIT 1"
            ).fetchone()[0]
        return {
            "available": True, "path": str(p),
            "sha256": sha256_of(p),
            "size_bytes": p.stat().st_size,
            "tables": len(existing),
            "alembic_head": alembic_head(conn),
            "world_runtime_rows": rows,
            "current_blessed_tick": tick,
            "official_counts": counts,
            "integrity": integrity_ok(conn),
        }
