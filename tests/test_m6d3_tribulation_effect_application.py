"""M6D.3 §2 — minimal causal reproduction of the tribulation effect overwrite.

TEST-ONLY. Reproduces, in ONE step on a real (temp) world, the exact collision found
in the M6D.2 300y run (population entity 61 @ year 53; resource node @ year 13):

    PRE_STEP_VALUE          row value before the step
    OWNING_ENGINE_MUTATION  the owning engine's staged change for the same field
    TRIBULATION_EFFECT      the adapter's delta for the same row/field
    FINAL_STAGED_VALUE      what the staged-change container holds for that field
    PERSISTED_VALUE         what the DB holds after the step commits

Frozen contract (runtime_design/M3A_TRIBULATION_ENGINE.md §14-§20): the tribulation
impact is a DELTA on the domain-owned state and the pipeline runs TRIBULATION after
the domain engines, so the authoritative result must be

    PERSISTED_VALUE = OWNING_ENGINE_MUTATION + TRIBULATION_EFFECT

The same repair must apply each effect EXACTLY ONCE (no dropped, no double apply).
"""
from __future__ import annotations

import pathlib

import pytest
from sqlalchemy import select

from tests import m6c1d_runner as R
from XiaoguangBlessedLandRuntime.database.models_world import (
    PopulationGroup, ResourceNode)
from XiaoguangBlessedLandRuntime.services.simulation.contracts import (
    EngineResult, StateChange)
from XiaoguangBlessedLandRuntime.services.simulation.coordinator import (
    SimulationCoordinator)
from XiaoguangBlessedLandRuntime.services.simulation.tribulation_adapters import (
    DemographyTribulationAdapter, ResourceTribulationAdapter)

WORLD_ID = "M6D3-REPRO-001"
EPOCH0_US = R.EPOCH0_US
TICK = 1_000_000


class _StagedCountEngine:
    """Owning engine stub: stages one count change for one population row."""
    engine_id = "DEMOGRAPHY"
    engine_version = "m6d3-stub"

    def __init__(self, row_id: int, new_value: int):
        self._row_id = row_id
        self._new_value = new_value

    def simulate(self, ctx) -> EngineResult:
        return EngineResult(
            engine_id=self.engine_id, engine_version=self.engine_version,
            proposed_changes=[StateChange(table="population_groups",
                                          entity_id=self._row_id, field="count",
                                          old_value=None,
                                          new_value=self._new_value)],
            metrics={"births": 0, "deaths": 0})


class _StagedReserveEngine:
    """Owning engine stub: stages one remaining_reserve change for one node."""
    engine_id = "RESOURCE"
    engine_version = "m6d3-stub"

    def __init__(self, row_id: int, new_value: int):
        self._row_id = row_id
        self._new_value = new_value

    def simulate(self, ctx) -> EngineResult:
        return EngineResult(
            engine_id=self.engine_id, engine_version=self.engine_version,
            proposed_changes=[StateChange(table="resource_nodes",
                                          entity_id=self._row_id,
                                          field="remaining_reserve",
                                          old_value=None,
                                          new_value=self._new_value)],
            metrics={})


class _PlanEngine:
    """Tribulation engine stub: returns one impact plan for the current step."""
    engine_id = "TRIBULATION"
    engine_version = "m6d3-stub"

    def __init__(self, plan: dict):
        self._plan = plan

    def simulate(self, ctx) -> EngineResult:
        return EngineResult(engine_id=self.engine_id,
                            engine_version=self.engine_version,
                            tribulation_plan=self._plan, metrics={})


def _world(workdir: pathlib.Path) -> dict:
    return R.build_world(workdir, tag="m6d3repro", via="direct",
                         world_id=WORLD_ID)


def _step(factory, engines, adapters, plan) -> None:
    coordinator = SimulationCoordinator(
        engines, simulation_version=R.SIMULATION_VERSION,
        tribulation_engine=_PlanEngine(plan), tribulation_adapters=adapters)
    with factory() as session:
        coordinator.run_step(session, world_id=WORLD_ID, blessed_start_tick=0,
                             blessed_end_tick=TICK,
                             real_interval_start_us=EPOCH0_US,
                             real_interval_end_us=EPOCH0_US + 86_400_000)
        session.commit()


