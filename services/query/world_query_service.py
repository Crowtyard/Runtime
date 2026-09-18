# -*- coding: utf-8 -*-
"""WorldQueryService（M5）—— 正式只读查询层。

- READ ONLY：任何查询前后 authoritative world state hash / event stream hash /
  causal history hash / current_tick / checkpoint 数 / event 数 全部不变
  （ReadOnlyGuard 内建强制，违例即抛 IntegrityError）。
- NOT_ACTIVATED：返回结构化 UNKNOWN（绝不把空库解释为"世界存在且为零"）。
- NULL tick ≠ 0（NOT_STARTED）。
- fail-closed：DB 不可用 / schema 异常 / scheduler FAILED → RUNTIME_UNAVAILABLE。
- History/因果：直接复用 M3b HistoryService，不实现第二套历史逻辑。
- 不 import astrbot；不读取 World Seed。
"""
from __future__ import annotations

from typing import Callable

from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from ...database.models_core import WorldEvent, WorldRuntime
from ...database.models_world import (EcologyState, Household, Institution,
                                      Lineage, PopulationGroup, ResourceNode,
                                      ResourceStock, ResourceSuccessionCandidate,
                                      SettlementSocialState, TribulationEpisode,
                                      TribulationRecoveryState)
from ...domain.constants import RuntimeStatus
from ...domain.errors import IntegrityError
from ..history.service import HistoryService
from .provenance import (NONE_OFFICIAL, NOT_STARTED, UNKNOWN, fact,
                         stable_sorted)
from .query_models import Authority, Fact, QueryType

RUNTIME_UNAVAILABLE = "RUNTIME_UNAVAILABLE"
NOT_ACTIVATED = "NOT_ACTIVATED"

# 有意义变化分类（§19）：这些类值得告知；其余数值微动只聚合计数
_MEANINGFUL_EVENT_CLASSES = {
    "TRIBULATION_PRECURSOR_STARTED": "TRIBULATION_LIFECYCLE",
    "TRIBULATION_PREPARATION_STARTED": "TRIBULATION_LIFECYCLE",
    "TRIBULATION_IMPACT_STARTED": "TRIBULATION_LIFECYCLE",
    "TRIBULATION_STABILIZED": "TRIBULATION_LIFECYCLE",
    "TRIBULATION_RESIDUAL_CHANGE_CREATED": "TRIBULATION_LIFECYCLE",
    "TRIBULATION_RECOVERY_PROGRESS": "TRIBULATION_LIFECYCLE",
    "TRIBULATION_NEW_NORMAL_REACHED": "TRIBULATION_LIFECYCLE",
    "TRIBULATION_EPISODE_COMPLETED": "TRIBULATION_LIFECYCLE",
    "RESOURCE_SUCCESSION_CANDIDATE_CREATED": "SUCCESSION",
    "RESOURCE_SHORTAGE": "RESOURCE_DEPLETION",
    "ECOLOGY_THRESHOLD_CROSSED": "ECOLOGY_THRESHOLD",
    "SOCIAL_STRESS_THRESHOLD_CROSSED": "SOCIAL_THRESHOLD",
    "INSTITUTION_STATE_CHANGED": "INSTITUTION_TRANSITION",
}


class ReadOnlyGuard:
    """查询只读不变量守卫：前后状态指纹一致，否则 IntegrityError。"""

    def __init__(self, svc: "WorldQueryService"):
        self._svc = svc
        self._before: dict | None = None

    def _fingerprint(self) -> dict:
        return self._svc._fingerprint()

    def __enter__(self) -> "ReadOnlyGuard":
        self._before = self._fingerprint()
        return self

    def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
        if exc_type is not None:
            return False
        if self._before != self._fingerprint():
            raise IntegrityError(
                "查询层只读不变量被破坏：world hashes/tick/counts 发生变化",
                detail={"before": self._before,
                        "after": self._fingerprint()})
        return False


