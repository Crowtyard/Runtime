# -*- coding: utf-8 -*-
"""M5 Query 数据模型（只读查询层）。

版本常量 + QueryType + Fact(provenance) + WorldContextCapsule。
所有模型 deterministic、可 JSON 序列化；不 import astrbot。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

# 版本（M5_QUERY_COMPANION_INTEGRATION_MANIFEST.json 同步冻结）
WORLD_QUERY_SCHEMA_VERSION = "world-query-v1"
WORLD_CONTEXT_CAPSULE_VERSION = "world-context-capsule-v1"
M5_INTEGRATION_VERSION = "m5-query-companion-v1"


class Authority(str, Enum):
    """事实权威级别。

    AUTHORITATIVE：数据库当前状态（世界真值）。
    DERIVED：对 authoritative 数据的确定性计算。
    STATIC_RULE：World Bible/本地 Canon 静态规则（不是动态事实；仅供静态引用）。
    禁止 LLM guessed 进入任何事实。
    """

    AUTHORITATIVE = "AUTHORITATIVE"
    DERIVED = "DERIVED"
    STATIC_RULE = "STATIC_RULE"


class QueryType(str, Enum):
    NO_WORLD_CONTEXT = "NO_WORLD_CONTEXT"
    WORLD_STATUS = "WORLD_STATUS"
    WORLD_TIME = "WORLD_TIME"
    POPULATION = "POPULATION"
    SETTLEMENT = "SETTLEMENT"
    RESOURCE_ECONOMY = "RESOURCE_ECONOMY"
    ECOLOGY = "ECOLOGY"
    SOCIAL = "SOCIAL"
    TRIBULATION = "TRIBULATION"
    HISTORY = "HISTORY"
    CAUSAL_EXPLANATION = "CAUSAL_EXPLANATION"
    CHANGES_SINCE = "CHANGES_SINCE"
    DEEP_WORLD_QUERY = "DEEP_WORLD_QUERY"


@dataclass(frozen=True)
class Fact:
    """带来源的查询事实（§13）。stable ordering 键：
    (fact_type, entity_id or "", as_of_tick or 0)。"""

    fact_type: str
    value: str
    authority: Authority = Authority.AUTHORITATIVE
    entity_id: str = ""
    source_table: str = ""
    source_event_id: str | None = None
    as_of_tick: int | None = None

    def sort_key(self) -> tuple:
        return (self.fact_type, self.entity_id or "",
                 self.as_of_tick if self.as_of_tick is not None else 0)

    def to_dict(self) -> dict:
        return {
            "fact_type": self.fact_type,
            "value": self.value,
            "authority": self.authority.value,
            "entity_id": self.entity_id,
            "source_table": self.source_table,
            "source_event_id": self.source_event_id,
            "as_of_tick": self.as_of_tick,
        }


@dataclass(frozen=True)
class CausalChain:
    """结构化因果链（M3b HistoryService 结果压缩）。"""

    head: str
    steps: tuple[str, ...]
    as_of_tick: int | None = None

    def sort_key(self) -> tuple:
        return (self.head, self.as_of_tick if self.as_of_tick is not None else 0)


@dataclass
class WorldContextCapsule:
    """注入模型的结构化世界上下文（§12/§52）。

    deterministic：facts/history/causal 全部 stable ordering；
    truncation 只整条裁剪，绝不随机截断。
    """

    runtime_status: str
    query_type: str
    as_of_tick: int | None
    as_of_world_date: str | None
    facts: list[Fact] = field(default_factory=list)
    history: list[str] = field(default_factory=list)
    causal_chains: list[CausalChain] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    provenance: list[Fact] = field(default_factory=list)
    truncation: dict = field(default_factory=dict)
    semantic_version: str = WORLD_CONTEXT_CAPSULE_VERSION
    source: str = "TEST_FIXTURE_ONLY"  # synthetic fixture 标记（§22）
    scheduler_state: str | None = None

    def to_dict(self) -> dict:
        return {
            "runtime_status": self.runtime_status,
            "query_type": self.query_type,
            "as_of_tick": self.as_of_tick,
            "as_of_world_date": self.as_of_world_date,
            "facts": [f.to_dict() for f in self.facts],
            "history": list(self.history),
            "causal_chains": [{"head": c.head, "steps": list(c.steps),
                               "as_of_tick": c.as_of_tick}
                              for c in self.causal_chains],
            "unknowns": list(self.unknowns),
            "provenance": [f.to_dict() for f in self.provenance],
            "truncation": dict(self.truncation),
            "semantic_version": self.semantic_version,
            "source": self.source,
            "scheduler_state": self.scheduler_state,
        }
