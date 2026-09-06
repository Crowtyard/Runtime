"""CANONICAL_BLESSED_TICK 单元测试：精度/换算/投影/分段积分/溢出。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from domain.blessed_time import (MAX_TICK, TICKS_PER_BLESSED_YEAR,
                                 blessed_subyear_tick, blessed_tick_delta,
                                 blessed_year_index, format_blessed_tick)
from services.time_service import RatioSegment, blessed_ticks_over_segments

DAY = timedelta(days=1)
HOUR = timedelta(hours=1)


def test_one_real_day_natural_ratio_exact():
    """自然态 ratio=365：现实 1 天 = 365 福地年 = 365,000,000 tick（精确整数）。"""
    start = datetime(2026, 9, 6, tzinfo=timezone.utc)
    assert blessed_tick_delta(start, start + DAY, 365.0) == 365 * TICKS_PER_BLESSED_YEAR


def test_sub_year_resolution():
    """子年分辨率：ratio=1（现实 1 天 = 1 福地年）下 1 现实小时 = 41,666 µy，
    远小于 1/4 年（250,000 µy）—— 季度/月度/灾劫前兆/人生节点均可表达。

    注：自然态 ratio=365 下 1 现实小时 = 15.2 福地年，那是 ratio 语义使然，
    不是 tick 分辨率问题。
    """
    start = datetime(2026, 9, 6, tzinfo=timezone.utc)
    delta = blessed_tick_delta(start, start + HOUR, 1.0)
    assert delta == TICKS_PER_BLESSED_YEAR // 24
    assert 0 < delta < TICKS_PER_BLESSED_YEAR // 4


def test_ratio_change_segmented_integration():
    """ratio 变更必须按 effective interval 分段积分，禁止拿最新 ratio 倒推历史。"""
    start = datetime(2026, 9, 6, tzinfo=timezone.utc)
    seg_a = RatioSegment(start, start + DAY, 365.0, "A")
    seg_b = RatioSegment(start + DAY, start + 2 * DAY, 100.0, "B")
    total = blessed_ticks_over_segments([seg_a, seg_b])
    assert total == (365 + 100) * TICKS_PER_BLESSED_YEAR
    # 错误用法（单段最新 ratio 倒推全史）得到不同结果 → 证明分段是实质计算
    wrong = blessed_ticks_over_segments(
        [RatioSegment(start, start + 2 * DAY, 100.0, "wrong")])
    assert wrong != total


def test_deterministic_integer_no_float_accumulation():
    start = datetime(2026, 9, 6, tzinfo=timezone.utc)
    segs = [RatioSegment(start + i * HOUR, start + (i + 1) * HOUR, 365.0, "n")
            for i in range(100)]
    a = blessed_ticks_over_segments(segs)
    b = blessed_ticks_over_segments(segs)
    assert isinstance(a, int)
    assert a == b


def test_naive_and_aware_mixed_inputs_normalized():
    naive = datetime(2026, 9, 6, 0, 0, 0)
    aware = datetime(2026, 9, 7, 0, 0, 0, tzinfo=timezone.utc)
    assert blessed_tick_delta(naive, aware, 1.0) == TICKS_PER_BLESSED_YEAR


def test_projection_year_and_subyear():
    tick = 3 * TICKS_PER_BLESSED_YEAR + 250_000
    assert blessed_year_index(tick) == 3
    assert blessed_subyear_tick(tick) == 250_000
    assert format_blessed_tick(tick) == "3y+250000µy"
    assert format_blessed_tick(None) == "NULL"


def test_zero_or_reversed_range():
    start = datetime(2026, 9, 6, tzinfo=timezone.utc)
    assert blessed_tick_delta(start, start, 365.0) == 0
    assert blessed_tick_delta(start + DAY, start, 365.0) == 0


def test_ratio_must_be_positive():
    start = datetime(2026, 9, 6, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        blessed_tick_delta(start, start + DAY, 0.0)
    with pytest.raises(ValueError):
        blessed_tick_delta(start, start + DAY, -365.0)


def test_overflow_headroom():
    """64-bit tick ≈ 9.2e12 福地年；自然态 ratio 下 ≈ 6.9e7 现实年才溢出。"""
    assert MAX_TICK // TICKS_PER_BLESSED_YEAR > 1_000_000_000_000
