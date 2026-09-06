"""时间服务（10 节）：aware UTC、时钟异常、TIME_RATIO_HISTORY 分段积分。

CANONICAL_BLESSED_TICK：世界时间一律为整数 canonical tick（µy，见
domain/blessed_time）；本模块提供按 effective ratio 区间分段积分，
禁止"拿最新 ratio 倒推全部历史"。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from domain.blessed_time import blessed_tick_delta
from domain.errors import ClockAnomaly


def to_utc(dt: datetime) -> datetime:
    """naive 视为 UTC（系统层禁止本地时区串/夏令时）。"""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class RatioSegment:
    """一个 ratio 生效段：real 时间窗 + 倍率（由 TIME_RATIO_HISTORY 切分而来）。"""
    real_start: datetime
    real_end: datetime
    ratio_value: float
    reason: str


def blessed_ticks_over_segments(segments: list[RatioSegment]) -> int:
    """按多个 ratio 生效段分段积分，返回整数 canonical tick 总量。

    - 每段独立用 :func:`blessed_tick_delta` 精确整数换算，总量只做整数加法，
      不存在浮点累计世界时间。
    - 禁止：拿当前 time_ratio 倒推全部过去时间 —— 调用方必须先从
      time_ratio_history 查询 effective-dated 区间并切分为 segments。
    """
    total = 0
    for seg in segments:
        total += blessed_tick_delta(seg.real_start, seg.real_end, seg.ratio_value)
    return total


def check_clock_forward(now: datetime, last_simulated_real_time: datetime | None) -> None:
    """system clock rollback 保护：now < last → CLOCK_ANOMALY。"""
    if last_simulated_real_time is not None and to_utc(now) < to_utc(last_simulated_real_time):
        raise ClockAnomaly(
            "系统时间回拨：now < last_simulated_real_time",
            detail={"now": str(now), "last": str(last_simulated_real_time)})
