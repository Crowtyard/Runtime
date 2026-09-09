# -*- coding: utf-8 -*-
"""M3b 历史层冻结语义：关系词表 / 节点类型 / tick 规则 / 排序 / identity。

本模块是 History Graph 的 vocabulary 契约。新增 relation 必须在此登记
并提升 HISTORY_SCHEMA_VERSION（或独立升级 causal_history_hash schema）。
"""
from __future__ import annotations

# History 层语义版本（独立于 simulation_version；纯索引不改变模拟结果）
HISTORY_SCHEMA_VERSION = "history-v1"
CAUSAL_LINK_ID_SCHEMA_VERSION = "causal-link-id-v1"
CAUSAL_HISTORY_HASH_SCHEMA_VERSION = "causal-history-hash-v1"

# 节点类型（kind）。source_id/target_id 按 kind 解析：
#   EVENT → world_events.event_uid
#   STATE_CHANGE → world_state_changes.id
#   EPISODE → history_episode_index.episode_id（含 tribulation episode）
#   PLAN → tribulation_impact_plans.plan_id
#   DECISION → tribulation_decisions.decision_id
#   RECOVERY_STATE → tribulation_recovery_states（episode_id 定位）
#   RESIDUAL → tribulation_residual_changes.id
#   SUCCESSION → resource_succession_candidates.candidate_id
#   ENTITY → (entity_type, entity_id) 通用实体
#   CHECKPOINT → simulation_checkpoints（checkpoint 引用）
NODE_KINDS = ("EVENT", "STATE_CHANGE", "EPISODE", "PLAN", "DECISION",
              "RECOVERY_STATE", "RESIDUAL", "SUCCESSION", "ENTITY",
              "CHECKPOINT")

# 关系词表（冻结；新增须版本化）
# 方向约定：source = 解释/前因，target = 被解释/结果；trace 只走入边。
CAUSES = "CAUSES"                    # 前因后果（DAG 语义，禁环）
TRIGGERS = "TRIGGERS"                # 触发（前向因果）
RESULTS_IN = "RESULTS_IN"            # 导致（前向因果）
AFFECTS = "AFFECTS"                  # 影响（前向因果；事件/计划 → 状态/实体）
CONTINUES = "CONTINUES"              # 延续（前状态 → 后状态/后阶段）
RECOVERS_FROM = "RECOVERS_FROM"      # 恢复自（冲击 → 恢复状态）
CORRECTS = "CORRECTS"                # 纠正（retrospective，显式分类）
SUPERSEDES = "SUPERSEDES"            # 取代（retrospective；supersede 链禁环）
REVERSES = "REVERSES"                # 反转（retrospective）
DECIDED_BY = "DECIDED_BY"            # 由…决定（决策 → 计划）
PART_OF_EPISODE = "PART_OF_EPISODE"  # 属于 episode（事件 → episode；归属边，不参与 trace）
DERIVED_FROM = "DERIVED_FROM"        # 派生自（源头 → 派生体）
MATERIALIZES_IN = "MATERIALIZES_IN"  # 物化为（候选 → 实体）

RELATION_TYPES = (CAUSES, TRIGGERS, RESULTS_IN, AFFECTS, CONTINUES,
                  RECOVERS_FROM, CORRECTS, SUPERSEDES, REVERSES,
                  DECIDED_BY, PART_OF_EPISODE, DERIVED_FROM,
                  MATERIALIZES_IN)

# tick 规则（source_tick vs target_tick，仅双方均解析出 tick 时校验）：
#   FORWARD  source_tick <= target_tick（禁止 Year100 造成 Year50 状态）
#   BACKWARD source_tick >= target_tick（归属边：事件 tick ≥ episode 进入 tick）
#   FREE     retrospective correction（显式分类，绝不使用 CAUSES）
#   NONE     任一方无 tick（如 PLAN 节点）→ 不校验
TICK_FORWARD = "FORWARD"
TICK_BACKWARD = "BACKWARD"
TICK_FREE = "FREE"
TICK_NONE = "NONE"

RELATION_TICK_RULES = {
    CAUSES: TICK_FORWARD, TRIGGERS: TICK_FORWARD, RESULTS_IN: TICK_FORWARD,
    AFFECTS: TICK_FORWARD,
    CONTINUES: TICK_FORWARD, RECOVERS_FROM: TICK_FORWARD,
    DERIVED_FROM: TICK_FORWARD, MATERIALIZES_IN: TICK_FORWARD,
    PART_OF_EPISODE: TICK_BACKWARD,
    DECIDED_BY: TICK_NONE,
    CORRECTS: TICK_FREE, SUPERSEDES: TICK_FREE, REVERSES: TICK_FREE,
}

# trace 走的关系（解释边；不含 PART_OF_EPISODE 归属边）
TRACE_RELATIONS = frozenset((
    CAUSES, TRIGGERS, RESULTS_IN, AFFECTS, CONTINUES, RECOVERS_FROM,
    DECIDED_BY, DERIVED_FROM, MATERIALIZES_IN, CORRECTS, SUPERSEDES,
    REVERSES))

# 禁环集合：除 correction 三关系外全部 DAG-like（插入时深度受限检测）
CYCLE_FORBIDDEN_RELATIONS = frozenset(
    r for r in RELATION_TYPES if r not in (CORRECTS, SUPERSEDES, REVERSES))

# 确定性排序优先级（tick 相同 / 无 tick 时的 tie-break；越小越先）
RELATION_PRIORITY = {
    CAUSES: 0, TRIGGERS: 1, RESULTS_IN: 2, AFFECTS: 3, DECIDED_BY: 4,
    CONTINUES: 5, RECOVERS_FROM: 6, DERIVED_FROM: 7, PART_OF_EPISODE: 8,
    MATERIALIZES_IN: 9, CORRECTS: 10, SUPERSEDES: 11, REVERSES: 12,
}

# 冻结排序规则（§9）：committed_tick → relation priority → source_id →
# target_id → link_id。禁止 DB physical row order / Python set order /
# wall-clock。
LINK_ORDER_KEY_FIELDS = ("committed_tick", "relation_priority", "source_id",
                         "target_id", "link_id")

# 插入时禁环检测的深度上限（因果链实际很短；防御性上限防恶意深链）
CYCLE_CHECK_MAX_DEPTH = 64
