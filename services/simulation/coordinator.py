# -*- coding: utf-8 -*-
"""Simulation Coordinator（M2 Preflight）。

一个 simulation step：
  WorldSnapshot → StagedWorld → 按 ENGINE_ORDER 逐引擎 simulate(ctx)
  → 所有权校验 → 确定性事件 identity → 统一写入（当前 fenced session）
  → M2 世界 checkpoint（world_state_hash v2）。

协调器自身不开启事务/不 commit：它运行在 M1 catch_up 的 simulate_fn 内
（WorldMutationContext 由 M1 持有），或由调用方显式提供 fenced session。
引擎零 commit / 零 LLM / 零网络 / 零 wall-clock。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from ...database.models_world import (EcologicalRegion, Industry, Institution,
                                     Lineage, PopulationGroup, ResourceNode,
                                     Settlement)
from ...domain.errors import IntegrityError
from ..repositories import CheckpointRepository, EventRepository
from ..rng_service import RngService
from .contracts import (ENGINE_ORDER, PREFLIGHT_PIPELINE_VERSION,
                        PREFLIGHT_SIMULATION_VERSION, TRIBULATION_SLOT,
                        TRIBULATION_SLOT_STATE, DomainEventDraft, Engine,
                        EngineResult, SimulationContext)
from .event_stream import (deterministic_event_uid,
                           step_event_stream_hash)
from .recovery import (WORLD_COMMITTED_KIND,
                       latest_authoritative_world_checkpoint)
from .snapshot import StagedWorld, read_snapshot
from .state_hash import world_state_hash_v2

_MODEL_BY_TABLE = {
    "settlements": Settlement,
    "population_groups": PopulationGroup,
    "resource_nodes": ResourceNode,
    "industries": Industry,
    "ecological_regions": EcologicalRegion,
    "lineages": Lineage,
    "institutions": Institution,
}


@dataclass(frozen=True)
class StepReport:
    step_index: int
    blessed_start_tick: int
    blessed_end_tick: int
    event_count: int
    change_count: int
    metrics: dict = field(default_factory=dict)
    world_state_hash: str = ""
    event_stream_hash: str = ""
    warnings: list[str] = field(default_factory=list)


class SimulationCoordinator:
    """按冻结顺序调度引擎；统一验证与写入（当前事务内，不 commit）。"""

    def __init__(self, engines: list[Engine], *,
                 simulation_version: str = PREFLIGHT_SIMULATION_VERSION,
                 pipeline_version: str = PREFLIGHT_PIPELINE_VERSION):
        self._by_id = {e.engine_id: e for e in engines}
        ordered = [self._by_id.get(eid) for eid in ENGINE_ORDER
                   if eid in self._by_id]
        if len(ordered) != len(engines):
            unknown = sorted(set(self._by_id) - set(ENGINE_ORDER))
            raise IntegrityError("引擎集合含未知引擎", detail=unknown)
        if [e.engine_id for e in ordered] != [e.engine_id for e in engines]:
            raise IntegrityError(
                "引擎列表顺序与冻结 ENGINE_ORDER 不一致",
                detail=[e.engine_id for e in engines])
        self.engines = ordered
        self.simulation_version = simulation_version
        self.pipeline_version = pipeline_version
        self.engine_versions = {e.engine_id: e.engine_version
                                for e in ordered}

    def run_step(self, session: Session, *, world_id: str,
                 blessed_start_tick: int, blessed_end_tick: int,
                 real_interval_start_us: int, real_interval_end_us: int,
                 step_index: int = 0,
                 crash_after: str | None = None) -> StepReport:
        """在一个 fenced session 内执行一步（不 commit）。

        crash_after：测试专用崩溃注入点
        before_snapshot / after_snapshot / engine:<ID> / after_engines /
        before_apply / during_apply / before_checkpoint / after_checkpoint
        """
        if TRIBULATION_SLOT_STATE != "NOT_REGISTERED":
            raise IntegrityError("TRIBULATION 槽位必须保持 NOT_REGISTERED",
                                 detail=TRIBULATION_SLOT)
        if crash_after == "before_snapshot":
            raise RuntimeError("crash: before_snapshot")

        snapshot = read_snapshot(session, world_id)
        if crash_after == "after_snapshot":
            raise RuntimeError("crash: after_snapshot")

        staged = StagedWorld(snapshot)
        rng_service = RngService(world_id=world_id,
                                 simulation_version=self.simulation_version)
        all_events: list[DomainEventDraft] = []
        step_metrics: dict = {}
        warnings: list[str] = []

        for engine in self.engines:
            if crash_after == f"engine:{engine.engine_id}":
                raise RuntimeError(f"crash: engine:{engine.engine_id}")
            rng = rng_service.stream(
                subsystem=engine.engine_id,
                blessed_period_tick=blessed_start_tick)
            ctx = SimulationContext(
                world_id=world_id,
                simulation_version=self.simulation_version,
                pipeline_version=self.pipeline_version,
                step_index=step_index,
                blessed_start_tick=blessed_start_tick,
                blessed_end_tick=blessed_end_tick,
                real_interval_start_us=real_interval_start_us,
                real_interval_end_us=real_interval_end_us,
                snapshot=snapshot, staged=staged, rng=rng)
            result: EngineResult = engine.simulate(ctx)
            _validate_result(engine.engine_id, result)
            for change in result.proposed_changes:
                # 所有权在 StagedWorld.propose 内强制
                staged.propose(engine_id=engine.engine_id,
                               table=change.table,
                               entity_id=change.entity_id,
                               field=change.field,
                               new_value=change.new_value)
            all_events.extend(result.domain_events)
            step_metrics[engine.engine_id] = dict(result.metrics)
            warnings.extend(result.warnings)

        if crash_after == "after_engines":
            raise RuntimeError("crash: after_engines")
        if crash_after == "before_apply":
            raise RuntimeError("crash: before_apply")

        _apply_changes(session, staged.changes)
        if crash_after == "during_apply":
            raise RuntimeError("crash: during_apply")

        event_repo = EventRepository(session)
        event_count = 0
        emitted: list[dict] = []
        for seq, draft in enumerate(all_events):
            uid = deterministic_event_uid(
                world_id=world_id,
                simulation_version=self.simulation_version,
                real_start_us=real_interval_start_us,
                real_end_us=real_interval_end_us,
                engine_id=draft.engine_id,
                event_type=draft.event_type, seq=seq)
            event_repo.append(
                world_id=world_id,
                event_type=draft.event_type,
                source="SIMULATION",
                blessed_tick=blessed_end_tick,
                severity=draft.severity,
                scope=draft.scope,
                cause=dict(draft.cause),
                effect=dict(draft.effect),
                event_uid=uid)
            emitted.append({
                "event_uid": uid,
                "blessed_tick": blessed_end_tick,
                "event_type": draft.event_type,
                "source": "SIMULATION",
                "cause": dict(draft.cause),
                "effect": dict(draft.effect),
                "severity": draft.severity,
                "scope": draft.scope,
            })
            event_count += 1

        if crash_after == "before_checkpoint":
            raise RuntimeError("crash: before_checkpoint")

        # Event Stream Hash（增量链；与 world_state_hash 语义分离）
        prev_checkpoint = latest_authoritative_world_checkpoint(
            session, world_id)
        prev_stream_hash = (prev_checkpoint.meta.get("event_stream_hash")
                            if prev_checkpoint is not None else None)
        stream_hash = step_event_stream_hash(
            prev_stream_hash, world_id=world_id,
            simulation_version=self.simulation_version, events=emitted)

        final_snapshot = read_snapshot(session, world_id)
        state_hash = world_state_hash_v2(
            snapshot=final_snapshot,
            simulation_version=self.simulation_version,
            pipeline_version=self.pipeline_version,
            engine_versions=self.engine_versions)
        CheckpointRepository(session).create(
            world_id=world_id,
            blessed_tick=blessed_end_tick,
            world_state_hash=state_hash,
            complete=True,
            meta={"kind": "M2_PREFLIGHT",
                  "checkpoint_kind": WORLD_COMMITTED_KIND,
                  "phase": "COMMITTED",
                  "event_stream_hash": stream_hash,
                  "prev_event_stream_hash": prev_stream_hash,
                  "pipeline_version": self.pipeline_version,
                  "engine_versions": self.engine_versions,
                  "simulation_version": self.simulation_version,
                  "step_index": step_index,
                  "step_metrics": step_metrics,
                  "real_interval_start_us": real_interval_start_us,
                  "real_interval_end_us": real_interval_end_us},
            last_committed_real_us=real_interval_end_us,
            simulation_version=self.simulation_version)

        if crash_after == "after_checkpoint":
            raise RuntimeError("crash: after_checkpoint")

        return StepReport(
            step_index=step_index,
            blessed_start_tick=blessed_start_tick,
            blessed_end_tick=blessed_end_tick,
            event_count=event_count,
            change_count=len(staged.changes),
            metrics=step_metrics,
            world_state_hash=state_hash,
            event_stream_hash=stream_hash,
            warnings=warnings)


def _validate_result(engine_id: str, result: EngineResult) -> None:
    if result.engine_id != engine_id:
        raise IntegrityError("EngineResult.engine_id 与引擎不符",
                             detail={"expect": engine_id,
                                     "got": result.engine_id})


def _apply_changes(session: Session, changes) -> None:
    """把 staged 变更写入当前 fenced 会话（ORM UPDATE；不 commit）。"""
    for change in changes:
        model = _MODEL_BY_TABLE[change.table]
        row = session.get(model, change.entity_id)
        if row is None:
            raise IntegrityError("变更目标实体不存在",
                                 detail={"table": change.table,
                                         "id": change.entity_id})
        setattr(row, change.field, change.new_value)
