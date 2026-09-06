# -*- coding: utf-8 -*-
"""M1.1 AstrBot 插件壳集成测试：PL1–PL22 + Activation Time Trap + 数据隔离。

覆盖：插件发现/元数据加载/无 Private Companion 初始化/Page 发现/状态 API/
plugin_data 持久化/源码目录无权威 DB/热重载/重启等价/Private Companion 替换隔离/
插件代码替换隔离/只读端点/无激活与推进端点/正式世界审计/激活时间陷阱/备份落在
plugin_data/核心层零 astrbot 依赖。

测试 harness：tests/stub_astrbot 提供最小官方 API 桩；真实 AstrBot 实例
（D:\\MY SELF\\AstrBot）仅用于只读审计，不参与本测试运行。
"""
from __future__ import annotations

import asyncio
import importlib
import json
import shutil
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import select, text

from database.models_core import (SimulationRun, TimeRatioHistory, WorldEvent,
                                  WorldRuntime)
from services.db_lifecycle import migrate_database, seed_database

REPO_ROOT = Path(__file__).resolve().parent.parent
STUB_DIR = REPO_ROOT / "tests" / "stub_astrbot"
PACKAGE_NAME = REPO_ROOT.name  # 部署名 = astrbot_plugin_blessed_land_runtime
PLUGIN_DATA_NAME = "astrbot_plugin_blessed_land_runtime"
DB_FILENAME = "blessed_land.sqlite"


def _run(coro):
    return asyncio.run(coro)


# ------------------------------------------------------------------ fixtures
@pytest.fixture()
def plugin_env(monkeypatch, tmp_path):
    """最小 AstrBot 环境：stub api + plugin_data 目录 + 插件包导入。"""
    data_root = tmp_path / "astrbot_data"
    plugin_data_dir = data_root / "plugin_data" / PLUGIN_DATA_NAME
    monkeypatch.setenv("BLR_TEST_PLUGIN_DATA_DIR", str(plugin_data_dir))
    monkeypatch.setenv("BLR_STUB_PLUGIN_DATA_ROOT",
                       str(data_root / "plugin_data"))
    monkeypatch.syspath_prepend(str(STUB_DIR))
    monkeypatch.syspath_prepend(str(REPO_ROOT.parent))
    main_mod = importlib.import_module(f"{PACKAGE_NAME}.main")
    return {
        "main": main_mod,
        "plugin_cls": main_mod.BlessedLandRuntimePlugin,
        "plugin_data_dir": plugin_data_dir,
        "repo_root": REPO_ROOT,
    }


def _make_not_activated_world_db(db_path: Path, bible_dir: Path) -> None:
    from database.db import create_db_engine, make_session_factory
    db_path.parent.mkdir(parents=True, exist_ok=True)
    url = "sqlite:///" + str(db_path).replace("\\", "/")
    migrate_database(url, project_root=REPO_ROOT)
    engine = create_db_engine(url)
    factory = make_session_factory(engine)
    seed_database(engine, factory, bible_dir=bible_dir)
    engine.dispose()


@pytest.fixture()
def booted_plugin(plugin_env, real_bible_dir):
    """插件已 initialize；数据目录内是 NOT_ACTIVATED 正式世界形态。"""
    plugin_data_dir: Path = plugin_env["plugin_data_dir"]
    _make_not_activated_world_db(plugin_data_dir / DB_FILENAME, real_bible_dir)

    from astrbot.api import AstrBotConfig  # stub 路径解析（与 main.py 同模块身份）
    from astrbot.api.star import Context
    context = Context()
    plugin = plugin_env["plugin_cls"](
        context, AstrBotConfig({"runtime_enabled": True}))
    _run(plugin.initialize())
    yield plugin
    _run(plugin.terminate())


