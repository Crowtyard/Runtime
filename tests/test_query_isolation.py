# -*- coding: utf-8 -*-
"""M5 隔离测试：M5Q37-39 / M5Q49。

- Private Companion 源码零修改/零引用（源码级 + live 目录 checksum 复核，
  live 路径不存在时跳过 checksum 部分）。
- Runtime 更新隔离（只写自己的 plugin_data；不覆盖 companion）。
- Companion 更新隔离（Runtime DB/config 只在自己 plugin_data 下）。
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tests.conftest import PROJECT_ROOT

REPO = PROJECT_ROOT
COMPANION_LIVE_DIR = Path(
    r"C:\Users\Crowtyard\.astrbot_launcher\instances"
    r"\f76fe2fd-8c03-4ba2-b4d6-467d1645ed0d\core\data\plugins"
    r"\astrbot_plugin_private_companion")
BASELINE_FILE = Path(
    r"D:\MY SELF\IKUN\小光\m5_companion_source_baseline.txt")


def test_m5q37_private_companion_source_unchanged():
    """源码级：M5 代码不得 import/patch/写入 Private Companion。"""
    for p in [REPO / "services", REPO / "plugin_shell", REPO / "main.py"]:
        files = [p] if p.is_file() else list(p.rglob("*.py"))
        for py in files:
            src = py.read_text(encoding="utf-8")
            assert "private_companion" not in src, py
    # live 目录存在时：checksum 与开工基线逐字节一致
    if COMPANION_LIVE_DIR.exists():
        entries = []
        for f in sorted(COMPANION_LIVE_DIR.rglob("*")):
            if f.is_file() and f.suffix in (
                    ".py", ".json", ".yaml", ".md", ".txt"):
                rel = str(f.relative_to(COMPANION_LIVE_DIR)).replace(
                    "/", "\\")  # 与基线文件路径格式一致
                entries.append(f"{hashlib.sha256(f.read_bytes()).hexdigest()}"
                               f"  {rel}")
        if BASELINE_FILE.exists():
            # utf-8-sig：基线文件由 PowerShell 写出（可能带 BOM）
            baseline = BASELINE_FILE.read_text(
                encoding="utf-8-sig").splitlines()
            assert "\n".join(entries).splitlines() == baseline


def test_m5q38_runtime_update_isolation():
    """Runtime 只写自己的 plugin_data / 项目目录；无跨插件路径写入。"""
    from XiaoguangBlessedLandRuntime.plugin_shell.paths import \
        resolve_plugin_data_dir
    data_dir = resolve_plugin_data_dir()
    assert "astrbot_plugin_blessed_land_runtime" in str(data_dir)
    for p in [REPO / "services", REPO / "plugin_shell", REPO / "main.py"]:
        files = [p] if p.is_file() else list(p.rglob("*.py"))
        for py in files:
            src = py.read_text(encoding="utf-8")
            for token in ("data/plugins/astrbot_plugin_private_companion",
                          "data\\plugins\\astrbot_plugin_private_companion"):
                assert token not in src, py


def test_m5q39_companion_update_isolation():
    """Runtime 的 DB/状态/配置全部位于自己的 plugin_data 目录（M1.1 既有
    隔离契约），与 companion 数据目录无交集。"""
    from XiaoguangBlessedLandRuntime.plugin_shell.paths import \
        resolve_plugin_data_dir
    from XiaoguangBlessedLandRuntime.plugin_shell.runtime_host import \
        DB_FILENAME, AUTHORITATIVE_MARKER
    data_dir = resolve_plugin_data_dir()
    assert DB_FILENAME == "blessed_land.sqlite"
    assert AUTHORITATIVE_MARKER == "authoritative_db.json"
    assert "companion" not in str(data_dir).lower()


def test_m5q49_no_cross_plugin_data_writes():
    """源码级：无任何向其他插件 data/plugins 目录的写入路径。"""
    for p in [REPO / "services", REPO / "plugin_shell", REPO / "main.py"]:
        files = [p] if p.is_file() else list(p.rglob("*.py"))
        for py in files:
            src = py.read_text(encoding="utf-8")
            assert "data/plugins/" not in src.replace(
                "plugin_data", ""), py
