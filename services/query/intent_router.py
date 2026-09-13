# -*- coding: utf-8 -*-
"""WorldQueryIntentRouter（M5 §10）—— 确定性路由，零 LLM。

关键词/类别映射 + 固定优先级；普通闲聊默认 NO_WORLD_CONTEXT。
路由只决定"要不要注入、注入哪类上下文"，不产生任何世界事实。
"""
from __future__ import annotations

import re

from .query_models import QueryType

# 类别关键词（小写匹配；同类别内命中任一词即可）
_CATEGORY_KEYWORDS: dict[QueryType, tuple[str, ...]] = {
    QueryType.TRIBULATION: (
        "灾劫", "劫难", "劫", "灾难", "天灾", "排劫", "移劫", "渡劫"),
    QueryType.POPULATION: (
        "人口", "多少人", "居民", "人丁", "出生", "死亡", "移民"),
    QueryType.SETTLEMENT: (
        "聚落", "城镇", "定居", "村落", "领地", "疆域"),
    QueryType.RESOURCE_ECONOMY: (
        "资源", "矿产", "库存", "生产", "经济", "贸易", "储备", "开采"),
    QueryType.ECOLOGY: ("生态", "环境", "植被", "土地"),
    QueryType.SOCIAL: ("社会", "家族", "宗门", "机构", "族群", "礼制"),
    QueryType.WORLD_TIME: (
        "时间", "年份", "纪年", "哪年", "几点", "日期"),
    QueryType.HISTORY: (
        "历史", "时间线", "过去", "最近", "发生了什么", "大事"),
    QueryType.CAUSAL_EXPLANATION: ("为什么", "为何", "原因", "怎么变"),
    QueryType.CHANGES_SINCE: ("离开", "不在", "期间", "变化", "改变了"),
    QueryType.WORLD_STATUS: ("怎么样", "状态", "情况", "激活", "启动"),
    QueryType.DEEP_WORLD_QUERY: ("详细", "全部", "完整", "所有"),
}

# 表达形态 pattern（M5.1 真人聊天验收 DEFECT B）：仅用少量明确 pattern 覆盖
# 合理中文表达，取代无限堆关键词。典型缺口：字面「现在是哪一年？」不命中
# 关键词「哪年」（"哪一年" 不含子串 "哪年"）。
# 仍为确定性、零 LLM、纯本地匹配；不改变任何类别优先级。
_CATEGORY_PATTERNS: dict[QueryType, tuple[re.Pattern[str], ...]] = {
    QueryType.WORLD_TIME: (
        re.compile(r"哪(一)?年"),
        re.compile(r"什么年份"),
        re.compile(r"什么纪年"),
        re.compile(r"纪年.{0,4}(是什么|是啥|是多少|多少|几年|是几)"),
        re.compile(r"几几年"),
    ),
}

# 优先级：越具体越先匹配（WORLD_STATUS 在时间/历史前：catch-all 语义后置）
_PRIORITY = (
    QueryType.TRIBULATION,
    QueryType.CAUSAL_EXPLANATION,
    QueryType.CHANGES_SINCE,
    QueryType.POPULATION,
    QueryType.SETTLEMENT,
    QueryType.RESOURCE_ECONOMY,
    QueryType.ECOLOGY,
    QueryType.SOCIAL,
    QueryType.WORLD_STATUS,
    QueryType.WORLD_TIME,
    QueryType.HISTORY,
    QueryType.DEEP_WORLD_QUERY,
)


class WorldQueryIntentRouter:
    def __init__(self, keywords: dict[QueryType, tuple[str, ...]]
                 | None = None):
        self._keywords = keywords or _CATEGORY_KEYWORDS
        self._patterns = _CATEGORY_PATTERNS

    def _matches(self, qtype: QueryType, lowered: str) -> bool:
        """关键词 OR 表达形态 pattern；两者都是确定性本地匹配。"""
        for kw in self._keywords.get(qtype, ()):
            if kw in lowered:
                return True
        for pattern in self._patterns.get(qtype, ()):
            if pattern.search(lowered):
                return True
        return False

    def route(self, user_text: str) -> QueryType:
        """确定性路由。空/短闲聊 → NO_WORLD_CONTEXT。"""
        lowered = (user_text or "").lower()
        if not lowered.strip():
            return QueryType.NO_WORLD_CONTEXT
        for qtype in _PRIORITY:
            if self._matches(qtype, lowered):
                return qtype
        return QueryType.NO_WORLD_CONTEXT

    def route_explicit(self, user_text: str) -> QueryType:
        """显式结构信号优先：消息前缀 [world] / [runtime] / [福地] 视为
        DEEP_WORLD_QUERY（命令元数据路径）。"""
        lowered = (user_text or "").lower().strip()
        for marker in ("[world]", "[runtime]", "[福地]", "[blessed]"):
            if lowered.startswith(marker):
                return QueryType.DEEP_WORLD_QUERY
        return self.route(user_text)
