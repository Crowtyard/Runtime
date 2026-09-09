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
from .state_hash import (world_state_hash_v2, world_state_hash_v3,
                         world_state_hash_v4, world_state_hash_v5,
                         world_state_hash_v6)

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
                 pipeline_version: str = PREFLIGHT_PIPELINE_VERSION,
                 tribulation_engine=None, tribulation_adapters=None,
                 history_builder=None):
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
        # M3a：可选 TRIBULATION 槽位（仅 0.3.x simulation_version 下构造；
        # M2 调用方不传 → 行为与 M2 frozen 逐字节一致）
        self.tribulation_engine = tribulation_engine
        self.tribulation_adapters = tribulation_adapters or {}
        if tribulation_engine is not None:
            self.engine_versions[tribulation_engine.engine_id] = \
                tribulation_engine.engine_version
        # M3b：可选历史索引（纯索引层；不传 → 行为与 M2/M3a 逐字节一致）
        self.history_builder = history_builder

    def run_step(self, session: Session, *, world_id: str,
                 blessed_start_tick: int, blessed_end_tick: int,
                 real_interval_start_us: int, real_interval_end_us: int,
                 step_index: int = 0,
                 crash_after: str | None = None,
                 simulation_run_id: str | None = None) -> StepReport:
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
        # M3b 历史索引：per-engine 事件/变更切片（确定性顺序继承）
        engine_event_slices: list[tuple[str, int, int]] = []
        engine_change_slices: list[tuple[str, int, int]] = []

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
                snapshot=snapshot, staged=staged, rng=rng,
                modifiers={}, crash_after=crash_after)
            result: EngineResult = engine.simulate(ctx)
            _validate_result(engine.engine_id, result)
            ev_start = len(all_events)
            ch_start = len(staged.changes)
            for change in result.proposed_changes:
                if change.new_row is not None:
                    # INSERT 语义（M2d 扩展；所有权在 propose_insert 内强制）
                    staged.propose_insert(engine_id=engine.engine_id,
                                          table=change.table,
                                          row=change.new_row)
                    continue
                # 所有权在 StagedWorld.propose 内强制
                staged.propose(engine_id=engine.engine_id,
                               table=change.table,
                               entity_id=change.entity_id,
                               field=change.field,
                               new_value=change.new_value)
            all_events.extend(result.domain_events)
            engine_event_slices.append(
                (engine.engine_id, ev_start, len(all_events)))
            engine_change_slices.append(
                (engine.engine_id, ch_start, len(staged.changes)))
            step_metrics[engine.engine_id] = dict(result.metrics)
            warnings.extend(result.warnings)

        # ---- M3a：TRIBULATION 引擎 + Domain Impact Adapters（方案 B）----
        adapter_results = []
        tribulation_plan_for_step = None
        if self.tribulation_engine is not None:
            if crash_after == "engine:TRIBULATION":
                raise RuntimeError("crash: engine:TRIBULATION")
            trng = rng_service.stream(
                subsystem=self.tribulation_engine.engine_id,
                blessed_period_tick=blessed_start_tick)
            tctx = SimulationContext(
                world_id=world_id,
                simulation_version=self.simulation_version,
                pipeline_version=self.pipeline_version,
                step_index=step_index,
                blessed_start_tick=blessed_start_tick,
                blessed_end_tick=blessed_end_tick,
                real_interval_start_us=real_interval_start_us,
                real_interval_end_us=real_interval_end_us,
                snapshot=snapshot, staged=staged, rng=trng,
                modifiers={}, crash_after=crash_after)
            tresult: EngineResult = self.tribulation_engine.simulate(tctx)
            _validate_result(self.tribulation_engine.engine_id, tresult)
            ev_start = len(all_events)
            ch_start = len(staged.changes)
            for change in tresult.proposed_changes:
                if change.new_row is not None:
                    staged.propose_insert(
                        engine_id=self.tribulation_engine.engine_id,
                        table=change.table, row=change.new_row)
                    continue
                staged.propose(engine_id=self.tribulation_engine.engine_id,
                               table=change.table,
                               entity_id=change.entity_id,
                               field=change.field,
                               new_value=change.new_value)
            all_events.extend(tresult.domain_events)
            engine_event_slices.append(
                (self.tribulation_engine.engine_id, ev_start,
                 len(all_events)))
            engine_change_slices.append(
                (self.tribulation_engine.engine_id, ch_start,
                 len(staged.changes)))
            step_metrics[self.tribulation_engine.engine_id] = dict(
                tresult.metrics)
            if tresult.tribulation_plan is not None:
                plan = tresult.tribulation_plan
                tribulation_plan_for_step = plan
                for domain, adapter in sorted(self.tribulation_adapters.items()):
                    if crash_after == f"adapter:{domain}":
                        raise RuntimeError(f"crash: adapter:{domain}")
                    res = adapter.apply(session, plan)
                    adapter_results.append(res)
                    all_events.extend(res.domain_events)
                all_events.append(DomainEventDraft(
                    engine_id=self.tribulation_engine.engine_id,
                    event_type="TRIBULATION_IMPACT_APPLIED",
                    cause={"episode_id": plan["episode_id"],
                           "plan_id": plan["plan_id"]},
                    effect={"domains": sorted(self.tribulation_adapters)}))
                engine_event_slices[-1] = (
                    self.tribulation_engine.engine_id, ev_start,
                    len(all_events))
        if crash_after == "after_tribulation":
            raise RuntimeError("crash: after_tribulation")

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

        # ---- M3a：adapter state changes + 最小因果链接（event_ref 回填）----
        impact_uid: str | None = None
        sc_ids: dict = {}
        if adapter_results:
            from ...database.base import utcnow as _utcnow
            from ...database.models_core import WorldStateChange
            from ...database.models_world import TribulationCausalLink
            impact_uid = next((e["event_uid"] for e in emitted
                               if e["event_type"]
                               == "TRIBULATION_IMPACT_APPLIED"), None)
            affected: dict = {}
            for res in adapter_results:
                for (etype, eid, field, old, new) in res.state_changes:
                    sc = WorldStateChange(
                        world_id=world_id, entity_type=etype,
                        entity_id=str(eid), field=field,
                        old_value={"v": old}, new_value={"v": new},
                        event_ref=impact_uid, blessed_tick=blessed_end_tick,
                        real_time=_utcnow())
                    session.add(sc)
                    session.flush()
                    sc_ids[f"{etype}:{eid}:{field}"] = sc.id
                affected[res.domain] = list(res.affected_entity_ids)
            plan = tribulation_plan_for_step
            if plan is not None:
                session.add(TribulationCausalLink(
                    world_id=world_id,
                    episode_id=plan["episode_id"],
                    correlation_id=plan["plan_id"],
                    cause_event_ids={"scheduled": [
                        e["event_uid"] for e in emitted
                        if e["event_type"] == "TRIBULATION_SCHEDULED"]},
                    trigger_event_id=impact_uid,
                    decision_event_ids={"events": [
                        e["event_uid"] for e in emitted
                        if e["event_type"] in ("OWNER_DECISION_COMMITTED",
                                               "AUTONOMOUS_RESPONSE_SELECTED")]},
                    impact_plan_id=plan["plan_id"],
                    result_event_ids={"events": [
                        e["event_uid"] for e in emitted
                        if e["event_type"].endswith("_IMPACT_APPLIED")]},
                    affected_entity_ids=affected,
                    state_change_ids=sc_ids))

        # ---- M3b：历史索引（纯索引层；与事件/状态同一 fenced 事务）----
        if self.history_builder is not None:
            bundle = _history_bundle_kwargs(
                session, world_id=world_id,
                blessed_start_tick=blessed_start_tick,
                blessed_end_tick=blessed_end_tick,
                step_index=step_index,
                simulation_run_id=simulation_run_id,
                snapshot=snapshot, staged=staged,
                all_events=all_events, emitted=emitted,
                engine_event_slices=engine_event_slices,
                engine_change_slices=engine_change_slices,
                adapter_results=adapter_results,
                impact_uid=impact_uid,
                plan=tribulation_plan_for_step)
            self.history_builder.build_step(session, bundle)

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
        # 哈希 schema 版本由管线状态域决定（不静默改语义）：
        #   - 注册 TRIBULATION → v6（覆盖灾劫状态域；仅 0.3.x）
        #   - 含 SOCIAL → v5（M2d 冻结语义，基线逐字节复现）
        #   - 含 ECOLOGY → v4（M2c 冻结语义）
        #   - 含 RESOURCE/ECONOMY → v3（M2b 冻结语义）
        #   - 仅 DEMOGRAPHY（M2a 回归）→ v2（M2a 冻结语义）
        if self.tribulation_engine is not None:
            state_hash = world_state_hash_v6(
                snapshot=final_snapshot,
                simulation_version=self.simulation_version,
                pipeline_version=self.pipeline_version,
                engine_versions=self.engine_versions)
        elif "SOCIAL" in self.engine_versions:
            state_hash = world_state_hash_v5(
                snapshot=final_snapshot,
                simulation_version=self.simulation_version,
                pipeline_version=self.pipeline_version,
                engine_versions=self.engine_versions)
        elif "ECOLOGY" in self.engine_versions:
            state_hash = world_state_hash_v4(
                snapshot=final_snapshot,
                simulation_version=self.simulation_version,
                pipeline_version=self.pipeline_version,
                engine_versions=self.engine_versions)
        elif {"RESOURCE", "ECONOMY"} & set(self.engine_versions):
            state_hash = world_state_hash_v3(
                snapshot=final_snapshot,
                simulation_version=self.simulation_version,
                pipeline_version=self.pipeline_version,
                engine_versions=self.engine_versions)
        else:
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


