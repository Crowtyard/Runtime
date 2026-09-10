# -*- coding: utf-8 -*-
"""正式 DB 安全迁移到 AstrBot plugin_data（§7 流程）。

OLD DB → pre-migration backup → integrity_check → checksum → copy to temporary
target → target integrity_check → schema head validation → formal world audit →
atomic promote → 写 authoritative_db.json → 旧 DB 保留 rollback copy（绝不自动删除）。

用法：
  python scripts/migrate_db_to_plugin_data.py \
      --source <old.db> \
      --target-data-dir <data/plugin_data/astrbot_plugin_blessed_land_runtime> \
      [--keep-source-in-place]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

EXPECTED_SCHEMA_HEAD = "d7f9b1c3e5a7"
DB_FILENAME = "blessed_land.sqlite"
MARKER = "authoritative_db.json"

BUSINESS_TABLES = [
    "persons", "population_groups", "settlements", "resource_nodes",
    "tribulations", "world_events", "timeline_entries", "simulation_run",
    "simulation_checkpoints", "narrative_records", "world_state_changes",
    "runtime_lock", "cultural_elements", "ecological_regions", "industries",
    "institutions", "lineages", "system_configuration",
]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sqlite_integrity(path: Path) -> str:
    conn = sqlite3.connect(str(path))
    try:
        return str(conn.execute("PRAGMA integrity_check").fetchone()[0])
    finally:
        conn.close()


def sqlite_head(path: Path) -> str:
    conn = sqlite3.connect(str(path))
    try:
        row = conn.execute(
            "SELECT version_num FROM alembic_version LIMIT 1").fetchone()
        return str(row[0]) if row else "NONE"
    finally:
        conn.close()


def audit_world(path: Path) -> dict:
    conn = sqlite3.connect(str(path))
    try:
        row = conn.execute(
            "SELECT runtime_status, world_seed_version, current_blessed_tick, "
            "last_committed_real_us FROM world_runtime LIMIT 1").fetchone()
        counts = {t: conn.execute(
            f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                  for t in BUSINESS_TABLES}
        return {
            "runtime_status": row[0] if row else None,
            "world_seed_version": row[1] if row else None,
            "current_blessed_tick": row[2] if row else None,
            "last_committed_real_us": row[3] if row else None,
            "entity_counts": counts,
        }
    finally:
        conn.close()


def assert_formal_world_audit(audit: dict, label: str) -> None:
    if audit["runtime_status"] != "NOT_ACTIVATED":
        raise SystemExit(f"{label}: runtime_status != NOT_ACTIVATED: "
                         f"{audit['runtime_status']!r}")
    if audit["world_seed_version"] is not None:
        raise SystemExit(f"{label}: world_seed_version 非 NULL")
    if audit["current_blessed_tick"] is not None:
        raise SystemExit(f"{label}: current_blessed_tick 非 NULL")
    if audit["last_committed_real_us"] is not None:
        raise SystemExit(f"{label}: last_committed_real_us 非 NULL")
    nonzero = {k: v for k, v in audit["entity_counts"].items() if v}
    if nonzero:
        raise SystemExit(f"{label}: 业务表非空: {nonzero}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--target-data-dir", required=True)
    ap.add_argument("--keep-source-in-place", action="store_true",
                    help="旧 DB 原样保留（默认重命名为 rollback copy）")
    args = ap.parse_args()

    source = Path(args.source)
    target_dir = Path(args.target_data_dir)
    if not source.exists():
        raise SystemExit(f"source 不存在: {source}")

    print("[1/9] pre-migration backup + 源库校验")
    if sqlite_integrity(source) != "ok":
        raise SystemExit("源库 integrity_check 失败")
    src_head = sqlite_head(source)
    if src_head != EXPECTED_SCHEMA_HEAD:
        raise SystemExit(f"源库 schema head 异常: {src_head}")
    audit_src = audit_world(source)
    assert_formal_world_audit(audit_src, "源库")
    src_checksum = sha256_file(source)
    print(f"      source integrity=ok head={src_head} checksum={src_checksum[:16]}…")

    backups_dir = source.parent / "backups"
    backups_dir.mkdir(exist_ok=True)
    pre = backups_dir / ("pre_plugin_migration_" + source.name)
    shutil.copyfile(source, pre)
    print(f"      pre-migration backup: {pre}")

    print("[2/9] 复制到临时目标 + 目标校验")
    target_dir.mkdir(parents=True, exist_ok=True)
    staging = target_dir / (DB_FILENAME + ".staging")
    shutil.copyfile(source, staging)
    if sqlite_integrity(staging) != "ok":
        staging.unlink(missing_ok=True)
        raise SystemExit("目标临时库 integrity_check 失败")
    if sqlite_head(staging) != EXPECTED_SCHEMA_HEAD:
        staging.unlink(missing_ok=True)
        raise SystemExit("目标临时库 schema head 校验失败")
    audit_staging = audit_world(staging)
    assert_formal_world_audit(audit_staging, "目标临时库")
    if sha256_file(staging) != src_checksum:
        staging.unlink(missing_ok=True)
        raise SystemExit("目标临时库 checksum 与源库不一致")
    print("      staging integrity=ok head=ok checksum=ok")

    print("[3/9] 原子提升为 authoritative DB")
    final = target_dir / DB_FILENAME
    os.replace(staging, final)

    print("[4/9] 写 authoritative_db.json")
    state_dir = target_dir / "runtime_state"
    state_dir.mkdir(parents=True, exist_ok=True)
    marker = state_dir / MARKER
    marker.write_text(json.dumps({
        "plugin": "astrbot_plugin_blessed_land_runtime",
        "authoritative_db_path": str(final),
        "checksum_sha256": src_checksum,
        "migrated_from": str(source),
        "migrated_at": datetime.now(timezone.utc).isoformat(),
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    print("[5/9] 旧 DB 处理（保留 rollback，绝不自动删除）")
    if args.keep_source_in_place:
        rollback = source
        print(f"      旧 DB 原样保留: {rollback}")
    else:
        rollback = source.with_name(
            source.name + ".rollback_pre_plugin_migration")
        if rollback.exists():
            rollback.unlink()
        os.replace(source, rollback)
        print(f"      旧 DB 重命名为 rollback copy: {rollback}")

    print("[6/9] 最终审计")
    audit_final = audit_world(final)
    assert_formal_world_audit(audit_final, "最终库")
    print("      final:", audit_final["runtime_status"],
          "seed=", audit_final["world_seed_version"],
          "tick=", audit_final["current_blessed_tick"],
          "counts=", audit_final["entity_counts"])
    print(f"      authoritative DB = {final}")
    print(f"      rollback copy    = {rollback}")
    print("MIGRATION_OK")


if __name__ == "__main__":
    main()
