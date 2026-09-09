# -*- coding: utf-8 -*-
"""M3b Causal World History（只读查询 + 历史索引构建）。

子模块：
- relations：冻结关系词表 / 节点类型 / tick 规则 / 排序规则 / link id scheme
- builder：HistoryLinkBuilder（模拟事务内构建索引；0 LLM/网络/wall-clock）
- service：HistoryService（只读查询；0 mutation）
- corrections：Correction API（append-only；CORRECTS/SUPERSEDES/REVERSES）
"""
from .relations import (CAUSAL_LINK_ID_SCHEMA_VERSION,  # noqa: F401
                        CAUSAL_HISTORY_HASH_SCHEMA_VERSION,
                        HISTORY_SCHEMA_VERSION, NODE_KINDS, RELATION_TYPES,
                        RELATION_TICK_RULES, RELATION_PRIORITY)
from .builder import HistoryLinkBuilder  # noqa: F401
from .service import HistoryService  # noqa: F401
