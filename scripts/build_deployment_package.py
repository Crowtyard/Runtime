#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""构建 AstrBot 生产部署包（M5.1）。

- zip 根层级直接暴露 metadata.yaml / main.py（AstrBot 上传校验要求）。
- 只包含 Runtime 生产文件；排除 .git / tests / reports / docs / scripts /
  runtime_design / __pycache__ / *.pyc / *.db* / backups / world.db* /
  报告 md / manifests（运行时不需要）。
- 持久数据（world DB / checkpoint / writer lock / runtime state）绝不打包。
- 构建后自校验：METADATA_VISIBLE_AT_EXPECTED_ROOT / MAIN_VISIBLE_AT_EXPECTED_ROOT。

用法：python scripts/build_deployment_package.py [输出 zip 路径]
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PLUGIN_ID = "astrbot_plugin_blessed_land_runtime"

# 显式生产文件集合（避免误打包持久数据/测试/文档）
TOP_FILES = {
    "metadata.yaml", "main.py", "__init__.py", "_conf_schema.json",
    "requirements.txt", "alembic.ini",
}
PACKAGE_DIRS = ("config", "database", "domain", "services",
                "plugin_shell", "pages")
EXCLUDE_SUFFIXES = {".pyc", ".db", ".db-wal", ".db-shm", ".jsonl"}
EXCLUDE_DIR_PARTS = {"__pycache__", ".pytest_cache", ".git", "tests",
                     "reports", "docs", "scripts", "runtime_design",
                     "backups", "stub_astrbot", "baselines"}


def collect() -> list[tuple[str, Path]]:
    entries: list[tuple[str, Path]] = []
    for name in sorted(TOP_FILES):
        p = REPO / name
        if p.exists():
            entries.append((name, p))
    for d in PACKAGE_DIRS:
        base = REPO / d
        for p in sorted(base.rglob("*")):
            if not p.is_file():
                continue
            parts = set(p.relative_to(REPO).parts)
            if parts & EXCLUDE_DIR_PARTS:
                continue
            if p.suffix.lower() in EXCLUDE_SUFFIXES:
                continue
            entries.append((str(p.relative_to(REPO)).replace("\\", "/"), p))
    return entries


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else \
        REPO.parent / f"{PLUGIN_ID}.zip"
    entries = collect()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for arcname, p in entries:
            zf.write(p, arcname)
    # 自校验：metadata/main 在 zip 根
    with zipfile.ZipFile(out, "r") as zf:
        names = set(zf.namelist())
    metadata_ok = "metadata.yaml" in names
    main_ok = "main.py" in names
    nested = any(n.startswith(f"{PLUGIN_ID}/") or n.startswith("repo/")
                 or n.startswith("project/") for n in names)
    forbidden = any(seg in n for n in names for seg in (
        ".git/", "tests/", "__pycache__", ".db", ".pytest_cache"))
    print(f"PACKAGE_PATH = {out}")
    print(f"METADATA_VISIBLE_AT_EXPECTED_ROOT = {metadata_ok}")
    print(f"MAIN_VISIBLE_AT_EXPECTED_ROOT = {main_ok}")
    print(f"NESTED_ROOT = {nested}")
    print(f"FORBIDDEN_CONTENT = {forbidden}")
    print(f"FILE_COUNT = {len(entries)}")
    ok = metadata_ok and main_ok and not nested and not forbidden
    print(f"PACKAGE_STRUCTURE_VALID = {ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