def _snapshot(plugin) -> dict:
    with plugin._host.session_factory() as s:
        row = s.execute(select(WorldRuntime)).scalar_one_or_none()
        counts = {
            t: s.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar()
            for t in ("persons", "population_groups", "settlements",
                      "resource_nodes", "tribulations", "world_events",
                      "timeline_entries", "simulation_run",
                      "simulation_checkpoints")
        }
        runs = s.execute(select(SimulationRun)).scalars().all()
        events = s.execute(select(WorldEvent)).scalars().all()
        return {
            "world_row": tuple(getattr(row, c) for c in (
                "world_id", "runtime_status", "world_seed_version",
                "current_blessed_tick", "last_committed_real_us",
                "time_rate_remainder", "schema_version"))
            if row else None,
            "counts": counts,
            "run_ids": sorted(r.run_id for r in runs),
            "event_uids": sorted(e.event_uid for e in events),
        }


# ---------------------------------------------------------------- PL1 / PL2
def test_pl1_astrbot_discovers_plugin(plugin_env):
    """PL1: AstrBot 可以发现插件（metadata.yaml + Star 子类）。"""
    assert (plugin_env["repo_root"] / "metadata.yaml").exists()
    from astrbot.api.star import Star  # stub 路径解析（与 main.py 同模块身份）
    assert issubclass(plugin_env["plugin_cls"], Star)


def test_pl2_metadata_and_conf_schema_load(plugin_env):
    """PL2: metadata 关键字段正确；_conf_schema 合法且无危险配置项。"""
    meta = (plugin_env["repo_root"] / "metadata.yaml").read_text(
        encoding="utf-8")
    for expected in (
        "name: astrbot_plugin_blessed_land_runtime",
        "display_name: 小光福地 Runtime",
        "version: 0.1.1",
        "author: DSH",
        'astrbot_version: ">=4.22.0"',
        "pages:",
        "- name: blessed-land",
    ):
        assert expected in meta, expected
    assert "repo:" not in meta  # 不伪造 repo URL

    schema = json.loads(
        (plugin_env["repo_root"] / "_conf_schema.json").read_text(
            encoding="utf-8"))
    assert set(schema) == {"runtime_enabled", "diagnostic_log_level",
                           "backup_retention", "page_refresh_interval"}
    forbidden = ("activate", "advance", "seed", "create", "delete", "reset",
                 "tick", "rate", "catchup")
    for key in schema:
        assert not any(f in key for f in forbidden), key


# ---------------------------------------------------------------- PL3 / PL4
def test_pl3_initializes_without_private_companion(booted_plugin):
    """PL3: 无 Private Companion 时插件照常初始化（Sibling Plugins）。"""
    assert booted_plugin._host is not None
    assert booted_plugin._host.status()["plugin_status"] == "RUNNING"


def test_pl4_plugin_page_discovered(plugin_env):
    """PL4: Plugin Page 被发现（metadata pages + 页面文件 + 官方桥）。"""
    pages_dir = plugin_env["repo_root"] / "pages" / "blessed-land"
    assert (pages_dir / "index.html").exists()
    assert (pages_dir / "app.js").exists()
    assert (pages_dir / "style.css").exists()
    app_js = (pages_dir / "app.js").read_text(encoding="utf-8")
    assert "window.AstrBotPluginPage" in app_js
    assert "bridge.apiGet" in app_js


# ---------------------------------------------------------------- PL5 / PL6 / PL7
def test_pl5_status_api_works(booted_plugin):
    """PL5: 页面状态 API 工作且字段完整。"""
    payload = _run(booted_plugin._api_status())
    assert payload["success"] is True
    data = payload["data"]
    for key in ("plugin_status", "runtime_version", "world_status",
                "seed_present", "current_blessed_tick", "natural_rate",
                "db", "writer", "entity_counts"):
        assert key in data, key
    assert data["world_status"] == "NOT_ACTIVATED"
    assert data["seed_present"] is False
    assert data["current_blessed_tick"] is None


def test_pl6_persistent_db_under_plugin_data(booted_plugin, plugin_env):
    """PL6: 持久数据位于 plugin_data/<plugin>/blessed_land.sqlite。"""
    host = booted_plugin._host
    assert host.db_path == plugin_env["plugin_data_dir"] / DB_FILENAME
    assert host.db_path.exists()


def test_pl7_no_authoritative_db_in_plugin_code_dir(booted_plugin, plugin_env):
    """PL7: 插件源码目录内不存在权威 DB；权威标记指向源码目录之外。"""
    repo: Path = plugin_env["repo_root"]
    assert not list(repo.rglob(DB_FILENAME))
    marker = booted_plugin._host.read_authoritative_marker()
    assert marker is not None
    target = Path(marker["authoritative_db_path"]).resolve()
    assert str(repo.resolve()) not in str(target)


