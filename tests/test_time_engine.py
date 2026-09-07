"""BLESSED TIME ENGINE 测试（M1）：整数有理积分、同速率进位、跨速率重置、分段。"""
from __future__ import annotations

import random
from fractions import Fraction

import pytest

from XiaoguangBlessedLandRuntime.domain.blessed_time import NATURAL_TIME_RATE, TimeRate
from XiaoguangBlessedLandRuntime.domain.errors import IntegrityError
from XiaoguangBlessedLandRuntime.services.time_engine import Integrator, RateWindow, rate_at, segment_interval

DAY_US = 86_400_000_000
HALF = TimeRate(blessed_ticks=500_000, real_micros=86_400_000_000)
RATE_C = TimeRate(blessed_ticks=2_000_000, real_micros=86_400_000_000)
RATE_D = TimeRate(blessed_ticks=250_000, real_micros=86_400_000_000)


def test_30_days_natural():
    it = Integrator()
    it.add_segment(0, 30 * DAY_US, NATURAL_TIME_RATE)
    assert it.total_ticks == 30_000_000
    assert it.remainder == 0


def test_365_days_natural():
    it = Integrator()
    it.add_segment(0, 365 * DAY_US, NATURAL_TIME_RATE)
    assert it.total_ticks == 365_000_000


def test_1s_x_86400_equals_1_day():
    """1 秒 × 86,400 次 == 1 天一次推进（同速率余数进位，无累计 drift）。"""
    whole = Integrator()
    whole.add_segment(0, DAY_US, NATURAL_TIME_RATE)
    chunks = Integrator()
    for i in range(86_400):
        chunks.add_segment(i * 1_000_000, (i + 1) * 1_000_000, NATURAL_TIME_RATE)
    assert chunks.total_ticks == whole.total_ticks == 1_000_000


def test_first_1s_chunk_delta_and_remainder():
    it = Integrator()
    delta = it.add_segment(0, 1_000_000, NATURAL_TIME_RATE)
    assert delta == 11
    assert it.remainder == 49_600_000_000  # 1e12 - 11 × 8.64e10


def test_random_chunks_equal_whole():
    """随机切成 N 个现实时间块（同速率）== 一次整体推进。"""
    rng = random.Random(0)
    cuts = sorted(rng.sample(range(1, 30 * DAY_US), 500))
    bounds = [0, *cuts, 30 * DAY_US]
    whole = Integrator()
    whole.add_segment(0, 30 * DAY_US, NATURAL_TIME_RATE)
    chunks = Integrator()
    for a, b in zip(bounds, bounds[1:]):
        chunks.add_segment(a, b, NATURAL_TIME_RATE)
    assert chunks.total_ticks == whole.total_ticks == 30_000_000


def test_cross_rate_remainder_reset():
    """跨速率：旧 remainder 不泄漏（泄漏时 delta=6，重置时 delta=5）。"""
    it = Integrator()
    it.add_segment(0, 1_000_000, NATURAL_TIME_RATE)  # remainder = 49,600,000,000
    delta = it.add_segment(1_000_000, 2_000_000, HALF)
    assert delta == 5
    assert it.remainder == 5 * 10**11 % 86_400_000_000


def test_four_rate_segmentation_matches_fraction_oracle():
    """A→B→C→D 四个速率区间分段计算 == 人工 Fraction oracle。"""
    windows = [
        RateWindow(0, NATURAL_TIME_RATE, 1, "A"),
        RateWindow(DAY_US, HALF, 2, "B"),
        RateWindow(2 * DAY_US, RATE_C, 3, "C"),
        RateWindow(3 * DAY_US, RATE_D, 4, "D"),
    ]
    slices = segment_interval(windows, 0, 4 * DAY_US)
    assert len(slices) == 4
    oracle = sum(Fraction((sl.real_end_us - sl.real_start_us) * sl.rate.blessed_ticks,
                          sl.rate.real_micros) for sl in slices)
    it = Integrator()
    for sl in slices:
        it.add_segment(sl.real_start_us, sl.real_end_us, sl.rate, sl.ratio_id)
    assert it.total_ticks == int(oracle)
    assert it.total_ticks == 1_000_000 + 500_000 + 2_000_000 + 250_000


def test_rate_at_boundaries_and_gap():
    windows = [RateWindow(0, NATURAL_TIME_RATE, 1, "A"),
               RateWindow(DAY_US, HALF, 2, "B")]
    assert rate_at(windows, 0) == (NATURAL_TIME_RATE, 1)
    assert rate_at(windows, DAY_US - 1) == (NATURAL_TIME_RATE, 1)
    assert rate_at(windows, DAY_US) == (HALF, 2)
    with pytest.raises(IntegrityError):
        rate_at([RateWindow(10, NATURAL_TIME_RATE, 1, "A")], 5)


def test_empty_and_reversed_segments():
    it = Integrator()
    assert it.add_segment(10, 10, NATURAL_TIME_RATE) == 0
    assert it.add_segment(20, 10, NATURAL_TIME_RATE) == 0
    assert it.total_ticks == 0
    assert segment_interval([], 10, 5) == []
    # 无速率 Canon 的时间区间拒绝积分（不发明历史速率）
    with pytest.raises(IntegrityError):
        segment_interval([], 0, 10)
