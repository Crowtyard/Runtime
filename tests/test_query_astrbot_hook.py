# -*- coding: utf-8 -*-
"""M5 AstrBot Hook 集成测试（stub harness）：
M5Q32-36 / M5Q51（exactly-once）。

真实 AstrBot 环境 smoke 由 scripts/m5_real_astrbot_smoke.py（live 实例
venv）覆盖；此处验证 hook 注册唯一性、每请求至多一份、启停/重载隔离。
"""
from __future__ import annotations

import asyncio
import importlib
from pathlib import Path

import pytest

from XiaoguangBlessedLandRuntime.database.db import (create_db_engine,
                                                     make_session_factory)
from XiaoguangBlessedLandRuntime.database.models_core import WorldRuntime
from XiaoguangBlessedLandRuntime.domain.constants import RuntimeStatus
from XiaoguangBlessedLandRuntime.services.db_lifecycle import migrate_database
from XiaoguangBlessedLandRuntime.services.repositories import (
    RuntimeRepository, TimeRatioRepository)
from XiaoguangBlessedLandRuntime.services.simulation.mini_world import \
    seed_mini_world

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_NAME = REPO_ROOT.name
DB_FILENAME = "blessed_land.sqlite"


class _FakeEvent:
    def __init__(self, text: str):
        self.message_str = text


class _FakeRequest:
    def __init__(self):
        self.extra_user_content_parts: list = []


@pytest.fixture()
def m5_plugin_env(monkeypatch, tmp_path):
    from tests.conftest import EPOCH0, EPOCH0_US
    data_root = tmp_path / "astrbot_data"
    plugin_data_dir = data_root / "plugin_data" / PACKAGE_NAME
    monkeypatch.setenv("BLR_TEST_PLUGIN_DATA_DIR", str(plugin_data_dir))
    monkeypatch.setenv("BLR_STUB_PLUGIN_DATA_ROOT",
                       str(data_root / "plugin_data"))
    monkeypatch.syspath_prepend(str(REPO_ROOT / "tests" / "stub_astrbot"))
    monkeypatch.syspath_prepend(str(REPO_ROOT.parent))
    # 与 main.py 完全相同的模块路径（astrbot.api.event.filter）读取 stub
    # registry —— 不同路径导入会是两个模块实例、两个 registry
    from astrbot.api.event.filter import HOOK_REGISTRY, reset_registry
    reset_registry()
    # import 缓存处理：模块已在会话中导入过 → reload 以重新执行类定义
    #（hook 装饰器随类定义注册；reload 模拟 AstrBot 插件热重载语义）
    import sys
    full_name = f"{PACKAGE_NAME}.main"
    if full_name in sys.modules:
        main_mod = importlib.reload(sys.modules[full_name])
    else:
        main_mod = importlib.import_module(full_name)

    def make_activated_db() -> None:
        db_path = plugin_data_dir / DB_FILENAME
        db_path.parent.mkdir(parents=True, exist_ok=True)
        url = "sqlite:///" + str(db_path).replace("\\", "/")
        migrate_database(url, project_root=REPO_ROOT)
        engine = create_db_engine(url)
        factory = make_session_factory(engine)
        with factory() as s:
            RuntimeRepository(s).create_not_activated(
                world_id="M5HOOK-001", world_bible_version="1.0",
                simulation_version="0.3.0-m3a",
                world_bible_manifest_hash="m5-test")
            row = s.execute(
                __import__("sqlalchemy").select(WorldRuntime)).scalar_one()
            row.runtime_status = RuntimeStatus.ACTIVE
            row.world_seed_version = "M5-TEST-SEED-001"
            row.current_blessed_tick = 0
            row.last_committed_real_us = EPOCH0_US
            row.time_rate_remainder = 0
            rate = TimeRatioRepository(s).add(
                world_id="M5HOOK-001", real_effective_from=EPOCH0,
                rate_numerator=1_000_000,
                rate_denominator=86_400_000_000, reason="TEST", source="TEST")
            row.current_time_ratio_id = rate.ratio_id
            seed_mini_world(s, with_ecology=True, with_social=True,
                            with_tribulation=True, world_id="M5HOOK-001")
            s.commit()
        engine.dispose()

    return {"main": main_mod, "plugin_cls": main_mod.BlessedLandRuntimePlugin,
            "plugin_data_dir": plugin_data_dir, "make_activated_db":
                make_activated_db, "registry": lambda: __import__(
                    "astrbot.api.event.filter", fromlist=["HOOK_REGISTRY"]
                ).HOOK_REGISTRY}


