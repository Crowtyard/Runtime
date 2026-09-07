"""BLESSED TIME ENGINE（M1）：整数有理时间推进核心。

换算核心（与 M0 量纲完全一致）：
    delta     = (real_us × rate_numerator + remainder) // rate_denominator
    remainder = (real_us × rate_numerator + remainder) % rate_denominator

- 全流程整数运算，无 float 时间真值。
- 同一 rate interval 内保持 remainder（无累计 drift）；
  rate 改变时旧 remainder 不跨 rate 泄漏（余数量纲随速率变化）。
- 支持非常长的 Offline Catch-up（任意多分段，O(n) 整数运算）。
- 支持把现实区间按 time_ratio_history 的整数真实时间边界分段
  （禁止用当前速率倒推历史）。

TIME ENGINE 不知道人口/NPC/灾劫：本模块只做时间数学与分段。
"""
from __future__ import annotations

from dataclasses import dataclass

from ..domain.blessed_time import TimeRate
from ..domain.errors import IntegrityError


@dataclass(frozen=True)
class RateWindow:
    """time_ratio_history 中的一条速率窗口（真实时间整数边界）。"""
    real_effective_from_us: int
    rate: TimeRate
    ratio_id: int
    reason: str


@dataclass(frozen=True)
class RateSlice:
    """[real_start_us, real_end_us) 与生效速率的切片。"""
    real_start_us: int
    real_end_us: int
    rate: TimeRate
    ratio_id: int


class Integrator:
    """分段累加器：同 rate 保持 remainder；rate 改变 remainder 归零。

    持久化契约：remainder 必须与 rate 绑定 —— 恢复时若当前速率与持久化
    remainder 所属速率不一致，调用方必须丢弃 remainder（见 services/catchup.py）。
    """

    def __init__(self, *, remainder: int = 0, rate: TimeRate | None = None,
                 ratio_id: int | None = None):
        self.remainder = remainder
        self.rate = rate
        self.ratio_id = ratio_id
        self.total_ticks = 0
        self.elapsed_real_us = 0

    def add_segment(self, real_start_us: int, real_end_us: int,
                    rate: TimeRate, ratio_id: int | None = None) -> int:
        """累加一段 [start, end)：返回本段 tick 增量。"""
        if real_end_us <= real_start_us:
            return 0
        if rate != self.rate:
            self.remainder = 0  # 跨 rate：旧余数不得泄漏
            self.rate = rate
            self.ratio_id = ratio_id
        us = real_end_us - real_start_us
        self.elapsed_real_us += us
        carry = self.remainder + us * rate.blessed_ticks
        delta = carry // rate.real_micros
        self.remainder = carry % rate.real_micros
        self.total_ticks += delta
        return delta


def rate_at(windows: list[RateWindow], real_us: int) -> tuple[TimeRate, int]:
    """real_us 时刻生效的 (rate, ratio_id)。windows 必须按 effective 升序。

    无任何窗口覆盖（早于第一条速率边界）→ IntegrityError：没有速率 Canon 的时间
    不允许积分（不发明历史速率）。
    """
    hit: RateWindow | None = None
    for w in windows:
        if w.real_effective_from_us <= real_us:
            hit = w
        else:
            break
    if hit is None:
        raise IntegrityError("rate history 未覆盖该现实时间", detail=real_us)
    return hit.rate, hit.ratio_id


def segment_interval(windows: list[RateWindow], real_start_us: int,
                     real_end_us: int) -> list[RateSlice]:
    """把 [start, end) 按速率窗口边界切分为若干 RateSlice。

    例：A 生效于 T0，B 生效于 T1（T0 < T1 < T2）：
    segment(T0, T2) → [T0,T1,A] + [T1,T2,B]。多个区间同理（A→B→C→D）。
    """
    if real_end_us <= real_start_us:
        return []
    boundaries = {real_start_us, real_end_us}
    for w in windows:
        if real_start_us < w.real_effective_from_us < real_end_us:
            boundaries.add(w.real_effective_from_us)
    ordered = sorted(boundaries)
    slices: list[RateSlice] = []
    for a, b in zip(ordered, ordered[1:]):
        rate, rid = rate_at(windows, a)
        slices.append(RateSlice(real_start_us=a, real_end_us=b, rate=rate,
                                ratio_id=rid))
    return slices
