# -*- coding: utf-8 -*-
"""stub astrbot.api.event.filter：on_llm_request 装饰器 + 注册表（测试 harness）。"""
from __future__ import annotations

# 全局注册表：hook 名 -> [handler, ...]（测试可清空/断言）
HOOK_REGISTRY: dict[str, list] = {}


def on_llm_request(*args, **kwargs):  # noqa: ANN002, ANN003
    """桩装饰器：把函数登记到 HOOK_REGISTRY（与真实实现同为注册语义）。"""

    def decorator(fn):
        HOOK_REGISTRY.setdefault("on_llm_request", []).append(fn)
        return fn

    return decorator


def reset_registry() -> None:
    HOOK_REGISTRY.clear()
