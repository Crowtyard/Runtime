# -*- coding: utf-8 -*-
"""RuntimeScheduler（M4）—— 只负责“什么时候跑、跑多少、谁写、失败如何恢复”。

Scheduler = orchestration；Engine = semantics。本模块：
- 绝不决定世界里发生什么（只调用冻结 coordinator + catch_up）；
- 正式未激活世界（NOT_ACTIVATED）→ DORMANT：零 mutation、零租约；
- 任何 authoritative safety 错误 → FAILED / RECOVERING（fail-closed），
  scheduler 内存状态永远不是世界真值；
- operational 状态（含 pause 位、计数器）持久化到 runtime_state JSON
  （原子 tmp+replace；不进世界 DB、不是世界真值）。

测试注入（只测试用）：
- real_now_us_provider：确定性现实锚（生产 = 冻结时间服务；测试 = EPOCH 注入）
- coordinator_provider：冻结引擎协调器（M6 接线；测试 = 真实 M3 pipeline）
- _crash_point / checkpoint 崩溃注入：scheduler-specific crash 点
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Callable

from sqlalchemy import select
from sqlalchemy import exc as sa_exc
from sqlalchemy.orm import Session, sessionmaker

from ...database.models_core import WorldRuntime
from ...domain.constants import RuntimeStatus
from ...domain.errors import FencingViolation, WriterLockConflict
from ..durable_truth import (
    read_durable_tick_resilient, read_world_epoch_anchor)
from ..logging_setup import get_logger
from ..simulation.harness import MINI_WORLD_EPOCH0_US
from ..simulation.tribulation import (M3A_SIMULATION_VERSION,
                                      TICKS_PER_BLESSED_YEAR)
from ..writer_lock import WriterLease
from .adapter import run_blessed_year
from .config import SchedulerConfig
from .planner import CatchUpPlan, CatchUpPlanner
from .state import SchedulerState, SchedulerStatusSnapshot

#: 未激活世界的 operational 默认年锚。**不是**世界真值：世界一旦激活，
#: 年锚一律来自 durable activation anchor（M6B §1 OPTION A）。
DEFAULT_OPERATIONAL_EPOCH0_US = MINI_WORLD_EPOCH0_US

log = get_logger("SCHEDULER")

_CHECKPOINT_VERSION = 1


class SchedulerCrash(RuntimeError):
    """scheduler-specific 崩溃注入信号（只测试用；与 commit 歧义区分）。

    崩溃 = 进程语义（调用方模拟死亡后恢复）；commit 歧义 = durable 状态
    未知（scheduler 自身 RECOVERING）。两者绝不能混为一谈。
    """

# scheduler-specific crash 注入点（§15；engine 级注入点沿用 M3c 77 项）
CRASH_POINTS = frozenset({
    "before_activation_check", "after_activation_check",
    "before_writer_acquire", "after_writer_acquire",
    "before_heartbeat", "after_heartbeat",
    "before_catchup_planning", "after_catchup_planning",
    "before_batch_execution", "during_batch_preparation",
    "before_authoritative_commit",
    "after_ack_before_checkpoint", "during_scheduler_checkpoint",
    "after_checkpoint", "before_lease_renewal",
    "during_shutdown",
})


class RuntimeScheduler:
    """Runtime 自动调度器（synchronous run_cycle；宿主负责循环/睡眠）。"""

    def __init__(self, *, session_factory: sessionmaker[Session],
                 world_id: str,
                 config: SchedulerConfig | None = None,
                 real_now_us_provider: Callable[[], int] | None = None,
                 epoch0_us: int | None = None,
                 coordinator_provider: Callable | None = None,
                 simulation_version: str = M3A_SIMULATION_VERSION,
                 state_dir: Path | None = None):
        self.session_factory = session_factory
        self.world_id = world_id
        self.config = config or SchedulerConfig()
        # M6B / OPTION A：epoch0_us=None → **每 cycle 从 durable truth 解析年锚**
        # （已激活世界用 durable activation anchor；未激活世界用既有 operational
        # 默认）。显式传入（既有 M4 测试路径）→ 行为与 M6 之前逐字一致。
        self._explicit_epoch0_us = epoch0_us
        self.epoch0_us = (epoch0_us if epoch0_us is not None
                          else DEFAULT_OPERATIONAL_EPOCH0_US)
        self.simulation_version = simulation_version
        self._real_now_provider = real_now_us_provider
        self._coordinator_provider = coordinator_provider
        self.state_dir = Path(state_dir) if state_dir is not None else None

        self._lock = threading.RLock()
        self._state = SchedulerState.STOPPED
        self._paused = False
        self._lease: WriterLease | None = None
        self._lease_session: Session | None = None

        # counters（持久化）
        self._cycle = 0
        self._batches_total = 0
        self._recovery_count = 0
        self._lease_takeover_count = 0
        self._stale_writer_rejection_count = 0
        self._commit_ambiguity_count = 0
        self._last_successful_commit = 0
        self._last_batch_ticks = 0
        self._last_error: str | None = None

        # 测试注入
        self._crash_point: str | None = None
        self._checkpoint_crash_after_write = False

        # planner 按“生效年锚”缓存（动态模式下每 cycle 依据 durable anchor 重建）
        self._planner = (CatchUpPlanner(world_id=world_id, epoch0_us=epoch0_us)
                         if epoch0_us is not None else None)

    # ------------------------------------------------------------- Epoch Anchoring
    def _effective_epoch0_us(self, row: WorldRuntime | None) -> int | None:
        """本 cycle 生效的世界年锚（M6B §1/§2/§3：Scheduler Alignment Contract）。

        - 显式注入（既有 M4 测试路径）→ 原样使用（语义不变）；
        - 世界**已激活** → 必须读 durable activation anchor：绝不按当前系统时间
          重新生成，也绝不在 restart / 进程替换 / crash recovery 后改变；
          读不到 → 返回 ``None``（调用方 fail-closed，**绝不偷偷 repair**）；
        - 世界**未激活** → 既有 operational 默认（DORMANT 路径，不触达世界真值）。
        """
        if self._explicit_epoch0_us is not None:
            return self._explicit_epoch0_us
        if row is not None and self._activated(row):
            return read_world_epoch_anchor(self.session_factory,
                                           world_id=self.world_id)
        return DEFAULT_OPERATIONAL_EPOCH0_US

    def _planner_for(self, epoch0_us: int) -> CatchUpPlanner:
        """按生效年锚取 planner（缓存按 anchor 值；anchor 本身每 cycle 从 durable truth 读）。"""
        if self._planner is None or self._planner.epoch0_us != epoch0_us:
            self._planner = CatchUpPlanner(world_id=self.world_id,
                                           epoch0_us=epoch0_us)
        return self._planner

    # ------------------------------------------------------------- 生命周期
    def start(self) -> bool:
        """幂等启动：STOPPED → STARTING（加载持久化 pause/计数器）。

        返回 False 表示已在运行（不产生第二个循环）。
        """
        with self._lock:
            if self._state not in (SchedulerState.STOPPED,
                                   SchedulerState.FAILED):
                return False
            self._load_checkpoint()
            self._state = SchedulerState.STARTING
            log.info("scheduler start world=%s", self.world_id)
            return True

    def stop(self) -> None:
        """幂等停止：STOPPING → 释放租约 → 持久化 → STOPPED。

        不产生任何世界推进；强杀场景交给 crash recovery + fencing。
        """
        with self._lock:
            if self._state in (SchedulerState.STOPPED,):
                return
            self._state = SchedulerState.STOPPING
            self._maybe_crash("during_shutdown")
            self._release_lease()
            self._persist_checkpoint()
            self._state = SchedulerState.STOPPED
            log.info("scheduler stop world=%s", self.world_id)

    def pause(self) -> None:
        """持久化暂停：不提交新 tick；释放租约；现实时间照常形成 backlog。"""
        with self._lock:
            self._paused = True
            self._persist_checkpoint()
            self._release_lease()
            self._state = SchedulerState.PAUSED
            log.info("scheduler pause world=%s（不发明时间规律）",
                     self.world_id)

    def resume(self) -> None:
        """显式清除 pause → STANDBY（下个 cycle 重新取得 writer）。"""
        with self._lock:
            self._paused = False
            self._persist_checkpoint()
            if self._state == SchedulerState.PAUSED:
                self._state = SchedulerState.STANDBY
            log.info("scheduler resume world=%s", self.world_id)

    # ------------------------------------------------------------- 主循环
    def run_cycle(self) -> SchedulerStatusSnapshot:
        """执行一个调度周期（同步；宿主负责轮询间隔）。

        行为模型（§6）：verify_activation → pause → writer → plan →
        batch execute（冻结 pipeline）→ checkpoint → observe。
        """
        with self._lock:
            if self._state == SchedulerState.STOPPED:
                raise RuntimeError("scheduler 未启动（先 start()）")
            if self._state == SchedulerState.FAILED:
                raise RuntimeError("scheduler 处于 FAILED（fail-closed，"
                                   "需外部诊断）")
            if self._state == SchedulerState.STARTING:
                self._state = SchedulerState.STANDBY

            # ---- 1) Activation Gate（任何 authoritative mutation 之前）
            self._maybe_crash("before_activation_check")
            row = self._read_runtime_row()
            self._maybe_crash("after_activation_check")
            if not self._activated(row):
                self._release_lease()
                self._state = SchedulerState.DORMANT
                self._persist_checkpoint()
                return self._snapshot(row)
            # ---- 1b) Epoch Anchor（M6B OPTION A）：已激活世界必须用 durable anchor
            epoch0_us = self._effective_epoch0_us(row)
            if epoch0_us is None:
                self._fail(
                    "已激活世界缺少 durable activation anchor"
                    "（fail-closed：拒绝按当前时间重建年锚，也绝不偷偷 repair）")
                return self._snapshot(row)
            if self._paused:
                self._release_lease()
                self._state = SchedulerState.PAUSED
                return self._snapshot(row)

            # ---- 2) Writer / Fencing
            self._maybe_crash("before_writer_acquire")
            try:
                self._ensure_writer()
            except WriterLockConflict:
                # 另一 writer 活跃：不抢、不推进，STANDBY 等待
                self._state = SchedulerState.STANDBY
                return self._snapshot(row)
            self._maybe_crash("after_writer_acquire")
            self._maybe_crash("before_heartbeat")
            if not self._heartbeat_guarded():
                return self._snapshot(row)  # stale writer：RECOVERING 已置位
            self._maybe_crash("after_heartbeat")

            # ---- 3) Catch-up 规划（只读预演；权威转换在 catch_up）
            self._maybe_crash("before_catchup_planning")
            now_real_us = self._real_now()
            try:
                with self.session_factory() as s:
                    plan = self._planner_for(epoch0_us).plan(
                        s, now_real_us=now_real_us,
                        budget_ticks=self.config.catch_up_max_ticks_per_cycle)
            except RuntimeError as exc:
                # 规划阶段 fail-closed（M6B §4）：durable 时钟与年锚不自洽/未初始化
                # → FAILED，零写入；**绝不**猜测、**绝不**偷偷 repair。
                self._fail(f"catch-up 规划失败（fail-closed）: {exc}")
                return self._snapshot(row)
            self._maybe_crash("after_catchup_planning")
            self._cycle += 1
            if plan.due_ticks <= 0 or plan.batch_years == 0:
                self._state = SchedulerState.RUNNING
                self._persist_checkpoint()
                return self._snapshot(row)

            # ---- 4) 批次执行（冻结 pipeline；年粒度）
            self._state = SchedulerState.CATCHING_UP
            self._maybe_crash("before_batch_execution")
            try:
                executed_ticks = self._execute_batch(plan, epoch0_us)
            except FencingViolation:
                # stale writer：_execute_batch 已停止 mutation 并置 RECOVERING
                return self._snapshot(row)
            if self._state == SchedulerState.FAILED:
                return self._snapshot(row)  # fail-closed：不再覆盖状态
            self._maybe_crash("before_authoritative_commit")

            # ---- 5) plan/execute 一致性（fail-closed）
            with self.session_factory() as s:
                row2 = self._read_runtime_row(s)
                new_tick = (row2.current_blessed_tick
                            if row2 is not None else None)
            expected = plan.durable_tick + executed_ticks
            if new_tick != expected:
                self._fail(
                    "plan/execute 不一致（fail-closed）: "
                    f"expected_tick={expected} durable_tick={new_tick}")
                return self._snapshot(row)

            # ---- 6) Scheduler checkpoint（非世界真值）
            self._maybe_crash("after_ack_before_checkpoint")
            self._last_successful_commit = self._cycle
            self._persist_checkpoint()
            self._maybe_crash("after_checkpoint")
            self._state = SchedulerState.RUNNING
            return self._snapshot(row2)

    # ------------------------------------------------------------- 批次执行
    def _execute_batch(self, plan: CatchUpPlan, epoch0_us: int) -> int:
        executed_ticks = 0
        coordinator = None
        for year_index in plan.year_indices:
            self._maybe_crash("during_batch_preparation")
            if coordinator is None:
                if self._coordinator_provider is None:
                    self._fail("coordinator provider 未配置（fail-closed）")
                    raise RuntimeError(
                        "coordinator provider 未配置，无法执行冻结 pipeline")
                coordinator = self._coordinator_provider()
            try:
                run_blessed_year(
                    self.session_factory, world_id=self.world_id,
                    year_index=year_index, coordinator=coordinator,
                    lease=self._lease, epoch0_us=epoch0_us,
                    simulation_version=self.simulation_version)
            except SchedulerCrash:
                raise  # 崩溃注入：模拟进程死亡，调用方恢复
            except FencingViolation as exc:
                # 租约已被接管：立即停止 mutation，绝不“这批写完算了”
                self._stale_writer_rejection_count += 1
                self._release_lease()
                self._state = SchedulerState.RECOVERING
                self._recovery_count += 1
                self._last_error = f"fencing violation: {exc}"
                self._persist_checkpoint()
                raise
            except RuntimeError as exc:
                # commit 歧义可能：绝不盲重试 —— 先核对 durable truth
                self._commit_ambiguity_count += 1
                self._recovery_count += 1
                self._state = SchedulerState.RECOVERING
                recovered = self._recover_truth(year_index, exc)
                if not recovered:
                    # FAILED（fail-closed）：停止本批，返回已执行量
                    return executed_ticks
                # durable truth 表明该年已提交 → 已推进，继续
            except sa_exc.DBAPIError as exc:
                # PG-012：真实数据库连接故障（OperationalError / InterfaceError /
                # AdminShutdown 等）**不是** RuntimeError，但同样意味着
                # "COMMIT 结果未知" → 必须走同一 durable-truth 核对路径，
                # 绝不盲重试；无法判定即 fail-closed。（连接在 COMMIT 期间断开、
                # 服务器重启等真实故障由此覆盖。）
                self._commit_ambiguity_count += 1
                self._recovery_count += 1
                self._state = SchedulerState.RECOVERING
                log.warning("db connection failure during batch (ambiguity) "
                            "world=%s year=%s err=%s", self.world_id,
                            year_index, type(exc).__name__)
                recovered = self._recover_truth(year_index, exc)
                if not recovered:
                    return executed_ticks
            executed_ticks += TICKS_PER_BLESSED_YEAR
            self._batches_total += 1
            self._last_batch_ticks = TICKS_PER_BLESSED_YEAR
            self._maybe_crash("before_lease_renewal")
            if not self._heartbeat_guarded():
                raise FencingViolation(
                    "批次中途租约被接管（立即停止 mutation）",
                    detail={"world_id": self.world_id})
        return executed_ticks

    def _read_durable_tick_resilient(self) -> int | None:
        """读取 durable tick；连接故障时重试一次（失效连接会被连接池回收）。

        仍失败则抛出 —— 调用方必须 fail-closed（durable truth 不可判定时
        绝不允许继续推进）。

        M6A：实现委托给 ``services.durable_truth``（正式世界激活服务共用**同一份**
        commit-ambiguity 核对实现）—— 禁止第二套 commit 协议（§16 / PG-012）。
        语义与迁移前逐字一致（fresh session / 仅 DBAPIError 重试 / 耗尽后抛出）。
        """
        return read_durable_tick_resilient(self.session_factory,
                                           world_id=self.world_id)

    def _recover_truth(self, year_index: int, exc: Exception) -> bool:
        """commit 歧义恢复：durable truth 优先；失败即 fail-closed。"""
        year_end_tick = (year_index + 1) * TICKS_PER_BLESSED_YEAR
        try:
            tick = self._read_durable_tick_resilient()
        except Exception as read_exc:  # noqa: BLE001
            # durable truth 不可判定 → 绝不猜测、绝不盲重试
            self._fail(f"commit 状态未知且 durable truth 不可读取: {read_exc}")
            return False
        if tick is not None and tick >= year_end_tick:
            # durable 已提交（ACK 丢失前 commit 成功）→ 不重试、继续
            self._last_error = (
                f"commit ambiguity resolved from durable truth: {exc}")
            log.warning("commit ambiguity: year=%s durable_tick=%s",
                        year_index, tick)
            return True
        self._fail(f"commit 状态未知且 durable truth 未推进: {exc}")
        return False

    # ------------------------------------------------------------- writer
    def _ensure_writer(self) -> None:
        if self._lease is not None:
            return
        from ...database.base import utcnow
        from ...database.models_core import RuntimeLock
        lease_session = self.session_factory()
        # 接管检测：acquire 前读共享租约行（跨实例真相）
        lock = lease_session.execute(
            select(RuntimeLock).where(
                RuntimeLock.world_id == self.world_id)
        ).scalar_one_or_none()
        takeover = lock is not None and lock.expires_at <= utcnow()
        lease = WriterLease(lease_session, self.world_id,
                            self.config.lease_seconds())
        lease.acquire()
        self._lease = lease
        self._lease_session = lease_session
        if takeover:
            self._lease_takeover_count += 1
            log.info("scheduler took over expired lease world=%s",
                     self.world_id)

    def _heartbeat(self) -> None:
        if self._lease is not None:
            self._lease.renew()

    def _heartbeat_guarded(self) -> bool:
        """心跳；租约被接管（token 失效）→ 记录 stale、释放本地引用、
        RECOVERING，返回 False（停止 mutation）。"""
        try:
            self._heartbeat()
            return True
        except WriterLockConflict as exc:
            self._stale_writer_rejection_count += 1
            self._recovery_count += 1
            self._release_lease()
            self._state = SchedulerState.RECOVERING
            self._last_error = f"heartbeat fencing loss: {exc}"
            self._persist_checkpoint()
            log.warning("stale writer detected world=%s: %s",
                        self.world_id, exc)
            return False

    def _release_lease(self) -> None:
        if self._lease is not None:
            try:
                self._lease.release()
            except Exception as exc:  # noqa: BLE001
                log.warning("lease release failed (expiry fallback): %s", exc)
            self._lease = None
        if self._lease_session is not None:
            try:
                self._lease_session.close()
            except Exception:  # noqa: BLE001
                pass
            self._lease_session = None

    # ------------------------------------------------------------- 状态读取
    def _read_runtime_row(self, session: Session | None = None) -> WorldRuntime | None:
        if session is None:
            with self.session_factory() as s:
                return self._read_runtime_row(s)
        return session.execute(
            select(WorldRuntime).where(
                WorldRuntime.world_id == self.world_id)
        ).scalar_one_or_none()

    @staticmethod
    def _activated(row: WorldRuntime | None) -> bool:
        return (row is not None
                and row.runtime_status == RuntimeStatus.ACTIVE
                and row.world_seed_version is not None)

    def _real_now(self) -> int:
        if self._real_now_provider is None:
            raise RuntimeError("real_now_us_provider 未配置（fail-closed）")
        return int(self._real_now_provider())

    def _fail(self, message: str) -> None:
        self._last_error = message
        self._state = SchedulerState.FAILED
        self._release_lease()
        self._persist_checkpoint()
        log.error("scheduler FAILED world=%s: %s", self.world_id, message)

    def _snapshot(self, row: WorldRuntime | None) -> SchedulerStatusSnapshot:
        activated = self._activated(row)
        target = None
        pending = 0
        if activated and row is not None and row.current_blessed_tick is not None:
            # 只读路径：年锚解析失败**不**改变 scheduler 状态（真正的 fail-closed
            # 发生在 run_cycle 的规划阶段）
            epoch0_us = None
            try:
                epoch0_us = self._effective_epoch0_us(row)
            except Exception:  # noqa: BLE001
                epoch0_us = None
            if epoch0_us is not None:
                try:
                    with self.session_factory() as s:
                        target = self._planner_for(epoch0_us).compute_target_tick(
                            s, self._real_now())
                except Exception:  # noqa: BLE001
                    target = None
            if target is not None:
                pending = max(0, target - row.current_blessed_tick)
        return SchedulerStatusSnapshot(
            scheduler_state=self._state.value,
            runtime_activation_state=(row.runtime_status if row is not None
                                      else None),
            writer_owned=self._lease is not None,
            writer_instance_id=(self._lease.owner
                                if self._lease is not None else None),
            fencing_token=(self._lease.token
                           if self._lease is not None else None),
            last_scheduler_cycle=self._cycle,
            last_successful_commit=self._last_successful_commit,
            durable_current_tick=(row.current_blessed_tick
                                  if activated and row is not None else None),
            target_tick=(target if activated else None),
            pending_catchup_ticks=pending,
            last_batch_ticks=self._last_batch_ticks,
            catchup_batches_total=self._batches_total,
            recovery_count=self._recovery_count,
            lease_takeover_count=self._lease_takeover_count,
            stale_writer_rejection_count=self._stale_writer_rejection_count,
            commit_ambiguity_count=self._commit_ambiguity_count,
            last_error=self._last_error,
            pause_state=self._paused,
            config={
                "poll_interval_ms": self.config.poll_interval_ms,
                "catch_up_max_ticks_per_cycle":
                    self.config.catch_up_max_ticks_per_cycle,
                "lease_ttl_ms": self.config.lease_ttl_ms,
                "heartbeat_interval_ms": self.config.heartbeat_interval_ms,
            },
        )

    def get_scheduler_status(self) -> dict:
        """§18 只读可观测性快照（不修改世界语义）。"""
        with self._lock:
            row = self._read_runtime_row()
            return self._snapshot(row).as_dict()

    # ------------------------------------------------------------- checkpoint
    def _checkpoint_path(self) -> Path | None:
        if self.state_dir is None:
            return None
        return self.state_dir / "scheduler_state.json"

    def _persist_checkpoint(self) -> None:
        path = self._checkpoint_path()
        if path is None:
            return
        payload = {
            "version": _CHECKPOINT_VERSION,
            "world_id": self.world_id,
            "scheduler_state": self._state.value,
            "pause_state": self._paused,
            "counters": {
                "cycle": self._cycle,
                "batches_total": self._batches_total,
                "recovery_count": self._recovery_count,
                "lease_takeover_count": self._lease_takeover_count,
                "stale_writer_rejection_count":
                    self._stale_writer_rejection_count,
                "commit_ambiguity_count": self._commit_ambiguity_count,
                "last_successful_commit": self._last_successful_commit,
                "last_batch_ticks": self._last_batch_ticks,
            },
            "last_error": self._last_error,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        if self._checkpoint_crash_after_write:
            raise SchedulerCrash("scheduler crash: during_scheduler_checkpoint")
        tmp.replace(path)

    def _load_checkpoint(self) -> None:
        path = self._checkpoint_path()
        if path is None or not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            log.warning("scheduler checkpoint 损坏，忽略（durable truth 优先）")
            return
        if data.get("version") != _CHECKPOINT_VERSION:
            return
        self._paused = bool(data.get("pause_state", False))
        c = data.get("counters", {})
        self._cycle = int(c.get("cycle", 0))
        self._batches_total = int(c.get("batches_total", 0))
        self._recovery_count = int(c.get("recovery_count", 0))
        self._lease_takeover_count = int(c.get("lease_takeover_count", 0))
        self._stale_writer_rejection_count = int(
            c.get("stale_writer_rejection_count", 0))
        self._commit_ambiguity_count = int(c.get("commit_ambiguity_count", 0))
        self._last_successful_commit = int(c.get("last_successful_commit", 0))
        self._last_batch_ticks = int(c.get("last_batch_ticks", 0))
        self._last_error = data.get("last_error")
        log.info("scheduler checkpoint loaded: paused=%s cycle=%s",
                 self._paused, self._cycle)

    # ------------------------------------------------------------- 测试注入
    def set_crash_point(self, point: str | None) -> None:
        if point is not None and point not in CRASH_POINTS:
            raise ValueError(f"未知 scheduler crash 点: {point}")
        if point == "during_scheduler_checkpoint":
            # 该点由 checkpoint 原子写机制注入（tmp 写出后、replace 前）
            self._checkpoint_crash_after_write = True
            self._crash_point = None
            return
        self._crash_point = point

    def _maybe_crash(self, point: str) -> None:
        if self._crash_point == point:
            self._crash_point = None  # 单次触发
            raise SchedulerCrash(f"scheduler crash: {point}")
