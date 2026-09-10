# -*- coding: utf-8 -*-
"""world_state_hash（WORLD_STATE_HASH_SCHEMA_VERSION=2/3/4/5/6）。

- v2（M2a 冻结）：只覆盖 M2a 状态域（7 张表 + M2a 字段集）。
- v3（M2b 冻结）：只覆盖 M2b 状态域（12 张表 + M2b 字段集，不含 M2c
  生态表/字段）—— M2b 120y 基线逐字节复现依赖此冻结。
- v4（M2c 冻结）：只覆盖 M2c 状态域（15 张表 + M2c 字段集，不含 M2d
  社会表/字段）—— M2c 120y 基线逐字节复现依赖此冻结。
- v5（M2d 冻结）：只覆盖 M2d 状态域（18 张表 + M2d 字段集，不含 M3a
  灾劫表/字段）—— M2d 120y 基线逐字节复现依赖此冻结。
- v6（M3a）：覆盖快照全状态域（含 Tribulation 九表）。仅在注册
  TRIBULATION 引擎的 simulation_version 下使用。
- canonical serialization：UTF-8 JSON（sort_keys + 紧凑分隔符）+ 实体按语义
  键排序（snapshot._canonical）；禁止行物理顺序/autoincrement 顺序/now()
  时间戳/日志元数据/事件日志作为输入。
"""
from __future__ import annotations

import hashlib
import json

from .snapshot import WorldSnapshot

WORLD_STATE_HASH_SCHEMA_VERSION = 6  # 当前（M3a）
WORLD_STATE_HASH_SCHEMA_VERSION_V2 = 2  # M2a 冻结（回归基线）
WORLD_STATE_HASH_SCHEMA_VERSION_V3 = 3  # M2b 冻结（回归基线）
WORLD_STATE_HASH_SCHEMA_VERSION_V4 = 4  # M2c 冻结（回归基线）
WORLD_STATE_HASH_SCHEMA_VERSION_V5 = 5  # M2d 冻结（回归基线）

# M2a 冻结表集（v2 只哈希这 7 张表，绝不因 snapshot 扩展而漂移）
_V2_TABLES = frozenset({
    "settlements", "population_groups", "resource_nodes", "industries",
    "ecological_regions", "lineages", "institutions"})

# M2a 冻结字段集（v2 每表只取这些字段；resource_nodes 不含 M2b 扩展列）
_V2_FIELDS = {
    "settlements": ("id", "world_id", "settlement_type", "region_ref",
                    "working_name", "state", "population_capacity", "meta"),
    "population_groups": ("id", "world_id", "species", "settlement_ref",
                          "age_cohort", "occupation_group", "count",
                          "age_advance_carry_ticks", "species_profile_ref",
                          "demography_version", "updated_blessed_tick"),
    "resource_nodes": ("id", "world_id", "kind", "region_ref", "state"),
    "industries": ("id", "world_id", "kind", "node_ref", "labor",
                   "capacity", "state"),
    "ecological_regions": ("id", "world_id", "terrain", "climate", "water",
                           "danger_level", "carrying_capacity", "state"),
    "lineages": ("id", "world_id", "lineage_type", "head_person_ref",
                 "member_ids"),
    "institutions": ("id", "world_id", "kind", "settlement_ref",
                     "owner_ref", "state", "capacity"),
}

# M2b 冻结表集（v3；不含 M2c 生态表）
_V3_TABLES = frozenset({
    "settlements", "population_groups", "resource_nodes", "industries",
    "ecological_regions", "lineages", "institutions",
    "resource_profiles", "resource_stocks", "production_recipes",
    "production_state", "economic_pressure_state"})

# M2b 冻结字段集（v3；resource_nodes 不含 M2c 两列）
_V3_FIELDS = {
    "settlements": ("id", "world_id", "settlement_type", "region_ref",
                    "working_name", "state", "population_capacity", "meta"),
    "population_groups": ("id", "world_id", "species", "settlement_ref",
                          "age_cohort", "occupation_group", "count",
                          "age_advance_carry_ticks", "species_profile_ref",
                          "demography_version", "updated_blessed_tick"),
    "resource_nodes": ("id", "world_id", "kind", "region_ref", "state",
                       "resource_profile_ref", "settlement_relation",
                       "remaining_reserve", "extraction_capacity",
                       "extraction_carry", "last_extracted_minor",
                       "engine_version", "state_version",
                       "updated_blessed_tick"),
    "industries": ("id", "world_id", "kind", "node_ref", "labor",
                   "capacity", "state"),
    "ecological_regions": ("id", "world_id", "terrain", "climate", "water",
                           "danger_level", "carrying_capacity", "state"),
    "lineages": ("id", "world_id", "lineage_type", "head_person_ref",
                 "member_ids"),
    "institutions": ("id", "world_id", "kind", "settlement_ref",
                     "owner_ref", "state", "capacity"),
    "resource_profiles": ("id", "world_id", "resource_id", "unit",
                          "quantity_scale", "renewability", "extractability",
                          "consumption_category", "production_usability",
                          "semantic_version"),
    "resource_stocks": ("id", "world_id", "settlement_ref",
                        "resource_profile_ref", "quantity",
                        "consumption_carry", "cum_extracted_minor",
                        "cum_produced_minor", "cum_input_minor",
                        "cum_imported_minor", "cum_exported_minor",
                        "cum_consumed_minor", "cum_lost_minor",
                        "engine_version", "updated_blessed_tick"),
    "production_recipes": ("id", "world_id", "recipe_id",
                           "input_resource_ref", "input_qty_minor",
                           "output_resource_ref", "output_qty_minor",
                           "capacity_batches_per_year", "labor_per_batch",
                           "loss_num", "loss_den", "semantic_version"),
    "production_state": ("id", "world_id", "settlement_ref", "recipe_ref",
                         "production_carry", "engine_version",
                         "updated_blessed_tick"),
    "economic_pressure_state": ("id", "world_id", "settlement_ref",
                                "resource_profile_ref", "demand_minor",
                                "fulfilled_minor", "unmet_minor",
                                "shortage_ratio_num", "shortage_ratio_den",
                                "sustained_shortage_steps", "stress_level",
                                "engine_version", "updated_blessed_tick"),
}