# ------------------------------------------------- PL8 / PL9 / PL10（重载与重启）
def test_pl8_reload_preserves_db(plugin_env, real_bible_dir):
    """PL8: A 实例 → terminate → B 实例加载同一 DB：无重复、无损坏。"""
    plugin_data_dir = plugin_env["plugin_data_dir"]
    _make_not_activated_world_db(plugin_data_dir / DB_FILENAME, real_bible_dir)
    from astrbot.api.star import Context
    from astrbot.api import AstrBotConfig

    for _ in range(2):  # 两轮 load → terminate（含重启等价）
        plugin = plugin_env["plugin_cls"](Context(), AstrBotConfig({}))
        _run(plugin.initialize())
        status = plugin._host.status()
        assert status["world_status"] == "NOT_ACTIVATED"
        assert status["db"]["integrity"] == "ok"
        _run(plugin.terminate())
    with sqlite3.connect(str(plugin_data_dir / DB_FILENAME)) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM world_runtime").fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM time_ratio_history").fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM alembic_version").fetchone()[0] == 1
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_pl9_reload_does_not_advance_not_activated_world(plugin_env,
                                                         real_bible_dir):
    """PL9: 重载不得推进 NOT_ACTIVATED 世界。"""
    plugin_data_dir = plugin_env["plugin_data_dir"]
    _make_not_activated_world_db(plugin_data_dir / DB_FILENAME, real_bible_dir)
    from astrbot.api.star import Context
    from astrbot.api import AstrBotConfig
    for _ in range(3):
        plugin = plugin_env["plugin_cls"](Context(), AstrBotConfig({}))
        _run(plugin.initialize())
        _run(plugin.terminate())
    with sqlite3.connect(str(plugin_data_dir / DB_FILENAME)) as conn:
        row = conn.execute(
            "SELECT current_blessed_tick, last_committed_real_us "
            "FROM world_runtime").fetchone()
        assert row == (None, None)
        assert conn.execute(
            "SELECT COUNT(*) FROM simulation_run").fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM world_events").fetchone()[0] == 0


def test_pl10_restart_equivalent_preserves_db(plugin_env, real_bible_dir):
    """PL10: 重启等价生命周期（engine 完全释放后重启）保持 DB。"""
    plugin_data_dir = plugin_env["plugin_data_dir"]
    _make_not_activated_world_db(plugin_data_dir / DB_FILENAME, real_bible_dir)
    from astrbot.api.star import Context
    from astrbot.api import AstrBotConfig
    plugin = plugin_env["plugin_cls"](Context(), AstrBotConfig({}))
    _run(plugin.initialize())
    _run(plugin.terminate())  # 完全释放引擎
    assert plugin._host is None
    plugin2 = plugin_env["plugin_cls"](Context(), AstrBotConfig({}))
    _run(plugin2.initialize())
    try:
        assert plugin2._host.status()["db"]["integrity"] == "ok"
        assert plugin2._host.status()["world_status"] == "NOT_ACTIVATED"
    finally:
        _run(plugin2.terminate())


# --------------------------------------------- PL11 / PL12（更新隔离）
def test_pl11_private_companion_replacement_does_not_affect_runtime(
        booted_plugin, plugin_env, tmp_path):
    """PL11: 删除/替换 Private Companion 不影响 Runtime（代码+数据）。"""
    companion_dir = tmp_path / "plugins" / "astrbot_plugin_private_companion"
    companion_dir.mkdir(parents=True)
    (companion_dir / "main.py").write_text("# fake companion\n",
                                           encoding="utf-8")
    assert booted_plugin._host.status()["plugin_status"] == "RUNNING"
    shutil.rmtree(tmp_path / "plugins")
    assert booted_plugin._host.status()["plugin_status"] == "RUNNING"
    # 重新安装 companion 后依然正常
    companion_dir.mkdir(parents=True)
    (companion_dir / "main.py").write_text("# fake companion v2\n",
                                           encoding="utf-8")
    assert booted_plugin._host.status()["plugin_status"] == "RUNNING"
    # 源码零依赖 Private Companion
    for rel in ("main.py", "plugin_shell", "domain", "services", "database"):
        root = plugin_env["repo_root"] / rel
        files = root.rglob("*.py") if root.is_dir() else [root]
        for f in files:
            assert "private_companion" not in f.read_text(
                encoding="utf-8").lower(), f


