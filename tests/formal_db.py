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
import json
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

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


# ==========================================================================
# M6C.1B — AUTHORITATIVE DB RESOLUTION（owner §2/§4/§5/§6）
#
# 权威契约（既有生产架构，本文件只是**只读**消费者）：
#   plugin_shell/paths.py:15            AUTHORITATIVE_MARKER = "authoritative_db.json"
#   plugin_shell/runtime_host.py:212-225 Runtime 启动时写出
#       <plugin_data>/runtime_state/authoritative_db.json =
#       {plugin, authoritative_db_path, checksum_sha256, written_at}
#   → 「正式库」= 该 marker 指向的 DB，**不是**磁盘上任意 blessed_land.sqlite。
#
# 硬规则：
#   * 不得按"第一个 / 最新 mtime / 固定路径"选库（owner §5）；
#   * 无权威元数据却有候选 → AMBIGUOUS；
#   * 权威元数据自相矛盾（checksum 不符 / 路径越界 / 显式覆盖与 marker 冲突）→ AMBIGUOUS；
#   * AMBIGUOUS → FAIL CLOSED：不得执行 activation / materialization / formal mutation。
# ==========================================================================
AUTHORITATIVE_MARKER = "authoritative_db.json"
DB_FILENAME = "blessed_land.sqlite"
RUNTIME_STATE_DIRNAME = "runtime_state"

RESOLVED = "RESOLVED"
ABSENT = "ABSENT"
AMBIGUOUS = "AMBIGUOUS"

_DISCOVERY_MAX_DEPTH = 6


class AuthoritativeDbAmbiguous(RuntimeError):
    """AUTHORITATIVE_DB_RESOLUTION = AMBIGUOUS → FAIL CLOSED。"""


@dataclass(frozen=True)
class DbResolution:
    """权威库解析结果（只读；不含任何写入能力）。"""

    state: str
    path: Path | None
    reason: str
    candidates: tuple[Path, ...] = ()
    non_authoritative: tuple[Path, ...] = ()
    marker_path: Path | None = None
    marker: dict | None = None
    checksum_matches: bool | None = None


def marker_path_for(plugin_data_dir: str | Path) -> Path:
    return Path(plugin_data_dir) / RUNTIME_STATE_DIRNAME / AUTHORITATIVE_MARKER