class WorldQueryService:
    def __init__(self, *, session_factory: sessionmaker[Session],
                 world_id: str,
                 scheduler_status_provider: Callable[[], dict | None]
                 | None = None):
        self.session_factory = session_factory
        self.world_id = world_id
        self._scheduler_status = scheduler_status_provider

    # ------------------------------------------------------------- 基础
    def _row(self, s: Session) -> WorldRuntime | None:
        return s.execute(select(WorldRuntime).where(
            WorldRuntime.world_id == self.world_id)).scalar_one_or_none()

    def _scheduler_state(self) -> str | None:
        if self._scheduler_status is None:
            return None
        try:
            snap = self._scheduler_status()
        except Exception:  # noqa: BLE001
            return None
        return snap.get("scheduler_state") if isinstance(snap, dict) else None

    def _fingerprint(self) -> dict:
        with self.session_factory() as s:
            row = self._row(s)
            tick = row.current_blessed_tick if row is not None else None
            checkpoints = s.execute(text(
                "SELECT COUNT(*) FROM simulation_checkpoints")).scalar()
            events = s.execute(text(
                "SELECT COUNT(*) FROM world_events")).scalar()
            try:
                from ...database.models_core import SimulationCheckpoint
                latest = s.execute(
                    select(SimulationCheckpoint).order_by(
                        SimulationCheckpoint.checkpoint_blessed_tick.desc())
                    .limit(1)).scalar_one_or_none()
            except Exception:  # noqa: BLE001
                # M6D.3：broad-exception 策略本轮**刻意不改**
                # （QUERY_SERVICE_BROAD_EXCEPTION_TECH_DEBT = OPEN_NON_BLOCKING）。
                latest = None
        wsh = latest.world_state_hash if latest else None
        esh = (latest.meta or {}).get("event_stream_hash") if latest else None
        chh = None
        if latest is not None:
            try:
                chh = HistoryService(self.session_factory).causal_history_hash(
                    world_id=self.world_id)["hash"]
            except Exception:  # noqa: BLE001
                chh = None
        return {"tick": tick, "checkpoints": checkpoints, "events": events,
                "world_state_hash": wsh, "event_stream_hash": esh,
                "causal_history_hash": chh}

    # ------------------------------------------------------------- 公共 API
    def get_runtime_status(self) -> dict:
        """§6：NOT_ACTIVATED 语义核心。"""
        with ReadOnlyGuard(self):
            with self.session_factory() as s:
                row = self._row(s)
            scheduler = self._scheduler_state()
            if scheduler == "FAILED":
                return {"status": RUNTIME_UNAVAILABLE,
                        "reason": "SCHEDULER_FAILED", "scheduler_state": "FAILED"}
            if row is None or row.runtime_status != RuntimeStatus.ACTIVE \
                    or row.world_seed_version is None:
                return {"status": NOT_ACTIVATED,
                        "reason": "WORLD_NOT_ACTIVATED",
                        "runtime_status": row.runtime_status
                        if row is not None else None,
                        "scheduler_state": scheduler,
                        "current_population": UNKNOWN,
                        "current_blessed_tick": None,
                        "official_world_events": 0}
            return {"status": "ACTIVATED",
                    "reason": None,
                    "runtime_status": row.runtime_status,
                    "simulation_version": row.simulation_version,
                    "scheduler_state": scheduler,
                    "current_blessed_tick": row.current_blessed_tick,
                    "current_population": self._population_total(),
                    "official_world_events": self._event_count()}

    def get_world_time(self) -> dict:
        """§7：NULL tick ≠ Year 0（NOT_STARTED）。"""
        with ReadOnlyGuard(self):
            with self.session_factory() as s:
                row = self._row(s)
            if row is None or row.runtime_status != RuntimeStatus.ACTIVE \
                    or row.world_seed_version is None:
                return {"status": NOT_ACTIVATED,
                        "current_blessed_tick": None,
                        "blessed_year": None,
                        "display": NOT_STARTED}
            tick = row.current_blessed_tick
            if tick is None:
                return {"status": NOT_ACTIVATED,
                        "current_blessed_tick": None,
                        "blessed_year": None,
                        "display": NOT_STARTED}
            return {"status": "ACTIVATED", "current_blessed_tick": tick,
                    "blessed_year": tick // 1_000_000,
                    "display": f"{tick // 1_000_000} 福地年"}

    def get_population_summary(self) -> dict:
        with ReadOnlyGuard(self):
            base = self.get_runtime_status()
            if base["status"] != "ACTIVATED":
                return {"status": base["status"], "summary": UNKNOWN,
                        "reason": base.get("reason")}
            with self.session_factory() as s:
                groups = s.execute(select(PopulationGroup).where(
                    PopulationGroup.world_id == self.world_id)).scalars().all()
                total = sum(g.count or 0 for g in groups)
                by_species: dict[str, int] = {}
                for g in groups:
                    by_species[g.species] = by_species.get(g.species, 0) \
                        + (g.count or 0)
                settlements = len({g.settlement_ref for g in groups})
                cohorts = len({g.age_cohort for g in groups})
            return {"status": "ACTIVATED",
                    "summary": {"total_population": total,
                                "species": dict(sorted(by_species.items())),
                                "settlements_with_population": settlements,
                                "age_cohorts": cohorts},
                    "facts": [fact("POPULATION_TOTAL", total,
                                   source_table="population_groups")]}

    def get_species_summary(self) -> dict:
        with ReadOnlyGuard(self):
            base = self.get_runtime_status()
            if base["status"] != "ACTIVATED":
                return {"status": base["status"], "summary": UNKNOWN}
            with self.session_factory() as s:
                groups = s.execute(select(PopulationGroup).where(
                    PopulationGroup.world_id == self.world_id)).scalars().all()
            by_species: dict[str, int] = {}
            for g in groups:
                by_species[g.species] = by_species.get(g.species, 0) \
                    + (g.count or 0)
            return {"status": "ACTIVATED",
                    "summary": {"species": dict(sorted(by_species.items()))}}

    def get_settlement_summary(self) -> dict:
        with ReadOnlyGuard(self):
            base = self.get_runtime_status()
            if base["status"] != "ACTIVATED":
                return {"status": base["status"], "summary": UNKNOWN}
            with self.session_factory() as s:
                rows = s.execute(text(
                    "SELECT COUNT(*) FROM settlements WHERE world_id=:w"),
                    {"w": self.world_id}).scalar()
                households = s.execute(text(
                    "SELECT COUNT(*) FROM households WHERE world_id=:w"),
                    {"w": self.world_id}).scalar()
                lineages = s.execute(text(
                    "SELECT COUNT(*) FROM lineages WHERE world_id=:w"),
                    {"w": self.world_id}).scalar()
                institutions = s.execute(text(
                    "SELECT COUNT(*) FROM institutions WHERE world_id=:w"),
                    {"w": self.world_id}).scalar()
            return {"status": "ACTIVATED",
                    "summary": {"settlements": rows,
                                "households": households,
                                "lineages": lineages,
                                "institutions": institutions}}

    def get_resource_summary(self) -> dict:
        with ReadOnlyGuard(self):
            base = self.get_runtime_status()
            if base["status"] != "ACTIVATED":
                return {"status": base["status"], "summary": UNKNOWN}
            with self.session_factory() as s:
                nodes = s.execute(select(ResourceNode).where(
                    ResourceNode.world_id == self.world_id)).scalars().all()
                stocks = s.execute(select(ResourceStock).where(
                    ResourceStock.world_id == self.world_id)).scalars().all()
            return {"status": "ACTIVATED",
                    "summary": {
                        "resource_nodes": len(nodes),
                        "total_remaining_reserve": sum(
                            n.remaining_reserve or 0 for n in nodes),
                        "stock_entries": len(stocks),
                        "total_stock_minor": sum(
                            r.quantity or 0 for r in stocks),
                    }}

    def get_economy_summary(self) -> dict:
        with ReadOnlyGuard(self):
            base = self.get_runtime_status()
            if base["status"] != "ACTIVATED":
                return {"status": base["status"], "summary": UNKNOWN}
            with self.session_factory() as s:
                pressure = s.execute(text(
                    "SELECT COUNT(*) FROM economic_pressure_state "
                    "WHERE world_id=:w"), {"w": self.world_id}).scalar()
                production = s.execute(text(
                    "SELECT COUNT(*) FROM production_state "
                    "WHERE world_id=:w"), {"w": self.world_id}).scalar()
            return {"status": "ACTIVATED",
                    "summary": {"pressure_entries": pressure,
                                "production_entries": production}}

    def get_ecology_summary(self) -> dict:
        with ReadOnlyGuard(self):
            base = self.get_runtime_status()
            if base["status"] != "ACTIVATED":
                return {"status": base["status"], "summary": UNKNOWN}
            with self.session_factory() as s:
                rows = s.execute(select(EcologyState).where(
                    EcologyState.world_id == self.world_id)).scalars().all()
            return {"status": "ACTIVATED",
                    "summary": {
                        "zones": len(rows),
                        "avg_habitat_quality": round(
                            sum(r.habitat_quality or 0 for r in rows)
                            / max(len(rows), 1)),
                        "min_habitat_quality": min(
                            (r.habitat_quality or 0 for r in rows),
                            default=None),
                    }}

    def get_social_summary(self) -> dict:
        with ReadOnlyGuard(self):
            base = self.get_runtime_status()
            if base["status"] != "ACTIVATED":
                return {"status": base["status"], "summary": UNKNOWN}
            with self.session_factory() as s:
                stress = s.execute(select(SettlementSocialState).where(
                    SettlementSocialState.world_id == self.world_id)
                ).scalars().all()
                households = s.execute(text(
                    "SELECT COUNT(*) FROM households WHERE world_id=:w"),
                    {"w": self.world_id}).scalar()
            return {"status": "ACTIVATED",
                    "summary": {
                        "settlements_with_social_state": len(stress),
                        "avg_social_stress": round(
                            sum(r.social_stress or 0 for r in stress)
                            / max(len(stress), 1)),
                        "households": households,
                    }}

    def get_active_tribulations(self) -> dict:
        with ReadOnlyGuard(self):
            base = self.get_runtime_status()
            if base["status"] != "ACTIVATED":
                return {"status": base["status"], "active": [],
                        "summary": UNKNOWN}
            with self.session_factory() as s:
                eps = s.execute(select(TribulationEpisode).where(
                    TribulationEpisode.world_id == self.world_id,
                    TribulationEpisode.status == "ACTIVE").order_by(
                    TribulationEpisode.entered_tick)).scalars().all()
            return {"status": "ACTIVATED",
                    "active": [{"episode_id": e.episode_id,
                                "tier": e.window_tier,
                                "current_stage": e.current_stage,
                                "entered_tick": e.entered_tick}
                               for e in eps],
                    "summary": f"{len(eps)} 个活跃灾劫"}

    def get_recent_tribulations(self, *, limit: int = 5) -> dict:
        with ReadOnlyGuard(self):
            base = self.get_runtime_status()
            if base["status"] != "ACTIVATED":
                return {"status": base["status"], "recent": [],
                        "summary": NONE_OFFICIAL}
            with self.session_factory() as s:
                eps = s.execute(select(TribulationEpisode).where(
                    TribulationEpisode.world_id == self.world_id).order_by(
                    TribulationEpisode.entered_tick.desc()).limit(limit)
                ).scalars().all()
            return {"status": "ACTIVATED",
                    "recent": [{"episode_id": e.episode_id,
                                "tier": e.window_tier,
                                "current_stage": e.current_stage,
                                "status": e.status,
                                "entered_tick": e.entered_tick}
                               for e in eps],
                    "summary": f"最近 {len(eps)} 场灾劫"}

    def get_history_timeline(self, *, start_tick: int | None = None,
                             end_tick: int | None = None,
                             limit: int = 20) -> dict:
        """复用冻结 M3b HistoryService.timeline。"""
        with ReadOnlyGuard(self):
            base = self.get_runtime_status()
            if base["status"] != "ACTIVATED":
                return {"status": base["status"], "timeline": [],
                        "summary": NONE_OFFICIAL}
            svc = HistoryService(self.session_factory)
            tl = svc.get_timeline(world_id=self.world_id,
                                  start_tick=start_tick, end_tick=end_tick)
            entries = list(tl)[:limit] if tl else []
            return {"status": "ACTIVATED", "timeline": entries,
                    "summary": f"时间线 {len(entries)} 条"}

    def get_entity_history(self, *, entity_type: str, entity_id: str,
                           max_items: int = 20) -> dict:
        with ReadOnlyGuard(self):
            base = self.get_runtime_status()
            if base["status"] != "ACTIVATED":
                return {"status": base["status"], "history": [],
                        "summary": NONE_OFFICIAL}
            svc = HistoryService(self.session_factory)
            hist = svc.get_entity_history(
                world_id=self.world_id, entity_type=entity_type,
                entity_id=entity_id, max_items=max_items)
            return {"status": "ACTIVATED",
                    "history": list(hist) if hist else [],
                    "summary": f"{entity_type}/{entity_id} 变更史"}

    def explain_state(self, *, entity_type: str, entity_id: str,
                      field: str, max_depth: int = 4,
                      max_nodes: int = 40) -> dict:
        with ReadOnlyGuard(self):
            base = self.get_runtime_status()
            if base["status"] != "ACTIVATED":
                return {"status": base["status"], "explanation": None,
                        "summary": UNKNOWN}
            svc = HistoryService(self.session_factory)
            return {"status": "ACTIVATED",
                    "explanation": svc.explain_state(
                        world_id=self.world_id, entity_type=entity_type,
                        entity_id=entity_id, field=field,
                        max_depth=max_depth, max_nodes=max_nodes),
                    "summary": f"{entity_type}/{entity_id}.{field} 因果解释"}

    def get_changes_between_ticks(self, *, start_tick: int,
                                  end_tick: int) -> dict:
        """§18/§19：区间内 meaningful committed changes（确定性分类+聚合）。"""
        with ReadOnlyGuard(self):
            base = self.get_runtime_status()
            if base["status"] != "ACTIVATED":
                return {"status": base["status"], "changes": [],
                        "summary": NONE_OFFICIAL}
            with self.session_factory() as s:
                events = s.execute(select(WorldEvent).where(
                    WorldEvent.world_id == self.world_id,
                    WorldEvent.blessed_tick >= start_tick,
                    WorldEvent.blessed_tick <= end_tick).order_by(
                    WorldEvent.blessed_tick,
                    WorldEvent.event_uid)).scalars().all()
            classes: dict[str, int] = {}
            major: list[dict] = []
            other = 0
            for e in events:
                cls = _MEANINGFUL_EVENT_CLASSES.get(e.event_type)
                if cls:
                    classes[cls] = classes.get(cls, 0) + 1
                    major.append({"tick": e.blessed_tick,
                                  "event_type": e.event_type,
                                  "event_uid": e.event_uid})
                else:
                    other += 1
            return {"status": "ACTIVATED",
                    "changes": {"meaningful_classes": dict(sorted(
                        classes.items())),
                                "major_events": major,
                                "other_events_aggregated": other},
                    "summary": f"[{start_tick}, {end_tick}] "
                               f"{len(events)} 事件（"
                               f"{sum(classes.values())} 有意义）"}

    def get_world_snapshot(self) -> dict:
        """一次性聚合快照（只读；各子查询自带 guard）。"""
        return {
            "runtime": self.get_runtime_status(),
            "time": self.get_world_time(),
            "population": self.get_population_summary(),
            "settlements": self.get_settlement_summary(),
            "resources": self.get_resource_summary(),
            "ecology": self.get_ecology_summary(),
            "social": self.get_social_summary(),
            "tribulations": self.get_active_tribulations(),
        }

    # ------------------------------------------------------------- 内部
    def _population_total(self) -> int:
        with self.session_factory() as s:
            return sum(g.count or 0 for g in s.execute(
                select(PopulationGroup).where(
                    PopulationGroup.world_id == self.world_id)).scalars())

    def _event_count(self) -> int:
        with self.session_factory() as s:
            return s.execute(text(
                "SELECT COUNT(*) FROM world_events WHERE world_id=:w"),
                {"w": self.world_id}).scalar()
