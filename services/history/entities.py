# -*- coding: utf-8 -*-
"""M3b 实体注册表：entity_type → ORM 模型 / scope 键（payload 匹配用）。

entity_type 与 world_state_changes.entity_type 一致（= 快照表名）。
scope 键：事件 payload（cause/effect）中出现的、可把事件归属到该实体的
字段值集合（确定性匹配；不猜测）。
"""
from __future__ import annotations

from ...database.models_world import (EcologyFeedbackState, EcologyState,
                                      EconomicPressureState, Household,
                                      Industry, Institution, Lineage,
                                      PopulationGroup, ProductionState,
                                      ResourceNode, ResourceStock,
                                      Settlement, SettlementSocialState,
                                      SocialFeedbackState)

ENTITY_MODELS = {
    "settlements": Settlement,
    "population_groups": PopulationGroup,
    "resource_nodes": ResourceNode,
    "resource_stocks": ResourceStock,
    "industries": Industry,
    "lineages": Lineage,
    "institutions": Institution,
    "production_state": ProductionState,
    "economic_pressure_state": EconomicPressureState,
    "ecology_state": EcologyState,
    "ecology_feedback_state": EcologyFeedbackState,
    "households": Household,
    "settlement_social_state": SettlementSocialState,
    "social_feedback_state": SocialFeedbackState,
}

# 事件 payload 匹配用的 scope 键（按表冻结）；值为 None 的键跳过。
SCOPE_KEYS = {
    "settlements": ("working_name",),
    "population_groups": ("settlement_ref", "species"),
    "resource_nodes": ("region_ref", "settlement_relation",
                       "resource_profile_ref"),
    "resource_stocks": ("settlement_ref", "resource_profile_ref"),
    "production_state": ("settlement_ref", "recipe_ref"),
    "economic_pressure_state": ("settlement_ref", "resource_profile_ref"),
    "ecology_state": ("zone_ref",),
    "ecology_feedback_state": ("zone_ref",),
    "households": ("settlement_ref", "household_id", "lineage_ref"),
    "settlement_social_state": ("settlement_ref",),
    "social_feedback_state": ("settlement_ref",),
    "institutions": ("settlement_ref", "institution_id"),
    "lineages": ("origin_settlement", "lineage_id"),
    "industries": ("node_ref",),
}

# 记账字段：引擎元数据而非世界事实 → 不进 world_state_changes 账本
BOOKKEEPING_FIELDS = frozenset({
    "engine_version", "state_version", "updated_blessed_tick",
    "demography_version", "semantic_version"})