def test_pl12_plugin_code_replacement_preserves_data(plugin_env,
                                                     real_bible_dir,
                                                     tmp_path):
    """PL12: 插件代码目录整体删除/替换，plugin_data DB 不受影响。"""
    plugin_data_dir = plugin_env["plugin_data_dir"]
    _make_not_activated_world_db(plugin_data_dir / DB_FILENAME, real_bible_dir)

    def _copy_code(dst: Path) -> Path:
        dst.mkdir(parents=True, exist_ok=True)
        for name in ("alembic.ini", "database", "domain", "services",
                     "config", "plugin_shell"):
            src = plugin_env["repo_root"] / name
            if src.is_dir():
                shutil.copytree(src, dst / name,
                                ignore=shutil.ignore_patterns("__pycache__"))
            else:
                shutil.copyfile(src, dst / name)
        return dst

    from plugin_shell.runtime_host import RuntimeHost
    code_dir = _copy_code(tmp_path / "code")
    host = RuntimeHost(plugin_data_dir, project_root=code_dir)
    host.boot()
    host.shutdown()
    shutil.rmtree(tmp_path / "code")  # 模拟插件代码目录整体删除
    assert (plugin_data_dir / DB_FILENAME).exists()  # 数据完全不受影响
    code_dir2 = _copy_code(tmp_path / "code2")  # 重新安装新版代码
    host2 = RuntimeHost(plugin_data_dir, project_root=code_dir2)
    host2.boot()
    try:
        with sqlite3.connect(str(plugin_data_dir / DB_FILENAME)) as conn:
            row = conn.execute(
                "SELECT current_blessed_tick, last_committed_real_us "
                "FROM world_runtime").fetchone()
            assert row == (None, None)
    finally:
        host2.shutdown()


# ------------------------------------------- PL13 / PL14 / PL15（只读不写）
def test_pl13_page_open_does_not_mutate_world(booted_plugin):
    before = _snapshot(booted_plugin)
    _run(booted_plugin._api_status())
    _run(booted_plugin._api_diagnostics())
    _run(booted_plugin._api_runtime_info())
    after = _snapshot(booted_plugin)
    assert after == before


def test_pl14_status_api_does_not_mutate_world(booted_plugin):
    before = _snapshot(booted_plugin)
    for _ in range(5):
        _run(booted_plugin._api_status())
    assert _snapshot(booted_plugin) == before


def test_pl15_diagnostics_api_does_not_mutate_world(booted_plugin):
    before = _snapshot(booted_plugin)
    for _ in range(5):
        _run(booted_plugin._api_diagnostics())
    assert _snapshot(booted_plugin) == before


# ------------------------------------------- PL16 / PL17（无危险端点）
def test_pl16_no_world_seed_activation_endpoint(booted_plugin, plugin_env):
    """PL16/PL17: 只注册 3 个只读 GET 端点；无 activate/advance/seed/create。"""
    routes = booted_plugin.context.routes
    assert set(routes) == {"/status", "/diagnostics", "/runtime-info"}
    for route, (handler, methods, desc) in routes.items():
        assert methods == ["GET"], (route, methods)
    main_src = (plugin_env["repo_root"] / "main.py").read_text(
        encoding="utf-8")
    # 只统计真实注册调用（docstring 中的禁词不算）
    import re
    registrations = re.findall(r'reg\("(/[^"]+)"', main_src)
    assert registrations == ["/status", "/diagnostics", "/runtime-info"]


def test_pl17_no_manual_tick_advancement_endpoint(booted_plugin):
    routes = booted_plugin.context.routes
    assert not any(m for _, (_, methods, _) in routes.items()
                   for m in methods if m != "GET")


