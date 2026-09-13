# -*- coding: utf-8 -*-
"""M5.1 事故修复回归：alembic 迁移不得改动宿主 logging。

事故（2026-09-12 live）：Runtime 在 AstrBot 进程内执行 ``alembic upgrade`` 时，
``env.py`` 调用 ``fileConfig(alembic.ini)``，默认 ``disable_existing_loggers=True``：

* 禁用当时已存在的全部 logger（含 ``astrbot`` 全树）；
* 用 ini 的 root（``WARNING`` + ``StreamHandler(sys.stderr)``）替换宿主 root handler。

后果：``logger.info("AstrBot started.")`` 被静默丢弃 → Launcher 的 stdout 就绪标记
永不出现 → ``startup timed out (300s)`` → force kill。

本文件锁定的不变量（HOST_LOGGING_MUTATIONS = 0）：

1. 嵌入式迁移不调用 ``fileConfig``（显式 flag 生效，不靠调用栈猜测）；
2. 迁移前后宿主 logger 状态逐项不变：root level/handlers、各 logger 的
   disabled/level/handlers/propagate、``Logger.manager.disable``；
3. 迁移后宿主仍能发出 ``AstrBot started.`` 并到达 sink（marker 不被静默）；
4. CLI 语义保留：未声明 flag 时仍按 ``alembic.ini`` 配置 logging；
5. 插件全生命周期（建库→load→migration→scheduler→shutdown）零宿主 logging 变异。
"""
from __future__ import annotations

import asyncio
import importlib
import io
import logging
import logging.config
from contextlib import contextmanager
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from XiaoguangBlessedLandRuntime.database.db import (
    create_db_engine, make_session_factory)
from XiaoguangBlessedLandRuntime.database.migration_contract import (
    SKIP_LOGGING_CONFIG_ATTR, embedded_migration_attributes,
    is_logging_config_skipped)
from XiaoguangBlessedLandRuntime.services.db_lifecycle import (
    build_embedded_migration_config, migrate_database, seed_database)

from tests.conftest import HEAD_REVISION, PROJECT_ROOT

REPO_ROOT = Path(__file__).resolve().parent.parent
STUB_DIR = REPO_ROOT / "tests" / "stub_astrbot"
PACKAGE_NAME = REPO_ROOT.name
PLUGIN_DATA_NAME = "astrbot_plugin_blessed_land_runtime"
DB_FILENAME = "blessed_land.sqlite"

#: 模拟 AstrBot 宿主 logging 命名空间：这些 logger 在插件加载前就已存在。
HOST_LOGGER_NAMES = (
    "astrbot",
    "astrbot.core",
    "astrbot.core.core_lifecycle",
    "astrbot_plugin_private_companion",
)

MARKER = "AstrBot started."


# ------------------------------------------------------------ host logging 复刻
def _handler_ids(logger: logging.Logger) -> tuple[int, ...]:
    return tuple(id(h) for h in logger.handlers)


def host_logging_snapshot(
        logger_names: tuple[str, ...] = HOST_LOGGER_NAMES) -> dict:
    """宿主 logging 状态快照（用于逐项比对，不许有任何变化）。"""
    root = logging.getLogger()
    snap = {
        "manager.disable": logging.Logger.manager.disable,
        "root.disabled": root.disabled,
        "root.level": root.level,
        "root.propagate": root.propagate,
        "root.handlers": _handler_ids(root),
        "root.filters": tuple(id(f) for f in root.filters),
    }
    for name in logger_names:
        lg = logging.getLogger(name)
        snap[f"{name}.disabled"] = lg.disabled
        snap[f"{name}.level"] = lg.level
        snap[f"{name}.handlers"] = _handler_ids(lg)
        snap[f"{name}.propagate"] = lg.propagate
        snap[f"{name}.filters"] = tuple(id(f) for f in lg.filters)
    return snap


def host_logging_diff(before: dict, after: dict) -> dict:
    return {k: (before[k], after[k]) for k in before if before[k] != after[k]}


