# -*- coding: utf-8 -*-
"""services.query —— M5 只读世界查询层。

READ ONLY；NOT_ACTIVATED → UNKNOWN；NULL ≠ 0；History 复用 M3b；
无 LLM / 无网络 / 不读取 World Seed / 不 import astrbot。
"""
from .context_builder import ContextBuilder
from .intent_router import WorldQueryIntentRouter
from .provenance import UNKNOWN, fact
from .query_models import (Authority, Fact, QueryType, WorldContextCapsule,
                           WORLD_CONTEXT_CAPSULE_VERSION,
                           WORLD_QUERY_SCHEMA_VERSION)
from .world_query_service import (ReadOnlyGuard, WorldQueryService)

__all__ = [
    "Authority", "Fact", "QueryType", "WorldContextCapsule",
    "WORLD_CONTEXT_CAPSULE_VERSION", "WORLD_QUERY_SCHEMA_VERSION",
    "WorldQueryService", "ReadOnlyGuard", "ContextBuilder",
    "WorldQueryIntentRouter", "UNKNOWN", "fact",
]
