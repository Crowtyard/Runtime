# -*- coding: utf-8 -*-
"""Scheduler 配置（M4）：operational 参数，integer only，严格校验 fail-closed。

世界规则不在这里（由 World State/World Rule 表管理）；此处只有调度节奏与
安全边界参数。所有时间配置使用整数毫秒/整数 blessed tick，禁止 authoritative
float。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SchedulerConfig:
    """RuntimeScheduler operational 配置（严格校验，非法即抛 ValueError）。"""

    enabled: bool = True
    poll_interval_ms: int = 5_000
    catch_up_max_ticks_per_cycle: int = 100_000_000  # 每 cycle 至多 100 福地年
    lease_ttl_ms: int = 120_000
    heartbeat_interval_ms: int = 30_000
    shutdown_grace_ms: int = 5_000
    # 检查点持久化目录（plugin_data/runtime_state；非世界 DB）
    checkpoint_dir: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ValueError("scheduler.enabled 必须为 bool")
        if self.poll_interval_ms < 1:
            raise ValueError("scheduler.poll_interval_ms 必须 >= 1")
        if self.catch_up_max_ticks_per_cycle < 1:
            raise ValueError("scheduler.catch_up_max_ticks_per_cycle 必须 >= 1")
        if self.heartbeat_interval_ms < 1:
            raise ValueError("scheduler.heartbeat_interval_ms 必须 >= 1")
        if self.lease_ttl_ms < 1:
            raise ValueError("scheduler.lease_ttl_ms 必须 >= 1")
        if self.heartbeat_interval_ms >= self.lease_ttl_ms:
            raise ValueError(
                "scheduler.heartbeat_interval_ms 必须 < lease_ttl_ms"
                "（否则租约将在两次心跳之间过期）")
        if self.shutdown_grace_ms < 0:
            raise ValueError("scheduler.shutdown_grace_ms 必须 >= 0")

    def lease_seconds(self) -> int:
        """WriterLease 使用整数秒；ceil(ms/1000)，最少 1 秒。"""
        return max(1, (self.lease_ttl_ms + 999) // 1000)

    def batch_years_per_cycle(self) -> int:
        """每 cycle 至多推进的整福地年数（冻结引擎原子粒度 = 1 年 = 1e6 ticks）。"""
        return max(1, self.catch_up_max_ticks_per_cycle // 1_000_000)