def test_repro_population_collision(tmp_path):
    """population_groups.count collision (M6D.2 evidence: entity 61 @ year 53)."""
    env = _world(tmp_path / "pop")
    factory = env["factory"]
    with factory() as s:
        row = s.execute(select(PopulationGroup).where(
            PopulationGroup.settlement_ref == "MAIN-01").order_by(
            PopulationGroup.id)).scalars().first()
        row_id, pre_value, settlement = row.id, int(row.count), row.settlement_ref

    loss = 2
    plan = {"world_id": WORLD_ID, "episode_id": "EP-M6D3",
            "plan_id": "PLAN-M6D3", "intensity": 100,
            "population_risk_num": loss, "population_risk_den": pre_value,
            "affected_settlements": {"selected": [settlement]}}
    engine_value = pre_value - 1
    _step(factory, [_StagedCountEngine(row_id, engine_value)],
          {"DEMOGRAPHY": DemographyTribulationAdapter()}, plan)

    with factory() as s:
        persisted = int(s.get(PopulationGroup, row_id).count)
    record = {"PRE_STEP_VALUE": pre_value,
              "OWNING_ENGINE_MUTATION": engine_value,
              "TRIBULATION_EFFECT": f"-{loss}",
              "FINAL_STAGED_VALUE": engine_value,
              "PERSISTED_VALUE": persisted,
              "EXPECTED": engine_value - loss}
    print("M6D3_REPRO_POPULATION", record)
    assert persisted == engine_value - loss, record


def test_repro_resource_collision(tmp_path):
    """resource_nodes.remaining_reserve collision (M6D.2 evidence: node 1 @ y13)."""
    env = _world(tmp_path / "res")
    factory = env["factory"]
    with factory() as s:
        node = s.execute(select(ResourceNode).where(
            ResourceNode.remaining_reserve > 0).order_by(
            ResourceNode.id)).scalars().first()
        row_id, pre_value = node.id, int(node.remaining_reserve)

    loss = max(pre_value // 1000, 1)
    plan = {"world_id": WORLD_ID, "episode_id": "EP-M6D3",
            "plan_id": "PLAN-M6D3", "intensity": 100,
            "resource_damage_num": 1, "resource_damage_den": 1000,
            "affected_settlements": {"selected": ["MAIN-01"]}}
    engine_value = pre_value - 7
    _step(factory, [_StagedReserveEngine(row_id, engine_value)],
          {"RESOURCE": ResourceTribulationAdapter()}, plan)

    with factory() as s:
        persisted = int(s.get(ResourceNode, row_id).remaining_reserve)
    record = {"PRE_STEP_VALUE": pre_value,
              "OWNING_ENGINE_MUTATION": engine_value,
              "TRIBULATION_EFFECT": f"-{loss}",
              "FINAL_STAGED_VALUE": engine_value,
              "PERSISTED_VALUE": persisted,
              "EXPECTED": engine_value - loss}
    print("M6D3_REPRO_RESOURCE", record)
    assert persisted == engine_value - loss, record


def test_repro_no_double_apply_without_owning_change(tmp_path):
    """No engine change for the row → the effect must still land exactly once."""
    env = _world(tmp_path / "solo")
    factory = env["factory"]
    with factory() as s:
        row = s.execute(select(PopulationGroup).where(
            PopulationGroup.settlement_ref == "SAT-01").order_by(
            PopulationGroup.id)).scalars().first()
        row_id, pre_value, settlement = row.id, int(row.count), row.settlement_ref

    loss = 3
    plan = {"world_id": WORLD_ID, "episode_id": "EP-M6D3",
            "plan_id": "PLAN-M6D3", "intensity": 100,
            "population_risk_num": loss, "population_risk_den": pre_value,
            "affected_settlements": {"selected": [settlement]}}
    _step(factory, [], {"DEMOGRAPHY": DemographyTribulationAdapter()}, plan)
    with factory() as s:
        persisted = int(s.get(PopulationGroup, row_id).count)
    record = {"PRE_STEP_VALUE": pre_value, "TRIBULATION_EFFECT": f"-{loss}",
              "PERSISTED_VALUE": persisted, "EXPECTED": pre_value - loss}
    print("M6D3_REPRO_SOLO", record)
    assert persisted == pre_value - loss, record
