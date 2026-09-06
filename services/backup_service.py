"""BACKUP_SERVICE（21/22 节）。

- 禁止 Runtime 活跃时用 shutil.copy DB 作为唯一备份方法；
  使用 SQLite 在线备份 API（sqlite3 Connection.backup）。
- 备份后运行 integrity_check；记录元数据行（backup_id/schema 等）到 manifest。
- PRE_MIGRATION_BACKUP：迁移前调用同一入口。
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import Engine, text

from database.base import utcnow
from domain.errors import BackupError
from services.logging_setup import get_logger

log = get_logger("BACKUP")
def _safe_unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass




def _now_iso() -> str:
    return utcnow().isoformat()


def backup_sqlite(engine: Engine, dest_path: Path,
                  meta: dict | None = None) -> dict:
    """在线备份 SQLite（v1 数据库引擎为 SQLite 时适用）。"""
    if not str(engine.url).startswith("sqlite"):
        raise BackupError("当前仅支持 SQLite 在线备份；PG 备份属未来适配点",
                          detail=str(engine.url))
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    backup_id = str(uuid.uuid4())[:12]
    final = dest_path.with_suffix(dest_path.suffix + f".{backup_id}")
    try:
        with engine.connect() as src_conn:
            src = src_conn.connection.driver_connection
            dest_conn = __import__("sqlite3").connect(str(final))
            try:
                src.backup(dest_conn)
            finally:
                dest_conn.close()
        # integrity check（失败即删除残件）
        import sqlite3
        check = sqlite3.connect(str(final)).execute("PRAGMA integrity_check").fetchone()
        if check[0] != "ok":
            raise BackupError("备份完整性检查失败", detail=check)
    except BackupError:
        _safe_unlink(final)
        raise
    except Exception as exc:  # noqa: BLE001
        _safe_unlink(final)
        raise BackupError("备份失败", detail=str(exc)) from exc

    record = {
        "backup_id": backup_id,
        "path": str(final),
        "created_at": _now_iso(),
        **(meta or {}),
    }
    manifest = dest_path.parent / "backup_manifest.jsonl"
    with manifest.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    log.info("backup done %s", final)
    return record


def pre_migration_backup(engine: Engine, backup_dir: Path) -> dict:
    """任何未来 Migration 前调用（22 节）。"""
    return backup_sqlite(engine, backup_dir / "pre_migration_world.db",
                         meta={"kind": "PRE_MIGRATION"})


def integrity_check(engine: Engine) -> str:
    with engine.connect() as conn:
        row = conn.execute(text("PRAGMA integrity_check")).fetchone()
        return str(row[0])
