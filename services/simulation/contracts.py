# -*- coding: utf-8 -*-
"""M2 Engine Contract（冻结于 runtime_design/M2_PREFLIGHT_ENGINE_CONTRACT.md）。

- Engine Protocol：simulate(ctx) -> EngineResult；引擎零 commit/LLM/网络/wall-clock/UUID。
- Engine Order（CONFIRMED，恢复自 04_time_engine §4）：
  TIME→DEMOGRAPHY→RESOURCE→ECONOMY→ECOLOGY→SOCIAL→(TRIBULATION: NOT_REGISTERED)→EVENT。
- 所有权表：引擎只能 propose 自己的实体（coordinator 强制）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:  # pragma: no cover
    from .snapshot import StagedWorld, WorldSnapshot
    from ..rng_service import RngStream

ENGINE_ORDER: tuple[str, ...] = (
    "DEMOGRAPHY", "RESOURCE", "ECONOMY", "ECOLOGY", "SOCIAL")
TRIBULATION_SLOT = "TRIBULATION"
TRIBULATION_SLOT_STATE = "NOT_REGISTERED"

ENGINE_OWNERSHIP: dict[str, frozenset[str]] = {
    "DEMOGRAPHY": frozenset({"population_groups"}),
    "RESOURCE": frozenset({"resource_nodes"}),
    "ECONOMY": frozenset({"resource_stocks", "production_state",
                          "economic_pressure_state"}),
    # ecological_regions = M0 遗留生态表（Preflight 所有权契约保留；
    # M2c EcologyEngine 实际只写 ecology_state / ecology_feedback_state）
    "ECOLOGY": frozenset({"ecological_regions", "ecology_state",
                          "ecology_feedback_state"}),
    # M2d：lineages/institutions 保留 Preflight 契约；households /
    # settlement_social_state / social_feedback_state 为 M2d 新增
    "SOCIAL": frozenset({"lineages", "institutions", "households",
                         "settlement_social_state", "social_feedback_state"}),
}

PREFLIGHT_SIMULATION_VERSION = "0.2.0-preflight"
PREFLIGHT_PIPELINE_VERSION = "m2-preflight-1"
NOOP_ENGINE_VERSION = "noop-0"


@dataclass(frozen=True)
class StateChange:
    """一条 proposed state mutation（staged；authoritative 写入由 coordinator
    统一执行，引擎零 commit）。

    - UPDATE 语义：entity_id + field + new_value（既有行字段更新）。
    - INSERT 语义（M2d 扩展，NEW_PROPOSAL）：new_row 非 None —— coordinator
      创建该行（确定性 id 由引擎派生，无 UUID4/autoincrement 依赖）。
    """
    table: str
    entity_id: int | None
    field: str | None
    old_value: object
    new_value: object
    new_row: dict | None = None


@dataclass(frozen=True)
class DomainEventDraft:
    """机器级 domain event（确定性 identity 由 coordinator 赋予）。"""
    engine_id: str
    event_type: str
    cause: dict = field(default_factory=dict)
    effect: dict = field(default_factory=dict)
    severity: float = 0.0
    scope: str = "WORLD"


@dataclass(frozen=True)
class EngineResult:
    engine_id: str
    engine_version: str
    proposed_changes: list[StateChange] = field(default_factory=list)
    domain_events: list[DomainEventDraft] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    draw_count: int = 0


@dataclass(frozen=True)
class SimulationContext:
    """一次 simulation step 的只读上下文（引擎唯一输入面）。"""
    world_id: str
    simulation_version: str
    pipeline_version: str
    step_index: int
    blessed_start_tick: int
    blessed_end_tick: int
    real_interval_start_us: int
    real_interval_end_us: int
    snapshot: "WorldSnapshot"
    staged: "StagedWorld"
    rng: "RngStream"
    modifiers: dict = field(default_factory=dict)  # 跨引擎 modifier 槽（M2b neutral）
    crash_after: str | None = None  # 测试专用崩溃注入点（引擎可在此 raise）


class Engine(Protocol):
    """M2 引擎统一协议（引擎不得持有 session；不得 commit）。"""
    engine_id: str
    engine_version: str

    def simulate(self, ctx: SimulationContext) -> EngineResult:
        ...


class NoOpEngine:
    """NoOp 引擎：验证管线可运行、确定性可证明（M2_PREFLIGHT 用）。"""

    engine_id: str
    engine_version: str = NOOP_ENGINE_VERSION

    def __init__(self, engine_id: str):
        if engine_id not in ENGINE_ORDER:
            raise ValueError(f"未知引擎: {engine_id}")
        self.engine_id = engine_id

    def simulate(self, ctx: SimulationContext) -> EngineResult:
        return EngineResult(engine_id=self.engine_id,
                            engine_version=self.engine_version,
                            metrics={"steps": 1})


class DeterministicFakeEngine:
    """确定性 Fake 引擎：消耗固定次数 RNG 并产出确定性 metrics/事件。

    仅用于 harness 测试（证明 RNG 隔离、事件纪律、哈希稳定）；
    不做任何真实业务演化。
    """

    engine_id: str
    engine_version: str = "fake-1"

    def __init__(self, engine_id: str, draws: int = 3):
        if engine_id not in ENGINE_ORDER:
            raise ValueError(f"未知引擎: {engine_id}")
        self.engine_id = engine_id
        self.draws = draws

    def simulate(self, ctx: SimulationContext) -> EngineResult:
        samples = [ctx.rng.randint(0, 10**6) for _ in range(self.draws)]
        return EngineResult(
            engine_id=self.engine_id, engine_version=self.engine_version,
            draw_count=self.draws,
            metrics={"rng_sum": sum(samples), "draws": self.draws},
            domain_events=[DomainEventDraft(
                engine_id=self.engine_id, event_type="FAKE_STEP",
                cause={"step_tick": ctx.blessed_start_tick},
                effect={"rng_sum": sum(samples)})])
