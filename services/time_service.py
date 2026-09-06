"""时间基础服务（10 节）：UTC 统一、时钟异常、倍率区间分段接口（不做补算执行）。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from domain.errors import ClockAnomaly

SECONDS_PER_REAL_DAY = 86400


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


def blessed_years_for_real_seconds(real_seconds: float, ratio_per_day: float) -> float:
    """现实秒 → 福地年（浮点；M1 落整数刻度前使用）。

    ratio_per_day 语义：现实 1 天 = ratio 福地年（Bible WS-0201 自然态=365）。
    """
    if ratio_per_day <= 0:
        raise ValueError("ratio 必须为正")
    return real_seconds / SECONDS_PER_REAL_DAY * ratio_per_day


def check_clock_forward(now: datetime, last_simulated_real_time: datetime | None) -> None:
    """system clock rollback 保护：now < last → CLOCK_ANOMALY。"""
    if last_simulated_real_time is not None and to_utc(now) < to_utc(last_simulated_real_time):
        raise ClockAnomaly(
            "系统时间回拨：now < last_simulated_real_time",
            detail={"now": str(now), "last": str(last_simulated_real_time)})


def blessed_elapsed_over_segments(segments: list[RatioSegment]) -> float:
    """按多个 ratio 生效段分段积分（9 节 TIME_RATIO_HISTORY）。

    禁止：拿当前 time_ratio 倒推全部过去时间——调用方必须先从
    time_ratio_history 查询 effective-dated 区间并切分为 segments。
    """
    total = 0.0
    for seg in segments:
        seconds = (to_utc(seg.real_end) - to_utc(seg.real_start)).total_seconds()
        if seconds <= 0:
            continue
        total += blessed_years_for_real_seconds(seconds, seg.ratio_value)
    return total