def read_marker(plugin_data_dir: str | Path) -> dict | None:
    marker = marker_path_for(plugin_data_dir)
    if not marker.exists():
        return None
    try:
        return json.loads(marker.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def discover_dbs(roots: Iterable[str | Path],
                 *, max_depth: int = _DISCOVERY_MAX_DEPTH) -> tuple[Path, ...]:
    """在给定根目录下**发现**所有 blessed_land.sqlite（只用于检测，不用于选择）。"""
    found: list[Path] = []
    for root in roots:
        base = Path(root)
        if not base.is_dir():
            continue
        base_depth = len(base.parts)
        for path in base.rglob(DB_FILENAME):
            if len(path.parts) - base_depth > max_depth:
                continue
            if path.is_file():
                found.append(path)
    return tuple(sorted(set(found)))


def resolve_authoritative_db(*, plugin_data_dir: str | Path | None = None,
                             extra_roots: Iterable[str | Path] = (),
                             explicit_path: str | Path | None = None
                             ) -> DbResolution:
    """按权威元数据解析正式库；无法唯一确定 → AMBIGUOUS（FAIL CLOSED）。"""
    roots: list[Path] = []
    if plugin_data_dir is not None:
        roots.append(Path(plugin_data_dir))
    roots.extend(Path(r) for r in extra_roots)
    candidates = discover_dbs(roots)

    # (1) 显式覆盖（BLR_FORMAL_DB_PATH 等）：只接受"存在且与 marker 不冲突"的路径
    if explicit_path is not None:
        path = Path(explicit_path)
        if not path.is_file():
            return DbResolution(AMBIGUOUS, None,
                                f"explicit formal DB path does not exist: {path}",
                                candidates=candidates)
        marker = read_marker(plugin_data_dir) if plugin_data_dir is not None else None
        if marker is not None:
            marker_db = marker.get("authoritative_db_path")
            if marker_db is not None and Path(marker_db) != path:
                return DbResolution(
                    AMBIGUOUS, None,
                    "explicit formal DB path conflicts with authoritative marker: "
                    f"{path} != {marker_db}", candidates=candidates,
                    marker_path=marker_path_for(plugin_data_dir) if plugin_data_dir
                    else None, marker=marker)
        non_auth = tuple(p for p in candidates if p != path)
        return DbResolution(RESOLVED, path, "explicit path (validated)",
                            candidates=candidates, non_authoritative=non_auth,
                            marker=marker)

    # (2) 权威标记（生产架构的唯一权威来源）
    if plugin_data_dir is not None:
        marker = read_marker(plugin_data_dir)
        if marker is None:
            if candidates:
                return DbResolution(
                    AMBIGUOUS, None,
                    f"{len(candidates)} blessed_land.sqlite candidate(s) found under "
                    "the discovery roots but no authoritative marker exists → "
                    "cannot uniquely determine the formal DB",
                    candidates=candidates)
            return DbResolution(ABSENT, None, "no marker and no candidate",
                                candidates=candidates)
        raw = marker.get("authoritative_db_path")
        if not raw:
            return DbResolution(AMBIGUOUS, None,
                                "authoritative marker lacks authoritative_db_path",
                                candidates=candidates,
                                marker_path=marker_path_for(plugin_data_dir),
                                marker=marker)
        path = Path(raw)
        if not path.is_file():
            return DbResolution(AMBIGUOUS, None,
                                f"authoritative marker points at a missing file: {path}",
                                candidates=candidates,
                                marker_path=marker_path_for(plugin_data_dir),
                                marker=marker)
        base = Path(plugin_data_dir).resolve()
        if base not in path.resolve().parents and path.resolve() != base:
            return DbResolution(AMBIGUOUS, None,
                                f"authoritative marker path escapes plugin_data scope: "
                                f"{path}", candidates=candidates,
                                marker_path=marker_path_for(plugin_data_dir),
                                marker=marker)
        checksum_matches: bool | None = None
        expected = marker.get("checksum_sha256")
        if expected:
            actual = sha256_of(path)
            checksum_matches = (actual == expected)
            if not checksum_matches:
                return DbResolution(AMBIGUOUS, None,
                                    "authoritative marker checksum mismatch "
                                    f"(marker={expected[:16]}… actual={actual[:16]}…)",
                                    candidates=candidates,
                                    marker_path=marker_path_for(plugin_data_dir),
                                    marker=marker, checksum_matches=False)
        non_auth = tuple(p for p in candidates if p != path)
        return DbResolution(RESOLVED, path, "authoritative marker",
                            candidates=candidates, non_authoritative=non_auth,
                            marker_path=marker_path_for(plugin_data_dir),
                            marker=marker, checksum_matches=checksum_matches)

    # (3) 只有发现根、没有权威元数据 → 不许猜
    if len(candidates) == 1:
        return DbResolution(AMBIGUOUS, None,
                            "single candidate found but no authoritative metadata → "
                            "selection by path/mtime is forbidden", candidates=candidates)
    if candidates:
        return DbResolution(AMBIGUOUS, None,
                            f"{len(candidates)} candidates and no authoritative metadata",
                            candidates=candidates)
    return DbResolution(ABSENT, None, "no candidates", candidates=candidates)


def _world_runtime_rows_or_none(path: Path) -> int | None:
    with readonly_connect(path) as conn:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if "world_runtime" not in tables:
            return None
        return world_runtime_rows(conn)


def redline_report(*, plugin_data_dir: str | Path | None = None,
                   extra_roots: Iterable[str | Path] = (),
                   explicit_path: str | Path | None = None) -> dict:
    """正式世界红线只读报告。

    * 红线数值**只能**来自权威库（非权威副本不得参与，owner §6）；
    * AMBIGUOUS → raise AuthoritativeDbAmbiguous（FAIL CLOSED，owner §5）。
    """
    res = resolve_authoritative_db(plugin_data_dir=plugin_data_dir,
                                   extra_roots=extra_roots,
                                   explicit_path=explicit_path)
    if res.state == AMBIGUOUS:
        raise AuthoritativeDbAmbiguous(res.reason)
    report: dict = {
        "AUTHORITATIVE_DB_RESOLUTION": "PASS" if res.state == RESOLVED else "ABSENT",
        "AUTHORITATIVE_DB_STATE": res.state,
        "AUTHORITATIVE_DB_REASON": res.reason,
        "AUTHORITATIVE_DB_PATH": str(res.path) if res.path else None,
        "AUTHORITATIVE_MARKER_PATH": str(res.marker_path) if res.marker_path else None,
        "MARKER_CHECKSUM_MATCH": res.checksum_matches,
        "CANDIDATE_DB_COUNT": len(res.candidates),
        "NON_AUTHORITATIVE_DB_DETECTED": bool(res.non_authoritative),
        "NON_AUTHORITATIVE_DBS": [],
        "STALE_DB_FALSE_POSITIVE": 0,
        "FALSE_POSITIVE_ACTIVATED": False,
        "AVAILABLE": res.state == RESOLVED,
    }
    for path in res.non_authoritative:
        try:
            rows = _world_runtime_rows_or_none(path)
        except sqlite3.Error as exc:  # pragma: no cover - 损坏副本
            rows = f"ERROR:{type(exc).__name__}"
        report["NON_AUTHORITATIVE_DBS"].append({
            "path": str(path), "sha256": sha256_of(path),
            "world_runtime_rows": rows, "consulted_for_redline": False,
        })
    if res.state != RESOLVED or res.path is None:
        report.update({"FORMAL_WORLD_RUNTIME_ROWS": None,
                       "FORMAL_WORLD_STATUS": "UNKNOWN_ABSENT",
                       "CURRENT_BLESSED_TICK": None,
                       "FORMAL_DB_SHA256": None})
        return report
    snap = snapshot(res.path)
    rows = snap["world_runtime_rows"]
    report.update({
        "FORMAL_DB_SHA256": snap["sha256"],
        "FORMAL_DB_SIZE_BYTES": snap["size_bytes"],
        "FORMAL_WORLD_RUNTIME_ROWS": rows,
        "FORMAL_WORLD_STATUS": "NOT_ACTIVATED" if rows == 0 else "ACTIVATED",
        "CURRENT_BLESSED_TICK": snap["current_blessed_tick"],
        "ALEMBIC_HEAD": snap["alembic_head"],
        "INTEGRITY": snap["integrity"],
    })
    return report
