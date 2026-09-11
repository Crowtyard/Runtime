# -*- coding: utf-8 -*-
"""Scheduler operational 状态机（M4）。

这些状态是 scheduler operational state，不是 world simulation state，
绝不写入世界事件史。世界语义（推进/灾劫/历史）与这些状态无关。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class SchedulerState(str, Enum):
    STARTING = "STARTING"
    DORMANT = "DORMANT"        # 世界未激活：零 mutation、零租约
    STANDBY = "STANDBY"        # 已激活但未持有 writer（或已 resume 未取回租约）
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"          # 持久化暂停：不提交新 tick；不发明时间规律
    CATCHING_UP = "CATCHING_UP"
    RECOVERING = "RECOVERING"  # 崩溃/ACK/commit-ambiguity 后核对 durable truth
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    FAILED = "FAILED"          # fail-closed：停止推进，等待外部诊断


@dataclass
class SchedulerStatusSnapshot:
    """§18 可观测性快照（read-only w.r.t. world semantics）。

    DORMANT（正式未激活世界）：durable_current_tick / target_tick 必须为 None，
    不得为展示伪造 0 tick（NULL 与 0 语义不同）。
    """

    scheduler_state: str = SchedulerState.STOPPED.value
    runtime_activation_state: str | None = None
    writer_owned: bool = False
    writer_instance_id: str | None = None
    fencing_token: str | None = None
    last_scheduler_cycle: int = 0
    last_successful_commit: int = 0
    durable_current_tick: int | None = None
    target_tick: int | None = None
    pending_catchup_ticks: int = 0
    last_batch_ticks: int = 0
    catchup_batches_total: int = 0
    recovery_count: int = 0
    lease_takeover_count: int = 0
    stale_writer_rejection_count: int = 0
    commit_ambiguity_count: int = 0
    last_error: str | None = None
    pause_state: bool = False
    config: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "scheduler_state": self.scheduler_state,
            "runtime_activation_state": self.runtime_activation_state,
            "writer_owned": self.writer_owned,
            "writer_instance_id": self.writer_instance_id,
            "fencing_token": self.fencing_token,
            "last_scheduler_cycle": self.last_scheduler_cycle,
            "last_successful_commit": self.last_successful_commit,
            "durable_current_tick": self.durable_current_tick,
            "target_tick": self.target_tick,
            "pending_catchup_ticks": self.pending_catchup_ticks,
            "last_batch_ticks": self.last_batch_ticks,
            "catchup_batches_total": self.catchup_batches_total,
            "recovery_count": self.recovery_count,
            "lease_takeover_count": self.lease_takeover_count,
            "stale_writer_rejection_count":
                self.stale_writer_rejection_count,
            "commit_ambiguity_count": self.commit_ambiguity_count,
            "last_error": self.last_error,
            "pause_state": self.pause_state,
            "config": dict(self.config),
        }