@contextmanager
def emulated_astrbot_logging():
    """复刻 AstrBot 宿主 logging：root 上挂 loguru 桥（此处用 StringIO handler 代表），
    并让 ``astrbot`` 全树 logger 处于“已存在且启用”的状态。

    退出时把全部状态还原，避免污染同进程其它测试。
    """
    root = logging.getLogger()
    saved_root = (root.level, list(root.handlers), root.disabled,
                  logging.Logger.manager.disable)
    saved_loggers = {}
    for name in HOST_LOGGER_NAMES:
        lg = logging.getLogger(name)
        saved_loggers[name] = (lg.level, list(lg.handlers), lg.disabled,
                               lg.propagate, list(lg.filters))

    stream = io.StringIO()
    bridge = logging.StreamHandler(stream)   # ← loguru 桥的替身
    bridge.setFormatter(logging.Formatter(
        "[%(asctime)s] [%(name)s] [%(levelname)s]: %(message)s"))
    root.addHandler(bridge)
    root.setLevel(logging.DEBUG)
    logging.Logger.manager.disable = 0
    for name in HOST_LOGGER_NAMES:
        lg = logging.getLogger(name)
        lg.setLevel(logging.INFO)
        lg.disabled = False
        lg.propagate = True
    try:
        yield stream
    finally:
        root.setLevel(saved_root[0])
        for h in list(root.handlers):
            root.removeHandler(h)
        for h in saved_root[1]:
            root.addHandler(h)
        root.disabled = saved_root[2]
        logging.Logger.manager.disable = saved_root[3]
        for name, (level, handlers, disabled, propagate, filters) in \
                saved_loggers.items():
            lg = logging.getLogger(name)
            lg.setLevel(level)
            for h in list(lg.handlers):
                lg.removeHandler(h)
            for h in handlers:
                lg.addHandler(h)
            lg.disabled = disabled
            lg.propagate = propagate
            for f in list(lg.filters):
                lg.removeFilter(f)
            for f in filters:
                lg.addFilter(f)