# --------------------------------- PL18–PL22（正式世界形态审计）
def test_pl18_22_formal_world_audit(booted_plugin):
    """PL18-22: NOT_ACTIVATED / seed=NULL / tick=NULL / 业务全零 / 历史为零。"""
    data = _run(booted_plugin._api_status())["data"]
    assert data["world_status"] == "NOT_ACTIVATED"            # PL18
    assert data["seed_present"] is False                       # PL19
    assert data["current_blessed_tick"] is None                # PL20
    counts = data["entity_counts"]
    assert counts["persons"] == 0
    assert counts["population_groups"] == 0
    assert counts["settlements"] == 0
    assert counts["resource_nodes"] == 0
    assert counts["tribulations"] == 0                         # PL21
    assert counts["world_events"] == 0
    assert counts["timeline_entries"] == 0                     # PL22 正式历史为零
    assert counts["simulation_run"] == 0
    with booted_plugin._host.session_factory() as s:
        assert s.execute(select(WorldEvent)).scalars().all() == []


# ------------------------------------------- Activation Time Trap（§9）
def test_activation_time_trap(plugin_env, real_bible_dir):
    """现实经过的时间不得在未激活期间累积成未来福地历史。"""
    plugin_data_dir = plugin_env["plugin_data_dir"]
    _make_not_activated_world_db(plugin_data_dir / DB_FILENAME, real_bible_dir)
    from astrbot.api.star import Context
    from astrbot.api import AstrBotConfig
    plugin = plugin_env["plugin_cls"](Context(), AstrBotConfig({}))
    _run(plugin.initialize())
    try:
        for _ in range(4):  # load/reload/status/page/diagnostics 等价操作
            _run(plugin._api_status())
            _run(plugin._api_diagnostics())
        with plugin._host.session_factory() as s:
            row = s.execute(select(WorldRuntime)).scalar_one()
            assert row.current_blessed_tick is None
            assert row.last_committed_real_us is None
            assert s.execute(select(SimulationRun)).scalars().all() == []
            assert s.execute(select(WorldEvent)).scalars().all() == []
    finally:
        _run(plugin.terminate())
    # 静态：宿主层绝不调用 catch_up（激活纪元属于 M2 Activation Transaction）
    host_src = (REPO_ROOT / "plugin_shell" / "runtime_host.py").read_text(
        encoding="utf-8")
    assert "catch_up" not in host_src


# ------------------------------------------- 配置与备份（§16/§24）
def test_disabled_config_creates_no_world_db(plugin_env):
    from astrbot.api.star import Context
    from astrbot.api import AstrBotConfig
    plugin = plugin_env["plugin_cls"](
        Context(), AstrBotConfig({"runtime_enabled": False}))
    _run(plugin.initialize())
    try:
        assert plugin._host.status()["plugin_status"] == "DISABLED"
        assert not (plugin_env["plugin_data_dir"] / DB_FILENAME).exists()
    finally:
        _run(plugin.terminate())


def test_backup_lives_under_plugin_data(booted_plugin):
    """§24: 备份写入 plugin_data/backups，不随插件代码更新丢失。"""
    rec = booted_plugin._host.backup_now()
    assert Path(rec["path"]).parent == booted_plugin._host.backups_dir
    assert (booted_plugin._host.backups_dir / "backup_manifest.jsonl").exists()
    conn = sqlite3.connect(rec["path"])
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()


def test_core_has_no_astrbot_imports():
    """PLUGIN SHELL ≠ DOMAIN CORE：核心层零 astrbot 依赖（main.py 除外）。"""
    import re
    import_stmt = re.compile(r"^\s*(import astrbot\b|from astrbot\b)", re.M)
    for base in ("domain", "services", "database", "config"):
        for f in (REPO_ROOT / base).rglob("*.py"):
            src = f.read_text(encoding="utf-8")
            assert not import_stmt.search(src), f
    # paths.py 是唯一允许触碰 AstrBot 路径 API 的适配点
    paths_src = (REPO_ROOT / "plugin_shell" / "paths.py").read_text(
        encoding="utf-8")
    assert "astrbot.core.utils.astrbot_path" in paths_src
    host_src = (REPO_ROOT / "plugin_shell" / "runtime_host.py").read_text(
        encoding="utf-8")
    assert not import_stmt.search(host_src)
