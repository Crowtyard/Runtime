"""BACKUP_SERVICE（21/22 节）。

- 禁止 Runtime 活跃时用 shutil.copy DB 作为唯一备份方法；
  使用 SQLite 在线备份 API（sqlite3 Connection.backup），WAL 状态下内容一致。
- 备份后运行 integrity_check；记录元数据行（backup_id/schema 等）到 manifest。
- PRE_MIGRATION_BACKUP：迁移前调用同一入口。
- RESTORE：restore_from_backup 做安全替换（清 -wal/-shm 副产物）+ integrity 验证。
- 全部 PRAGMA/sqlite3 只存在于本 adapter 模块（按 URL 前缀分流，PG 下换实现）。
"""
from __future__ import annotations

import json
import os
import shutil
import uuid
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


def _require_sqlite(engine: Engine, action: str) -> None:
    if not str(engine.url).startswith("sqlite"):
        raise BackupError(f"{action} 当前仅支持 SQLite；PG 备份属未来适配点",
                          detail=str(engine.url))


def _sqlite_file_of(engine: Engine) -> Path:
    return Path(str(engine.url).removeprefix("sqlite:///"))


def backup_sqlite(engine: Engine, dest_path: Path,
                  meta: dict | None = None) -> dict:
    """在线备份 SQLite（v1 数据库引擎为 SQLite 时适用）。"""
    _require_sqlite(engine, "在线备份")
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


def restore_from_backup(engine: Engine, backup_path: Path) -> Path:
    """从备份文件安全恢复 SQLite DB。

    流程：释放引擎连接 → 清除旧库 -wal/-shm 副产物 → 原子替换主库文件 →
    重新打开做 integrity_check。WAL 状态下同样安全。
    """
    _require_sqlite(engine, "恢复")
    backup_path = Path(backup_path)
    if not backup_path.exists():
        raise BackupError("备份文件不存在", detail=str(backup_path))
    engine.dispose()
    db_path = _sqlite_file_of(engine)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    for sidecar in (
        db_path.parent / (db_path.name + "-wal"),
        db_path.parent / (db_path.name + "-shm"),
    ):
        _safe_unlink(sidecar)
    tmp = db_path.with_name(db_path.name + ".restoring")
    try:
        shutil.copyfile(backup_path, tmp)
        os.replace(tmp, db_path)  # 同卷原子替换（Windows/Unix 皆可）
    except Exception as exc:  # noqa: BLE001
        _safe_unlink(tmp)
        raise BackupError("恢复替换失败", detail=str(exc)) from exc
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    try:
        check = conn.execute("PRAGMA integrity_check").fetchone()
    finally:
        conn.close()
    if check[0] != "ok":
        raise BackupError("恢复后完整性检查失败", detail=check)
    log.info("restore done %s", db_path)
    return db_path


def pre_migration_backup(engine: Engine, backup_dir: Path) -> dict:
    """任何未来 Migration 前调用（22 节）。"""
    return backup_sqlite(engine, backup_dir / "pre_migration_world.db",
                         meta={"kind": "PRE_MIGRATION"})


def integrity_check(engine: Engine) -> str:
    _require_sqlite(engine, "PRAGMA integrity_check")
    with engine.connect() as conn:
        row = conn.execute(text("PRAGMA integrity_check")).fetchone()
        return str(row[0])