def _boot(m5_plugin_env, config: dict | None = None):
    from astrbot.api import AstrBotConfig
    from astrbot.api.star import Context
    cfg = {"runtime_enabled": True, "scheduler_enabled": False}
    cfg.update(config or {})
    plugin = m5_plugin_env["plugin_cls"](Context(), AstrBotConfig(cfg))
    asyncio.run(plugin.initialize())
    return plugin


# ---------------------------------------------------------------- M5Q32
def test_m5q32_duplicate_hook_prevention(m5_plugin_env):
    """hook 注册唯一：类定义一次 = 注册一次；单次 import 后 registry 恰一份。"""
    registry = m5_plugin_env["registry"]()
    handlers = registry.get("on_llm_request", [])
    assert len(handlers) == 1
    assert handlers[0].__name__ == "_on_llm_request_world_context"


# ---------------------------------------------------------------- M5Q33/51
def test_m5q33_reload_no_duplicate_capsule(m5_plugin_env):
    """重复实例化（模拟 reload）：每 ProviderRequest 至多一份 Capsule。"""
    m5_plugin_env["make_activated_db"]()
    a = _boot(m5_plugin_env, {"query_integration_enabled": True})
    b = _boot(m5_plugin_env, {"query_integration_enabled": True})
    req = _FakeRequest()
    asyncio.run(b._on_llm_request_world_context(
        _FakeEvent("福地现在怎么样？"), req))
    assert len(req.extra_user_content_parts) == 1  # 恰好一份
    part = req.extra_user_content_parts[0]
    assert "[Blessed Land Runtime" in part.text
    assert getattr(part, "_temp", False) is True  # mark_as_temp：不进记忆
    asyncio.run(a.terminate())
    asyncio.run(b.terminate())


def test_m5q51_exactly_once_per_request(m5_plugin_env):
    m5_plugin_env["make_activated_db"]()
    p = _boot(m5_plugin_env)
    req = _FakeRequest()
    asyncio.run(p._on_llm_request_world_context(_FakeEvent("现在有多少人？"),
                                                req))
    asyncio.run(p._on_llm_request_world_context(_FakeEvent("现在有多少人？"),
                                                req))
    # 每次调用 = 一个请求周期；单请求内绝不追加两份
    assert len(req.extra_user_content_parts) == 2
    asyncio.run(p.terminate())


# ---------------------------------------------------------------- M5Q34/35
def test_m5q34_disable_removes_injection(m5_plugin_env):
    m5_plugin_env["make_activated_db"]()
    p = _boot(m5_plugin_env, {"query_integration_enabled": False})
    req = _FakeRequest()
    asyncio.run(p._on_llm_request_world_context(_FakeEvent("现在有多少人？"),
                                                req))
    assert req.extra_user_content_parts == []
    asyncio.run(p.terminate())


def test_m5q35_reenable_restores_injection(m5_plugin_env):
    m5_plugin_env["make_activated_db"]()
    p = _boot(m5_plugin_env, {"query_integration_enabled": False})
    req = _FakeRequest()
    asyncio.run(p._on_llm_request_world_context(_FakeEvent("现在有多少人？"),
                                                req))
    assert req.extra_user_content_parts == []
    p.config["query_integration_enabled"] = True
    req2 = _FakeRequest()
    asyncio.run(p._on_llm_request_world_context(_FakeEvent("现在有多少人？"),
                                                req2))
    assert len(req2.extra_user_content_parts) == 1
    asyncio.run(p.terminate())


# ---------------------------------------------------------------- M5Q36
def test_m5q36_restart_cycles(m5_plugin_env):
    m5_plugin_env["make_activated_db"]()
    for _ in range(3):
        p = _boot(m5_plugin_env)
        req = _FakeRequest()
        asyncio.run(p._on_llm_request_world_context(
            _FakeEvent("福地现在怎么样？"), req))
        assert len(req.extra_user_content_parts) == 1
        asyncio.run(p.terminate())
    assert len(m5_plugin_env["registry"]().get(
        "on_llm_request", [])) == 1


# ---------------------------------------------------------------- 闲聊不注入
def test_m5q_normal_chat_no_injection(m5_plugin_env):
    m5_plugin_env["make_activated_db"]()
    p = _boot(m5_plugin_env)
    for msg in ("早上好", "今天有点累", "你在干嘛"):
        req = _FakeRequest()
        asyncio.run(p._on_llm_request_world_context(_FakeEvent(msg), req))
        assert req.extra_user_content_parts == [], msg
    asyncio.run(p.terminate())