# ---------------------------------------------------------------- M3b 历史
def _history_bundle_kwargs(session, *, world_id, blessed_start_tick,
                           blessed_end_tick, step_index, simulation_run_id,
                           snapshot, staged, all_events, emitted,
                           engine_event_slices, engine_change_slices,
                           adapter_results, impact_uid, plan):
    """由协调器内部组装 StepHistoryBundle（保持 imports 惰性）。"""
    from ..history.builder import StepHistoryBundle
    from ...database.models_world import (TribulationResidualChange,
                                          ResourceSuccessionCandidate)
    engine_events = []
    for eid, s, e in engine_event_slices:
        evs = tuple({
            "event_uid": emitted[i]["event_uid"],
            "event_type": emitted[i]["event_type"],
            "cause": dict(emitted[i]["cause"]),
            "effect": dict(emitted[i]["effect"]),
        } for i in range(s, e))
        engine_events.append((eid, evs))
    engine_changes = tuple((eid, tuple(staged.changes[s:e]))
                           for eid, s, e in engine_change_slices)
    adapter_changes = []
    for res in adapter_results:
        for (etype, eid, field, old, new) in res.state_changes:
            adapter_changes.append({
                "domain": res.domain, "entity_type": etype,
                "entity_id": str(eid), "field": field, "old": old,
                "new": new})

    eps_touched: set[str] = set()
    plans_created: list[dict] = []
    decisions_created: list[dict] = []
    recovery_created: list[dict] = []
    residual_refs: list[tuple[str, str]] = []  # (episode_id, change_kind)
    succession_created: list[dict] = []
    snap_eps = {r["id"]: r.get("episode_id") for r in snapshot.tables.get(
        "tribulation_episodes", ())}
    for eid, chs in engine_changes:
        for ch in chs:
            if ch.new_row is not None:
                nr = dict(ch.new_row)
                if ch.table == "tribulation_episodes":
                    eps_touched.add(nr["episode_id"])
                elif ch.table == "tribulation_impact_plans":
                    plans_created.append(nr)
                elif ch.table == "tribulation_decisions":
                    decisions_created.append(nr)
                elif ch.table == "tribulation_recovery_states":
                    recovery_created.append({
                        "episode_id": nr["episode_id"],
                        "started_tick": nr.get("started_tick")})
                elif ch.table == "tribulation_residual_changes":
                    residual_refs.append((nr["episode_id"],
                                          nr.get("change_kind")))
                elif ch.table == "resource_succession_candidates":
                    succession_created.append({
                        "candidate_id": nr["candidate_id"],
                        "episode_id": nr["episode_id"]})
            elif ch.table == "tribulation_episodes" \
                    and ch.entity_id in snap_eps:
                eps_touched.add(snap_eps[ch.entity_id])
    if plan is not None:
        eps_touched.add(plan["episode_id"])
    # 残留行 id：INSERT 后 flush 查询（id 仅此处需要）
    residual_created: list[dict] = []
    if residual_refs:
        session.flush()
        snap_residual_ids = {r["id"] for r in snapshot.tables.get(
            "tribulation_residual_changes", ())}
        from sqlalchemy import select as _select
        rows = session.execute(_select(TribulationResidualChange).where(
            TribulationResidualChange.world_id == world_id)).scalars().all()
        for r in rows:
            if r.id not in snap_residual_ids \
                    and (r.episode_id, r.change_kind) in residual_refs:
                residual_created.append({"id": r.id,
                                         "episode_id": r.episode_id})
    return StepHistoryBundle(
        world_id=world_id, simulation_run_id=simulation_run_id,
        blessed_start_tick=blessed_start_tick,
        blessed_end_tick=blessed_end_tick, step_index=step_index,
        snapshot=snapshot,
        engine_events=tuple(engine_events),
        engine_changes=engine_changes,
        adapter_changes=tuple(adapter_changes),
        impact_event_uid=impact_uid,
        impact_plan=plan,
        episodes_touched=tuple(sorted(eps_touched)),
        plans_created=tuple(plans_created),
        decisions_created=tuple(decisions_created),
        recovery_created=tuple(recovery_created),
        residual_created=tuple(residual_created),
        succession_created=tuple(succession_created))


def _apply_changes(session: Session, changes) -> None:
    """把 staged 变更写入当前 fenced 会话（ORM；不 commit）。

    - UPDATE：entity_id 行 setattr。
    - INSERT（M2d 扩展）：new_row 非 None → 创建行（确定性 id 由引擎派生）。
    """
    for change in changes:
        if change.new_row is not None:
            model = _MODEL_BY_TABLE[change.table]
            session.add(model(**change.new_row))
            continue
        model = _MODEL_BY_TABLE[change.table]
        row = session.get(model, change.entity_id)
        if row is None:
            raise IntegrityError("变更目标实体不存在",
                                 detail={"table": change.table,
                                         "id": change.entity_id})
        setattr(row, change.field, change.new_value)
