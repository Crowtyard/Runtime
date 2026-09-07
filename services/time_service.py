"""时间服务（10 节）：aware UTC、时钟异常、TIME_RATIO_HISTORY 分段积分。

CANONICAL_BLESSED_TICK：世界时间一律为整数 canonical tick（µy，见
domain/blessed_time）；速率 = 有量纲有理速率 TimeRate（整数 numerator/denominator，
禁止 float 倍率）。本模块提供按 effective interval 分段积分，
禁止"拿当前速率倒推全部历史"。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from ..domain.blessed_time import TimeRate, datetime_to_epoch_us
from ..domain.errors import ClockAnomaly
from .time_engine import Integrator


def to_utc(dt: datetime) -> datetime:
    """naive 视为 UTC（系统层禁止本地时区串/夏令时）。"""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class RateSegment:
    """一个速率生效段：real 时间窗 + TimeRate（由 TIME_RATIO_HISTORY 切分而来）。"""
    real_start: datetime
    real_end: datetime
    rate: TimeRate
    reason: str


def blessed_ticks_over_segments(segments: list[RateSegment]) -> int:
    """按多个速率生效段分段积分，返回整数 canonical tick 总量。

    - 每段按 ticks = (µ_real × num) // den 精确整数换算，全程无浮点。
    - 舍入政策：floor；**同一速率的连续分段共享余数进位**（有理精确累加，
      24×1h 与 1×24h 结果完全一致，无累计 drift）；**跨速率分段进位重置**
      （余数量纲随速率变化，不得跨速率传递）。
    - 禁止：拿当前 time_rate 倒推全部过去时间 —— 调用方必须先从
      time_ratio_history 查询 effective-dated 区间并切分为 segments。
    - 调用约定：segments 必须按时间有序、不重叠。
    - 实现：委托 services/time_engine.Integrator（M1 时间引擎同一数学核心）。
    """
    integrator = Integrator()
    for seg in segments:
        integrator.add_segment(
            datetime_to_epoch_us(seg.real_start),
            datetime_to_epoch_us(seg.real_end),
            seg.rate)
    return integrator.total_ticks


def check_clock_forward(now: datetime, last_simulated_real_time: datetime | None) -> None:
    """system clock rollback 保护：now < last → CLOCK_ANOMALY。"""
    if last_simulated_real_time is not None and to_utc(now) < to_utc(last_simulated_real_time):
        raise ClockAnomaly(
            "系统时间回拨：now < last_simulated_real_time",
            detail={"now": str(now), "last": str(last_simulated_real_time)})
