# -*- coding: utf-8 -*-
"""WorldSnapshot / StagedWorld（M2 Preflight 冻结）。

- WorldSnapshot：step 开始时从权威 DB 一次性读取（不可变）。
- StagedWorld：start snapshot 的内存拷贝；引擎读暂存视图（Feed-Forward），
  经 propose() 声明变更；中间状态只在内存，绝不提前成为 authoritative DB。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...database.models_core import WorldRuntime
from ...database.models_world import (EcologicalRegion, EcologyFeedbackState,
                                      EcologyState, EcologyZone,
                                      EconomicPressureState, Household,
                                      Industry, Institution, Lineage,
                                      PopulationGroup, ProductionRecipe,
                                      ProductionState, ResourceNode,
                                      ResourceProfile, ResourceStock,
                                      ResourceSuccessionCandidate,
                                      Settlement, SettlementSocialState,
                                      SocialFeedbackState,
                                      TribulationCausalLink,
                                      TribulationDecision,
                                      TribulationEpisode,
                                      TribulationImpactPlan,
                                      TribulationProfile,
                                      TribulationRecoveryState,
                                      TribulationResidualChange,
                                      TribulationSchedule)
from ...domain.errors import IntegrityError
from .contracts import ENGINE_OWNERSHIP, StateChange

SNAPSHOT_TABLES = (
    "settlements", "population_groups", "resource_nodes", "industries",
    "ecological_regions", "lineages", "institutions",
    # M2b Resource-Economy：
    "resource_profiles", "resource_stocks", "production_recipes",
    "production_state", "economic_pressure_state",
    # M2c Ecology：
    "ecology_zones", "ecology_state", "ecology_feedback_state",
    # M2d Social：
    "households", "settlement_social_state", "social_feedback_state",
    # M3a Tribulation：
    "tribulation_profiles", "tribulation_schedules",
    "tribulation_episodes", "tribulation_decisions",
    "tribulation_impact_plans", "tribulation_recovery_states",
    "tribulation_residual_changes", "resource_succession_candidates",
    "tribulation_causal_links")

_MODEL_BY_TABLE = {
    "settlements": Settlement,
    "population_groups": PopulationGroup,
    "resource_nodes": ResourceNode,
    "industries": Industry,
    "ecological_regions": EcologicalRegion,
    "lineages": Lineage,
    "institutions": Institution,
    "resource_profiles": ResourceProfile,
    "resource_stocks": ResourceStock,
    "production_recipes": ProductionRecipe,
    "production_state": ProductionState,
    "economic_pressure_state": EconomicPressureState,
    "ecology_zones": EcologyZone,
    "ecology_state": EcologyState,
    "ecology_feedback_state": EcologyFeedbackState,
    "households": Household,
    "settlement_social_state": SettlementSocialState,
    "social_feedback_state": SocialFeedbackState,
    "tribulation_profiles": TribulationProfile,
    "tribulation_schedules": TribulationSchedule,
    "tribulation_episodes": TribulationEpisode,
    "tribulation_decisions": TribulationDecision,
    "tribulation_impact_plans": TribulationImpactPlan,
    "tribulation_recovery_states": TribulationRecoveryState,
    "tribulation_residual_changes": TribulationResidualChange,
    "resource_succession_candidates": ResourceSuccessionCandidate,
    "tribulation_causal_links": TribulationCausalLink,
}

_FIELDS = {
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
                       "updated_blessed_tick", "reserve_ceiling_minor",
                       "regeneration_carry"),
    "industries": ("id", "world_id", "kind", "node_ref", "labor",
                   "capacity", "state"),
    "ecological_regions": ("id", "world_id", "terrain", "climate", "water",
                           "danger_level", "carrying_capacity", "state"),
    "lineages": ("id", "world_id", "lineage_type", "head_person_ref",
                 "member_ids", "lineage_id", "origin_settlement",
                 "represented_population", "household_count", "generation",
                 "status", "founded_tick", "parent_lineage_ref",
                 "semantic_version", "updated_blessed_tick"),
    "institutions": ("id", "world_id", "kind", "settlement_ref",
                     "owner_ref", "state", "capacity", "institution_id",
                     "founded_tick", "profile_ref", "updated_blessed_tick"),
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
    "tribulation_profiles": ("id", "world_id", "profile_id", "tier",
                             "theme", "intensity_min", "intensity_max",
                             "precursor_steps", "preparation_steps",
                             "impact_steps", "population_risk_num",
                             "population_risk_den", "resource_damage_num",
                             "resource_damage_den", "inventory_damage_num",
                             "inventory_damage_den",
                             "production_disruption_num",
                             "production_disruption_den",
                             "social_displacement_num",
                             "social_displacement_den",
                             "institution_disruption_num",
                             "institution_disruption_den",
                             "ecology_pressure", "recovery_steps",
                             "targeting_rules", "succession_rules", "status",
                             "source_refs", "semantic_version"),
    "tribulation_schedules": ("id", "world_id", "schedule_id", "tier",
                              "period_years", "enabled", "semantic_version"),
    "tribulation_episodes": ("id", "world_id", "episode_id", "window_tier",
                             "schedule_ref", "profile_ref", "current_stage",
                             "entered_tick", "transition_tick",
                             "target_regions", "target_settlements", "status",
                             "decision_policy", "semantic_version",
                             "updated_blessed_tick"),
    "tribulation_decisions": ("id", "world_id", "decision_id", "episode_id",
                              "action", "submitted_tick",
                              "effective_before_tick", "target_priorities",
                              "resource_allocation", "status",
                              "supersedes_decision_id", "source",
                              "semantic_version"),
    "tribulation_impact_plans": ("id", "world_id", "plan_id", "episode_id",
                                 "profile_ref", "tier", "intensity",
                                 "affected_regions", "affected_settlements",
                                 "population_risk_num", "population_risk_den",
                                 "resource_damage_num", "resource_damage_den",
                                 "inventory_damage_num",
                                 "inventory_damage_den",
                                 "production_disruption_num",
                                 "production_disruption_den",
                                 "social_displacement_num",
                                 "social_displacement_den",
                                 "institution_disruption_num",
                                 "institution_disruption_den",
                                 "ecology_pressure", "mitigation_applied",
                                 "residual_changes", "recovery_requirements",
                                 "succession_candidates", "semantic_version"),
    "tribulation_recovery_states": ("id", "world_id", "episode_id",
                                    "recovery_need_num", "recovery_need_den",
                                    "progress_num", "progress_den",
                                    "resource_requirement",
                                    "population_requirement",
                                    "ecology_requirement",
                                    "social_requirement", "status",
                                    "started_tick", "semantic_version",
                                    "updated_blessed_tick"),
    "tribulation_residual_changes": ("id", "world_id", "episode_id",
                                     "change_kind", "region_ref",
                                     "settlement_ref", "payload", "persistent",
                                     "semantic_version"),
    "resource_succession_candidates": ("id", "world_id", "candidate_id",
                                       "episode_id", "region_ref",
                                       "resource_category",
                                       "environment_conditions",
                                       "maturation_requirement",
                                       "observation_progress",
                                       "stability_progress",
                                       "discovery_status",
                                       "development_status",
                                       "semantic_version"),
    "tribulation_causal_links": ("id", "world_id", "episode_id",
                                 "correlation_id", "cause_event_ids",
                                 "trigger_event_id", "decision_event_ids",
                                 "impact_plan_id", "result_event_ids",
                                 "affected_entity_ids", "state_change_ids"),
}


def _row_dict(model, fields) -> dict:
    return {f: getattr(model, f) for f in fields}


def _canonical(row: dict, table: str) -> Any:
    """语义键元组（哈希规范化排序用；见契约 §9）。"""
    if table == "population_groups":
        # age_cohort 存 bucket 序号字符串：按整数排序，避免 "10" < "2"
        try:
            bucket = int(row["age_cohort"])
        except (TypeError, ValueError):
            bucket = -1
        return (_norm(row["species"]), _norm(row["settlement_ref"]), bucket,
                _norm(row["occupation_group"]))
    key_specs = {
        "settlements": ("settlement_type", "working_name"),
        "resource_nodes": ("kind", "region_ref"),
        "industries": ("kind", "node_ref"),
        "ecological_regions": ("terrain", "climate", "water"),
        "lineages": ("lineage_type", "head_person_ref"),
        "institutions": ("kind", "settlement_ref", "owner_ref"),
        "resource_profiles": ("resource_id",),
        "resource_stocks": ("settlement_ref", "resource_profile_ref"),
        "production_recipes": ("recipe_id",),
        "production_state": ("settlement_ref", "recipe_ref"),
        "economic_pressure_state": ("settlement_ref", "resource_profile_ref"),
        "ecology_zones": ("zone_id",),
        "ecology_state": ("zone_ref",),
        "ecology_feedback_state": ("zone_ref",),
        "households": ("household_id",),
        "settlement_social_state": ("settlement_ref",),
        "social_feedback_state": ("settlement_ref",),
        "tribulation_profiles": ("profile_id",),
        "tribulation_schedules": ("schedule_id", "tier"),
        "tribulation_episodes": ("episode_id",),
        "tribulation_decisions": ("decision_id",),
        "tribulation_impact_plans": ("plan_id",),
        "tribulation_recovery_states": ("episode_id",),
        "tribulation_residual_changes": ("episode_id", "change_kind",
                                          "region_ref", "settlement_ref"),
        "resource_succession_candidates": ("candidate_id",),
        "tribulation_causal_links": ("episode_id", "correlation_id"),
    }
    return tuple(_norm(row[k]) for k in key_specs[table])


def _norm(value: Any) -> Any:
    if isinstance(value, dict):
        return tuple(sorted((k, _norm(v)) for k, v in value.items()))
    if isinstance(value, list):
        return tuple(_norm(v) for v in value)
    return value


@dataclass(frozen=True)
class WorldSnapshot:
    """start-of-step 权威快照（不可变）。"""
    world_id: str
    blessed_tick: int
    last_committed_real_us: int
    time_rate_remainder: int
    current_time_ratio_id: int | None
    tables: dict[str, tuple[dict, ...]] = field(default_factory=dict)

    def rows(self, table: str) -> tuple[dict, ...]:
        return self.tables.get(table, ())


def read_snapshot(session: Session, world_id: str) -> WorldSnapshot:
    runtime = session.execute(
        select(WorldRuntime).where(WorldRuntime.world_id == world_id)
    ).scalar_one_or_none()
    if runtime is None:
        raise IntegrityError("world_runtime 行缺失", detail=world_id)
    tables: dict[str, tuple[dict, ...]] = {}
    for table, model in _MODEL_BY_TABLE.items():
        rows = [_row_dict(m, _FIELDS[table]) for m in session.execute(
            select(model).where(model.world_id == world_id)).scalars()]
        tables[table] = tuple(sorted(rows, key=lambda r: (_canonical(r, table),
                                                          r["id"])))
    return WorldSnapshot(
        world_id=world_id,
        blessed_tick=runtime.current_blessed_tick,
        last_committed_real_us=runtime.last_committed_real_us,
        time_rate_remainder=runtime.time_rate_remainder,
        current_time_ratio_id=runtime.current_time_ratio_id,
        tables=tables)


class StagedWorld:
    """内存暂存世界（Feed-Forward）：引擎读 staged 视图、经 propose 声明变更。"""

    def __init__(self, snapshot: WorldSnapshot):
        self.snapshot = snapshot
        self._rows: dict[str, dict[int, dict]] = {
            table: {r["id"]: dict(r) for r in rows}
            for table, rows in snapshot.tables.items()}
        self.changes: list[StateChange] = []

    def rows(self, table: str) -> tuple[dict, ...]:
        return tuple(self._rows.get(table, {}).values())

    def get(self, table: str, entity_id: int) -> dict | None:
        return self._rows.get(table, {}).get(entity_id)

    def propose(self, *, engine_id: str, table: str, entity_id: int,
                field: str, new_value: Any) -> None:
        if table not in SNAPSHOT_TABLES:
            raise IntegrityError("propose 目标表不在快照契约内", detail=table)
        if table not in ENGINE_OWNERSHIP.get(engine_id, frozenset()):
            raise IntegrityError(
                f"引擎 {engine_id} 无权写表 {table}（所有权契约）",
                detail={"engine": engine_id, "table": table})
        row = self._rows[table][entity_id]
        old = row.get(field)
        if old == new_value:
            return
        row[field] = new_value
        self.changes.append(StateChange(table=table, entity_id=entity_id,
                                        field=field, old_value=old,
                                        new_value=new_value))

    def propose_insert(self, *, engine_id: str, table: str,
                       row: dict[str, Any]) -> None:
        """INSERT 语义（M2d 扩展）：声明创建一行（coordinator 统一写入）。

        - 所有权与快照契约同 propose；确定性 id 由引擎派生（无 UUID）。
        - 新行进入 changes；本步后续引擎不读取暂存新行（单向 feed-forward
          末尾引擎使用；SOCIAL 是最后一个引擎）。
        """
        if table not in SNAPSHOT_TABLES:
            raise IntegrityError("propose_insert 目标表不在快照契约内",
                                 detail=table)
        if table not in ENGINE_OWNERSHIP.get(engine_id, frozenset()):
            raise IntegrityError(
                f"引擎 {engine_id} 无权写表 {table}（所有权契约）",
                detail={"engine": engine_id, "table": table})
        self.changes.append(StateChange(
            table=table, entity_id=None, field=None, old_value=None,
            new_value=dict(row), new_row=dict(row)))
