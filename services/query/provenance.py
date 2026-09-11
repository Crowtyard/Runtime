# -*- coding: utf-8 -*-
"""Fact provenance 与 stable ordering（M5）。

- AUTHORITATIVE / DERIVED / STATIC_RULE 三级；
- UNKNOWN 是合法结果（绝不自动补数字）；
- 排序全链路 stable：不依赖 SQL 物理顺序 / set 顺序。
"""
from __future__ import annotations

from .query_models import Authority, Fact

UNKNOWN = "UNKNOWN"
NONE_OFFICIAL = "NONE_OFFICIAL"
NOT_STARTED = "NOT_STARTED"


def fact(fact_type: str, value, *, authority: Authority = Authority.AUTHORITATIVE,
         entity_id: str = "", source_table: str = "",
         source_event_id: str | None = None,
         as_of_tick: int | None = None) -> Fact:
    """构造带来源事实；value 统一为字符串（数值由调用方格式化）。"""
    return Fact(fact_type=fact_type, value=str(value), authority=authority,
                entity_id=entity_id, source_table=source_table,
                source_event_id=source_event_id, as_of_tick=as_of_tick)


def stable_sorted(facts: list[Fact]) -> list[Fact]:
    """stable ordering：sort_key (fact_type, entity_id, as_of_tick)；
    同键保持插入序（Python sort 稳定）。"""
    return sorted(facts, key=lambda f: f.sort_key())


def sanitize_value(raw: str, *, max_len: int = 160) -> str:
    """DATA 渲染清理（§26 prompt injection 防护）：
    剥离控制字符/换行，长度上限；数据永远是数据，不是指令。"""
    cleaned = "".join(
        ch for ch in str(raw) if ch in "\t" or (32 <= ord(ch) < 127)
        or ord(ch) >= 0x4E00)  # 保留可打印 ASCII + CJK 基础面
    cleaned = cleaned.replace("\t", " ")
    if len(cleaned) > max_len:
        cleaned = cleaned[: max_len - 3] + "..."
    return cleaned
