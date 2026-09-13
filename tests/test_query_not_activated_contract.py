# -*- coding: utf-8 -*-
"""M5.2 Chat Semantics Bugfix 回归（M5Q52+）：

DEFECT B — WORLD_TIME 表达形态覆盖（确定性、零 LLM、无 LLM router）
DEFECT A — NOT_ACTIVATED 严格语义合同（Runtime 侧 context guard）
集成    — ProviderRequest 注入份数（Q1–Q5 = 1，Q6 = 0）与去重（0 重复）

题面固定为 M5 文档原题（docs/m5_astrbot_companion_integration.md §4 + §3），
不得为了通过而改写。
"""
from __future__ import annotations

import asyncio
import importlib
from pathlib import Path

import pytest

from tests.test_scheduler_lifecycle import fresh_scheduler_world

from XiaoguangBlessedLandRuntime.services.query import (ContextBuilder,
                                                        WorldQueryIntentRouter,
                                                        WorldQueryService)
from XiaoguangBlessedLandRuntime.services.query.context_builder import (
    NOT_ACTIVATED_AUTHORITATIVE_RULE, NOT_ACTIVATED_CONSTRAINTS)
from XiaoguangBlessedLandRuntime.services.query.query_models import QueryType

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_NAME = REPO_ROOT.name
DB_FILENAME = "blessed_land.sqlite"

# --------------------------------------------------- M5 文档原题（Q1–Q6）
Q1 = "福地现在怎么样？"
Q2 = "现在有多少人？"
Q3 = "现在是哪一年？"
Q4 = "最近发生了什么？"
Q5 = "下一次灾劫是什么时候？"
Q6 = "小光，今天辛苦啦，陪我聊聊天吧～"

# 合同必须出现的关键语义（natural-language 约束）
CONTRACT_MARKERS = (
    "AUTHORITATIVE_RULE",
    "正式福地尚未激活",
    "STRICT_NOT_ACTIVATED_CONSTRAINTS",
    "不得叙述为当前事实",
    "UNKNOWN=权威值尚不存在",
    "NONE_OFFICIAL=不存在正式历史事件",
    "NULL=NOT_STARTED",
)
# 禁止出现的“退化解释”措辞（把 UNKNOWN 说成资料缺失等）
FORBIDDEN_PHRASINGS = (
    "尚未统计", "未记录", "档案缺失", "第0年", "第 0 年", "元年", "第一年",
    "0 人", "0人", "已经存在", "已有居民",
)


# ---------------------------------------------------------------- DEFECT B
def test_m5q52_world_time_phrase_coverage():
    """WORLD_TIME 表达形态覆盖：exactly one route，且全部为 WORLD_TIME。"""
    r = WorldQueryIntentRouter()
    phrases = (
        "现在是哪一年？",          # 原文档题面（M5.1 验收暴露的缺口）
        "现在是哪年？",
        "现在是什么年份？",
        "福地现在是什么纪年？",
        "福地是什么年份？",
        "现在的纪年是什么？",
        "福地几几年了？",
    )
    for text in phrases:
        assert r.route(text) == QueryType.WORLD_TIME, text
    # 确定性：同一输入重复路由结果一致
    assert len({r.route(t) for t in phrases}) == 1


def test_m5q53_original_question_matrix_routing():
    """M5 原题路由矩阵（不得改写题面）。"""
    r = WorldQueryIntentRouter()
    assert r.route(Q1) == QueryType.WORLD_STATUS
    assert r.route(Q2) == QueryType.POPULATION
    assert r.route(Q3) == QueryType.WORLD_TIME
    assert r.route(Q4) == QueryType.HISTORY
    assert r.route(Q5) == QueryType.TRIBULATION
    assert r.route(Q6) == QueryType.NO_WORLD_CONTEXT


def test_m5q54_plain_chat_never_world_context():
    """普通闲聊/现实无关问题绝不触发 world context（无 LLM router）。"""
    r = WorldQueryIntentRouter()
    for msg in ("早上好", "今天我有点累", "你在干嘛呀", "陪我聊聊天吧",
                "你吃饭了吗", "晚安", ""):
        assert r.route(msg) == QueryType.NO_WORLD_CONTEXT, msg


# ---------------------------------------------------------------- DEFECT A
NOT_ACTIVATED_QUESTIONS = ((Q1, QueryType.WORLD_STATUS),
                           (Q2, QueryType.POPULATION),
                           (Q3, QueryType.WORLD_TIME),
                           (Q4, QueryType.HISTORY),
                           (Q5, QueryType.TRIBULATION))


def _not_activated_builder(tmp_path, i: int) -> ContextBuilder:
    env = fresh_scheduler_world(tmp_path, i, activated=False)
    svc = WorldQueryService(session_factory=env["factory"],
                            world_id=env["world_id"])
    return ContextBuilder(query_service=svc, source="TEST_FIXTURE_ONLY")


