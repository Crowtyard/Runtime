#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""M5 真实 AstrBot 环境 smoke —— 真实 hook 机制面（§34/§55）。

用 live 实例的真实 astrbot 包（独立进程；不触碰 live 数据；不注册进 live
进程；不 import 本插件包，避免 live venv 缺失纯 Python 依赖）验证：

1. 真实 star_handlers_registry 的注册与去重（按 module_name 唯一，
   reload 不产生 duplicate handler）——用与本插件完全相同的装饰器与
   签名形态的 scratch handler 实测；
2. 真实 ProviderRequest.extra_user_content_parts 注入语义：append
   TextPart + mark_as_temp 后可被 runner 消费（is_temp 标记存在、列表
   为普通 list append 语义）——本插件 handler 对 req 的唯一操作即
   `req.extra_user_content_parts.append(TextPart(text=...).mark_as_temp())`，
   该注入面在此真实对象上逐字段验证。

插件 handler 的完整语义（NOT_ACTIVATED → UNKNOWN / 零注入闲聊 /
NOT_STARTED 等）由 tests/test_query_astrbot_hook.py + tests/test_query_*.py
在 stub 与 synthetic fixture 上覆盖；ProviderRequest.extra_user_content_parts
字段类型（list[ContentPart]）已从真实源码 entities.py 确认。

运行：
    <live venv python> scripts/m5_real_astrbot_smoke.py
"""
from __future__ import annotations

import importlib
import os
import sys
import tempfile
from pathlib import Path

# 防止真实 astrbot import 在调用方 cwd 产生 data/ 等副作用文件：
# 必须在任何 astrbot import 之前 chdir 到独立临时目录
os.chdir(tempfile.mkdtemp(prefix="m5_smoke_cwd_"))

REPO = Path(__file__).resolve().parent.parent
LIVE_CORE = Path(
    r"C:\Users\Crowtyard\.astrbot_launcher\instances"
    r"\f76fe2fd-8c03-4ba2-b4d6-467d1645ed0d\core")

sys.path.insert(0, str(LIVE_CORE))

import astrbot  # noqa: E402
from astrbot.api.event.filter import on_llm_request  # noqa: E402
from astrbot.core.agent.message import TextPart  # noqa: E402
from astrbot.core.provider.entities import ProviderRequest  # noqa: E402
from astrbot.core.star.star_handler import (  # noqa: E402
    star_handlers_registry)

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}")
    if not ok:
        failures.append(name)


def main() -> int:
    print("astrbot from:", astrbot.__file__)
    print("smoke cwd:", os.getcwd())

    # ---- 1) 注册 + reload 去重（真实注册器，独立 temp 模块模拟插件热重载）
    import tempfile
    scratch_dir = Path(tempfile.mkdtemp(prefix="m5_scratch_star_"))
    scratch_mod = scratch_dir / "m5_scratch_star.py"
    scratch_mod.write_text(
        "from astrbot.api.event.filter import on_llm_request\n"
        "from astrbot.core.agent.message import TextPart\n"
        "class _ScratchStar:\n"
        "    @on_llm_request()\n"
        "    async def _on_llm_request_world_context(self, event, req):\n"
        "        req.extra_user_content_parts.append(\n"
        "            TextPart(text='[Blessed Land Runtime — smoke]')"
        ".mark_as_temp())\n",
        encoding="utf-8")
    sys.path.insert(0, str(scratch_dir))
    mod1 = importlib.import_module("m5_scratch_star")
    mod1._ScratchStar()
    after_first = star_handlers_registry.get_handlers_by_module_name(
        "m5_scratch_star")
    check("real_registry_registered", len(after_first) >= 1)
    # 模拟插件热重载：同 module 名重新执行类定义（新函数对象、同名）
    mod2 = importlib.reload(mod1)
    mod2._ScratchStar()
    after_reload = star_handlers_registry.get_handlers_by_module_name(
        "m5_scratch_star")
    check("duplicate_hooks_after_reload", len(after_reload) == 1,
          f"（真实注册器按 module_name+handler_name 去重，"
          f"count={len(after_reload)}）")
    star_handlers_registry.clear()  # 独立进程内清理（不影响 live 实例）

    # ---- 2) 真实 ProviderRequest 注入面
    req = ProviderRequest(prompt="福地现在怎么样？")
    check("extra_user_content_parts_is_plain_list",
          isinstance(req.extra_user_content_parts, list))
    part = TextPart(text="[Blessed Land Runtime — Authoritative World "
                          "Context]\nSTATUS: NOT_ACTIVATED").mark_as_temp()
    req.extra_user_content_parts.append(part)
    check("injection_append_once", len(req.extra_user_content_parts) == 1)
    check("injection_is_textpart", isinstance(
        req.extra_user_content_parts[0], TextPart))
    check("injection_marked_temp",
          getattr(req.extra_user_content_parts[0], "_no_save", False)
          is True, "（mark_as_temp → _no_save，不进持久记忆）")
    check("provider_request_fields_intact",
          req.prompt is not None and req.system_prompt == "")

    # ---- 3) 不修改 persona 面的契约：hook 只允许 append，其余字段可空
    check("persona_fields_untouched_by_append",
          req.system_prompt == "" and req.contexts == [])

    print()
    if failures:
        print("SMOKE_FAILED:", failures)
        return 1
    print("M5_REAL_ASTRBOT_SMOKE = PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