# M2c 冻结表集（v4；不含 M2d 社会表；lineages/institutions 用 M2c 字段集）
_V4_TABLES = _V3_TABLES | frozenset({
    "ecology_zones", "ecology_state", "ecology_feedback_state"})

# M2c 冻结字段集（v4；社会表不在内；resource_nodes 含 M2c 两列；
# lineages/institutions 保持 M0 字段）
_V4_FIELDS = dict(_V3_FIELDS)
_V4_FIELDS["resource_nodes"] = (
    "id", "world_id", "kind", "region_ref", "state",
    "resource_profile_ref", "settlement_relation",
    "remaining_reserve", "extraction_capacity",
    "extraction_carry", "last_extracted_minor",
    "engine_version", "state_version", "updated_blessed_tick",
    "reserve_ceiling_minor", "regeneration_carry")
_V4_FIELDS.update({
    "ecology_zones": ("id", "world_id", "zone_id", "region_ref",
                      "settlement_relation", "profile_ref",
                      "semantic_version"),
    "ecology_state": ("id", "world_id", "zone_ref", "habitat_quality",
                      "regeneration_capacity", "ecological_stress",
                      "population_pressure", "extraction_pressure",
                      "production_pressure", "depletion_pressure",
                      "external_pressure", "degradation_carry",
                      "recovery_carry", "quality_min_seen",
                      "quality_max_seen", "engine_version",
                      "updated_blessed_tick"),
    "ecology_feedback_state": ("id", "world_id", "zone_ref",
                               "regeneration_capacity_minor_per_year",
                               "yield_modifier_num", "yield_modifier_den",
                               "extraction_modifier_num",
                               "extraction_modifier_den",
                               "habitat_stress_level",
                               "environmental_stress_num",
                               "environmental_stress_den", "engine_version",
                               "updated_blessed_tick"),
})

# M2d 冻结表集/字段集（v5；不含 M3a 灾劫九表）
# 注意（FROZEN_SEMANTICS_RESTORATION）：lineages/institutions 必须使用
# M2d 时代全字段（含 lineage_id/origin_settlement/represented_population/
# household_count/generation/status/founded_tick/parent_lineage_ref/
# semantic_version/updated_blessed_tick 与 institution_id/founded_tick/
# profile_ref/updated_blessed_tick）——M3a 冻结 v5 时误继承了 v4 的
# M0 最小字段，导致 v5 无法逐字节复现权威 M2d 基线 final_world_state_hash
# 7cd769e0…（当时活 v5 = dict(snapshot._FIELDS)，见 ac64d72）。本修复
# 只恢复冻结语义，不改变任何 simulation algorithm / M3a / M3b 冻结值。
_V5_TABLES = _V4_TABLES | frozenset({
    "households", "settlement_social_state", "social_feedback_state"})
_V5_FIELDS = dict(_V4_FIELDS)
_V5_FIELDS.update({
    "lineages": ("id", "world_id", "lineage_type", "head_person_ref",
                 "member_ids", "lineage_id", "origin_settlement",
                 "represented_population", "household_count", "generation",
                 "status", "founded_tick", "parent_lineage_ref",
                 "semantic_version", "updated_blessed_tick"),
    "institutions": ("id", "world_id", "kind", "settlement_ref",
                     "owner_ref", "state", "capacity", "institution_id",
                     "founded_tick", "profile_ref", "updated_blessed_tick"),
    "households": ("id", "world_id", "household_id", "settlement_ref",
                   "species", "represented_population", "generation",
                   "lineage_ref", "anchor_group_ref", "state",
                   "formation_version", "updated_blessed_tick"),
    "settlement_social_state": ("id", "world_id", "settlement_ref",
                                "social_stress", "social_cohesion",
                                "household_stability", "mobility_pressure",
                                "unallocated_population",
                                "stress_min_seen", "stress_max_seen",
                                "engine_version", "updated_blessed_tick"),
    "social_feedback_state": ("id", "world_id", "settlement_ref",
                              "migration_modifier_num",
                              "migration_modifier_den",
                              "fertility_context_num",
                              "fertility_context_den", "social_support_num",
                              "social_support_den", "social_stress_num",
                              "social_stress_den", "engine_version",
                              "updated_blessed_tick"),
})