def _sqlite_url(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    return "sqlite:///" + str(path).replace("\\", "/")


def _head_of(url: str) -> str:
    engine = create_db_engine(url)
    try:
        with engine.connect() as c:
            return c.execute(text("SELECT version_num FROM alembic_version")
                             ).scalar()
    finally:
        engine.dispose()


# ------------------------------------------------------------------- fixtures
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


# ------------------------------------------------------- 1. 显式 flag（契约）
def test_embedded_builder_declares_explicit_flag():
    """嵌入式构造器必须显式写入 skip_logging_config，不依赖隐式猜测。"""
    cfg = build_embedded_migration_config("sqlite:///:memory:",
                                          project_root=PROJECT_ROOT)
    assert cfg.attributes.get(SKIP_LOGGING_CONFIG_ATTR) is True
    assert is_logging_config_skipped(cfg.attributes) is True
    assert embedded_migration_attributes() == {SKIP_LOGGING_CONFIG_ATTR: True}


def test_flag_absent_means_logging_config_allowed():
    """未声明 flag（CLI 语义）时，契约判定为“允许配置 logging”。"""
    assert is_logging_config_skipped({}) is False


# ------------------------------------------- 2. 嵌入式迁移不调用 fileConfig
def test_embedded_migration_does_not_call_fileconfig(tmp_path, monkeypatch):
    calls: list[tuple] = []
    monkeypatch.setattr(logging.config, "fileConfig",
                        lambda *a, **k: calls.append((a, k)))
    url = _sqlite_url(tmp_path / "embedded.db")
    with emulated_astrbot_logging():
        migrate_database(url, project_root=PROJECT_ROOT)
    assert calls == [], f"嵌入式迁移不得调用 fileConfig，实际调用 {calls}"


def test_cli_style_config_still_configures_logging(tmp_path, monkeypatch):
    """CLI 语义保留：不带 flag 的 Config 仍会让 env.py 调用 fileConfig。

    这里用 spy 断言调用发生（不真的改本进程宿主 logging）。
    """
    calls: list[tuple] = []
    monkeypatch.setattr(logging.config, "fileConfig",
                        lambda *a, **k: calls.append((a, k)))
    url = _sqlite_url(tmp_path / "cli.db")
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location",
                        str(PROJECT_ROOT / "database" / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    # 注意：不写入 embedded_migration_attributes() → 等价于 `alembic upgrade head`
    command.upgrade(cfg, "head")
    assert len(calls) == 1, "CLI 路径必须保留 alembic 自行配置 logging 的语义"
    assert _head_of(url) == HEAD_REVISION


# ------------------------------- 3. 宿主 logging 逐项不变（HOST LOGGING = 0）
def test_embedded_migration_host_logging_invariants(tmp_path):
    url = _sqlite_url(tmp_path / "invariants.db")
    with emulated_astrbot_logging():
        before = host_logging_snapshot()
        migrate_database(url, project_root=PROJECT_ROOT)
        after = host_logging_snapshot()

        # 用户可见字段（逐条显式断言，便于事故复盘定位）
        assert before["root.level"] == after["root.level"], "ROOT_LEVEL_UNCHANGED"
        assert before["root.handlers"] == after["root.handlers"], \
            "ROOT_HANDLERS_UNCHANGED"
        assert logging.getLogger("astrbot").disabled is False, \
            "ASTRBOT_LOGGER_DISABLED = FALSE"
        assert before["manager.disable"] == after["manager.disable"]

        diff = host_logging_diff(before, after)
        assert diff == {}, f"HOST_LOGGING_MUTATIONS != 0: {diff}"
    assert _head_of(url) == HEAD_REVISION


# ------------------------------------------- 4. startup marker 不被静默
def test_startup_marker_survives_embedded_migration(tmp_path):
    """宿主 logger 在迁移之后仍能把 "AstrBot started." 送到 sink。"""
    url = _sqlite_url(tmp_path / "marker.db")
    with emulated_astrbot_logging() as stream:
        logging.getLogger("astrbot.core.core_lifecycle").info("before migration")
        migrate_database(url, project_root=PROJECT_ROOT)
        logging.getLogger("astrbot.core.core_lifecycle").info(MARKER)
        out = stream.getvalue()

    assert "before migration" in out
    assert MARKER in out, "迁移后宿主 marker 被静默：Launcher 就绪握手会失败"


# ------------------------------------------- 5. migration 矩阵
def test_fresh_existing_idempotent_migration_matrix(tmp_path):
    url = _sqlite_url(tmp_path / "matrix.db")
    with emulated_astrbot_logging():
        before = host_logging_snapshot()

        migrate_database(url, project_root=PROJECT_ROOT)   # FRESH_DB_UPGRADE
        assert _head_of(url) == HEAD_REVISION

        migrate_database(url, project_root=PROJECT_ROOT)   # EXISTING_DB_UPGRADE
        assert _head_of(url) == HEAD_REVISION

        migrate_database(url, project_root=PROJECT_ROOT)   # SECOND (幂等)
        assert _head_of(url) == HEAD_REVISION

        assert host_logging_diff(before, host_logging_snapshot()) == {}, \
            "重复迁移也不得改动宿主 logging"


# ------------------------------------------- 6. 插件全生命周期
def test_plugin_lifecycle_does_not_mutate_host_logging(plugin_env,
                                                       real_bible_dir):
    """load → DB migration → scheduler boot → shutdown：宿主 logging 全程不变。"""
    plugin_data_dir: Path = plugin_env["plugin_data_dir"]
    db_path = plugin_data_dir / DB_FILENAME
    url = _sqlite_url(db_path)

    from astrbot.api import AstrBotConfig
    from astrbot.api.star import Context

    with emulated_astrbot_logging() as stream:
        stages: dict[str, dict] = {}
        stages["before_any"] = host_logging_snapshot()

        # 建 NOT_ACTIVATED 世界库（这一步本身即一次嵌入式迁移）
        migrate_database(url, project_root=REPO_ROOT)
        engine = create_db_engine(url)
        seed_database(engine, make_session_factory(engine),
                      bible_dir=real_bible_dir)
        engine.dispose()
        stages["after_db_migration"] = host_logging_snapshot()

        plugin = plugin_env["plugin_cls"](
            Context(), AstrBotConfig({"runtime_enabled": True}))
        stages["after_plugin_construct"] = host_logging_snapshot()

        asyncio.run(plugin.initialize())   # host.boot() + scheduler attach/start
        stages["after_initialize_scheduler_boot"] = host_logging_snapshot()

        asyncio.run(plugin.terminate())    # scheduler stop + host shutdown
        stages["after_plugin_shutdown"] = host_logging_snapshot()

        captured = stream.getvalue()

    baseline = stages["before_any"]
    for name, snap in stages.items():
        diff = host_logging_diff(baseline, snap)
        assert diff == {}, f"[{name}] HOST_LOGGING_MUTATIONS != 0: {diff}"
    assert logging.getLogger("astrbot").disabled is False
    # 插件自身确实产生了日志（说明上面不是“因为什么都没跑”而通过）
    assert captured.strip(), "生命周期内宿主 sink 未收到任何记录，测试无效"
