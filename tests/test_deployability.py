# -*- coding: utf-8 -*-
"""可部署形态回归：生产代码不得依赖开发仓库包名 ``XiaoguangBlessedLandRuntime``。

M5.1 隔离验收发现的第二个缺陷：``main.py`` 内多处使用开发包名绝对导入
（``from XiaoguangBlessedLandRuntime.services.query import ...``），
在 AstrBot 部署形态（插件目录名 = ``astrbot_plugin_blessed_land_runtime``）下必然
``ModuleNotFoundError`` → ``initialize()`` 抛错 → AstrBot 标记插件加载失败
（调度器未挂载、查询钩子未注册）。

本文件锁定：
1. 生产代码（main.py + 生产包目录）零开发包名引用；
2. 把生产文件按**部署名**复制到临时目录后，能真正导入并以部署形态完成
   ``initialize()``（含 scheduler 挂载），即部署形态可加载。
"""
from __future__ import annotations

import asyncio
import importlib
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STUB_DIR = REPO_ROOT / "tests" / "stub_astrbot"
DEV_PACKAGE_NAME = REPO_ROOT.name            # XiaoguangBlessedLandRuntime
DEPLOY_PACKAGE_NAME = "astrbot_plugin_blessed_land_runtime"

RUNTIME_FILES = ("main.py", "__init__.py", "metadata.yaml", "_conf_schema.json",
                 "requirements.txt", "alembic.ini")
RUNTIME_DIRS = ("config", "database", "domain", "services", "plugin_shell",
                "pages")


def _runtime_py_files() -> list[Path]:
    files = [REPO_ROOT / name for name in RUNTIME_FILES if (REPO_ROOT / name).exists()]
    for d in RUNTIME_DIRS:
        base = REPO_ROOT / d
        if base.is_dir():
            files.extend(p for p in base.rglob("*.py")
                         if "__pycache__" not in p.parts)
    return files


def test_runtime_code_has_no_dev_package_name_reference():
    offenders: list[str] = []
    for path in _runtime_py_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            if DEV_PACKAGE_NAME in line:
                offenders.append(
                    f"{path.relative_to(REPO_ROOT)}:{lineno} {line.strip()}")
    assert offenders == [], (
        "生产代码出现开发包名绝对导入（部署形态会 ModuleNotFoundError）:\n"
        + "\n".join(offenders))


def _make_deployment_copy(dest: Path) -> Path:
    """按部署形态复制生产文件：包目录名 = 部署名。"""
    pkg = dest / DEPLOY_PACKAGE_NAME
    pkg.mkdir(parents=True, exist_ok=True)
    for name in RUNTIME_FILES:
        src = REPO_ROOT / name
        if src.exists():
            shutil.copy2(src, pkg / name)
    for d in RUNTIME_DIRS:
        src = REPO_ROOT / d
        if src.is_dir():
            shutil.copytree(src, pkg / d,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return pkg.parent


def test_deployment_form_can_initialize_plugin(tmp_path, monkeypatch):
    """部署形态（部署包名）下插件必须能 import 且 initialize() 成功。"""
    host_root = _make_deployment_copy(tmp_path)
    plugin_data_dir = tmp_path / "astrbot_data" / "plugin_data" / DEPLOY_PACKAGE_NAME
    monkeypatch.setenv("BLR_TEST_PLUGIN_DATA_DIR", str(plugin_data_dir))
    monkeypatch.setenv("BLR_STUB_PLUGIN_DATA_ROOT",
                       str(tmp_path / "astrbot_data" / "plugin_data"))
    monkeypatch.syspath_prepend(str(STUB_DIR))
    monkeypatch.syspath_prepend(str(host_root))

    # 必须用部署名导入（开发名此时不可用：临时目录里没有同名包）
    for mod in list(sys.modules):
        if mod.startswith(DEV_PACKAGE_NAME):
            monkeypatch.delitem(sys.modules, mod, raising=False)
    main_mod = importlib.import_module(f"{DEPLOY_PACKAGE_NAME}.main")

    from astrbot.api import AstrBotConfig
    from astrbot.api.star import Context

    plugin = main_mod.BlessedLandRuntimePlugin(
        Context(), AstrBotConfig({"runtime_enabled": True}))
    asyncio.run(plugin.initialize())          # 不得抛 ModuleNotFoundError
    try:
        assert plugin._host is not None, "host 未建立"
        assert plugin._host._scheduler is not None, \
            "scheduler 未挂载（部署形态 initialize 失败的典型症状）"
        assert (plugin_data_dir / "blessed_land.sqlite").exists(), \
            "未在 plugin_data 下建库"
        status = plugin._host.status()
        assert status["world_status"] == "NOT_ACTIVATED"
    finally:
        asyncio.run(plugin.terminate())