def _build_doc(*, snapshot: WorldSnapshot, simulation_version: str,
               pipeline_version: str, engine_versions: dict[str, str],
               schema_version: int, table_fields: dict[str, tuple[str, ...]]
               ) -> dict:
    doc = {
        "schema_version": schema_version,
        "world_id": snapshot.world_id,
        "clock": {
            "blessed_tick": snapshot.blessed_tick,
            "last_committed_real_us": snapshot.last_committed_real_us,
            "time_rate_remainder": snapshot.time_rate_remainder,
            "current_time_ratio_id": snapshot.current_time_ratio_id,
        },
        "simulation_version": simulation_version,
        "pipeline_version": pipeline_version,
        "engine_versions": dict(sorted(engine_versions.items())),
        "tables": {
            t: [_strip(row, table_fields[t]) for row in snapshot.rows(t)]
            for t in sorted(table_fields)
        },
    }
    return doc


def _strip(row: dict, fields: tuple[str, ...]) -> dict:
    """只保留版本冻结字段，并排除 autoincrement id（插入顺序依赖）。"""
    return {k: row[k] for k in fields if k != "id" and k in row}


def world_state_hash_v2(*, snapshot: WorldSnapshot, simulation_version: str,
                        pipeline_version: str,
                        engine_versions: dict[str, str]) -> str:
    """M2a 冻结 v2（回归基线专用；语义永不变化）。"""
    doc = _build_doc(
        snapshot=snapshot, simulation_version=simulation_version,
        pipeline_version=pipeline_version, engine_versions=engine_versions,
        schema_version=WORLD_STATE_HASH_SCHEMA_VERSION_V2,
        table_fields={t: _V2_FIELDS[t] for t in sorted(_V2_TABLES)})
    return _digest(doc)


def world_state_hash_v3(*, snapshot: WorldSnapshot, simulation_version: str,
                        pipeline_version: str,
                        engine_versions: dict[str, str]) -> str:
    """M2b 冻结 v3（回归基线专用；覆盖 M2b 12 表状态域，语义永不变化）。"""
    doc = _build_doc(
        snapshot=snapshot, simulation_version=simulation_version,
        pipeline_version=pipeline_version, engine_versions=engine_versions,
        schema_version=WORLD_STATE_HASH_SCHEMA_VERSION_V3,
        table_fields={t: _V3_FIELDS[t] for t in sorted(_V3_TABLES)})
    return _digest(doc)


def world_state_hash_v4(*, snapshot: WorldSnapshot, simulation_version: str,
                        pipeline_version: str,
                        engine_versions: dict[str, str]) -> str:
    """M2c 冻结 v4（回归基线专用；覆盖 M2c 15 表状态域，语义永不变化）。"""
    doc = _build_doc(
        snapshot=snapshot, simulation_version=simulation_version,
        pipeline_version=pipeline_version, engine_versions=engine_versions,
        schema_version=WORLD_STATE_HASH_SCHEMA_VERSION_V4,
        table_fields={t: _V4_FIELDS[t] for t in sorted(_V4_TABLES)})
    return _digest(doc)


def world_state_hash_v5(*, snapshot: WorldSnapshot, simulation_version: str,
                        pipeline_version: str,
                        engine_versions: dict[str, str]) -> str:
    """M2d 冻结 v5（回归基线专用；覆盖 M2d 18 表状态域，语义永不变化）。"""
    doc = _build_doc(
        snapshot=snapshot, simulation_version=simulation_version,
        pipeline_version=pipeline_version, engine_versions=engine_versions,
        schema_version=WORLD_STATE_HASH_SCHEMA_VERSION_V5,
        table_fields={t: _V5_FIELDS[t] for t in sorted(_V5_TABLES)})
    return _digest(doc)


def world_state_hash_v6(*, snapshot: WorldSnapshot, simulation_version: str,
                        pipeline_version: str,
                        engine_versions: dict[str, str]) -> str:
    """M3a v6：覆盖快照全状态域（含 Tribulation 九表）。

    仅在注册 TRIBULATION 引擎的 simulation_version 下由 coordinator 使用；
    M2 路径绝不调用（M2 语义逐字节不变）。"""
    from .snapshot import _FIELDS  # 延迟导入避免循环
    doc = _build_doc(
        snapshot=snapshot, simulation_version=simulation_version,
        pipeline_version=pipeline_version, engine_versions=engine_versions,
        schema_version=WORLD_STATE_HASH_SCHEMA_VERSION,
        table_fields=dict(_FIELDS))
    return _digest(doc)


def _digest(doc: dict) -> str:
    canonical = json.dumps(doc, sort_keys=True, ensure_ascii=False,
                           separators=(",", ":"), default=_json_default)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _json_default(value):
    if isinstance(value, (list, tuple)):
        return list(value)
    if isinstance(value, dict):
        return dict(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)