def test_m5q55_not_activated_contract_present(tmp_path):
    """五类 world intent 的未激活上下文必须携带严格合同，且数据面无退化措辞。"""
    contract_lines = (NOT_ACTIVATED_AUTHORITATIVE_RULE, *NOT_ACTIVATED_CONSTRAINTS)
    for idx, (question, qtype) in enumerate(NOT_ACTIVATED_QUESTIONS, start=1):
        b = _not_activated_builder(tmp_path, 550 + idx)
        text = b.build_and_render(question)
        assert text is not None, question
        assert f"STATUS: NOT_ACTIVATED" in text, question
        for line in contract_lines:
            assert line in text, (question, line)
        for marker in CONTRACT_MARKERS:
            assert marker in text, (question, marker)
        # 退化措辞只允许出现在合同的否证说明里（≠ 之后）；
        # 数据/字段面（剥离合同行后）绝不得出现。
        body = text
        for line in contract_lines:
            body = body.replace(line, "")
        for bad in FORBIDDEN_PHRASINGS:
            assert bad not in body, (question, bad, body)
        # 语义字段：未激活 → 绝不出现“0 / Year 0”式伪事实
        assert "UNKNOWN" in text or "NOT_STARTED" in text or \
            "NONE_OFFICIAL" in text, question


def test_m5q55b_not_activated_semantics_per_intent(tmp_path):
    """逐 intent 的 canonical 未激活语义。"""
    checks = {
        QueryType.WORLD_STATUS: ("NOT_ACTIVATED",),
        QueryType.POPULATION: ("UNKNOWN", "（正式世界未激活）"),
        QueryType.WORLD_TIME: ("NOT_STARTED", "NULL"),
        QueryType.HISTORY: ("NONE_OFFICIAL",),
        QueryType.TRIBULATION: ("UNKNOWN", "下一次灾劫"),
    }
    for idx, (question, qtype) in enumerate(NOT_ACTIVATED_QUESTIONS, start=1):
        b = _not_activated_builder(tmp_path, 560 + idx)
        text = b.build_and_render(question)
        for needle in checks[qtype]:
            assert needle in text, (question, needle)


def test_m5q56_not_activated_render_deterministic(tmp_path):
    b1 = _not_activated_builder(tmp_path, 570)
    b2 = _not_activated_builder(tmp_path, 571)
    for question, _ in NOT_ACTIVATED_QUESTIONS:
        assert b1.build_and_render(question) == b2.build_and_render(question)


# ---------------------------------------------- ProviderRequest 集成（§9）
class _FakeEvent:
    def __init__(self, text: str):
        self.message_str = text


class _FakeRequest:
    def __init__(self):
        self.extra_user_content_parts: list = []


@pytest.fixture()
def m5_not_activated_plugin(monkeypatch, tmp_path):
    """live 同形 harness：插件自建 schema（world_runtime 0 行 = NOT_ACTIVATED）。"""
    data_root = tmp_path / "astrbot_data"
    plugin_data_dir = data_root / "plugin_data" / PACKAGE_NAME
    monkeypatch.setenv("BLR_TEST_PLUGIN_DATA_DIR", str(plugin_data_dir))
    monkeypatch.setenv("BLR_STUB_PLUGIN_DATA_ROOT",
                       str(data_root / "plugin_data"))
    monkeypatch.syspath_prepend(str(REPO_ROOT / "tests" / "stub_astrbot"))
    monkeypatch.syspath_prepend(str(REPO_ROOT.parent))
    from astrbot.api.event.filter import reset_registry
    reset_registry()
    import sys
    full_name = f"{PACKAGE_NAME}.main"
    main_mod = (importlib.reload(sys.modules[full_name])
                if full_name in sys.modules
                else importlib.import_module(full_name))
    return {"plugin_cls": main_mod.BlessedLandRuntimePlugin}


def test_m5q57_provider_request_injection_counts(m5_not_activated_plugin, tmp_path):
    """Q1–Q5 每请求恰 1 份世界上下文；Q6 零注入；无重复注入。"""
    from astrbot.api import AstrBotConfig
    from astrbot.api.star import Context
    plugin = m5_not_activated_plugin["plugin_cls"](
        Context(),
        AstrBotConfig({"runtime_enabled": True, "scheduler_enabled": False,
                       "query_integration_enabled": True}))
    asyncio.run(plugin.initialize())
    try:
        expect = ((Q1, 1), (Q2, 1), (Q3, 1), (Q4, 1), (Q5, 1), (Q6, 0))
        for question, want in expect:
            req = _FakeRequest()
            asyncio.run(plugin._on_llm_request_world_context(
                _FakeEvent(question), req))
            got = len(req.extra_user_content_parts)
            assert got == want, (question, got, want)
            assert got <= 1, ("duplicate injection", question)
            if want == 1:
                part = req.extra_user_content_parts[0]
                assert part.text.startswith("[Blessed Land Runtime")
                assert NOT_ACTIVATED_AUTHORITATIVE_RULE in part.text
                assert "STRICT_NOT_ACTIVATED_CONSTRAINTS" in part.text
                assert getattr(part, "_temp", False) is True
        # 同一请求对象内重复调用 hook（模拟重入）仍不得出现重复块
        req = _FakeRequest()
        asyncio.run(plugin._on_llm_request_world_context(_FakeEvent(Q2), req))
        assert len(req.extra_user_content_parts) == 1
    finally:
        asyncio.run(plugin.terminate())
