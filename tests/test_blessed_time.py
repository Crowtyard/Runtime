"""CANONICAL_BLESSED_TICK + 有量纲有理速率测试（TIME_MODEL_UNIT_BLOCKER 修正后）。

量纲：tick = µy；µ_real = 现实微秒；速率 = blessed ticks / real µs。
舍入政策：floor；同一速率连续分段共享余数进位（无累计 drift）；跨速率进位重置。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from fractions import Fraction

import pytest

from domain.blessed_time import (MAX_TICK, NATURAL_TIME_RATE, TICKS_PER_BLESSED_YEAR,
                                 TimeRate, blessed_subyear_tick, blessed_tick_delta,
                                 blessed_year_index, blessed_years_per_real_day,
                                 format_blessed_tick)
from services.time_service import RateSegment, blessed_ticks_over_segments

DAY = timedelta(days=1)
HOUR = timedelta(hours=1)
START = datetime(2026, 9, 6, tzinfo=timezone.utc)

# 测试用第二速率：现实 1 天 → 半福地年（500,000 ticks / 86,400,000,000 µs）
HALF = TimeRate(blessed_ticks=500_000, real_micros=86_400_000_000)


def test_one_real_day_is_one_million_ticks():
    """量纲核心：24 real hours → 1,000,000 blessed ticks（1 现实天 = 1 福地年）。"""
    assert blessed_tick_delta(START, START + DAY, NATURAL_TIME_RATE) == 1_000_000


def test_three_real_days_three_million_ticks():
    assert blessed_tick_delta(START, START + 3 * DAY, NATURAL_TIME_RATE) == 3_000_000


def test_twelve_real_hours_half_million_ticks():
    assert blessed_tick_delta(START, START + 12 * HOUR, NATURAL_TIME_RATE) == 500_000


def test_one_real_hour_floor_rounding_policy():
    """1 real hour → 41,666 µy（精确值 41,666.666…，舍入政策 = 向下取整 floor）。

    41,666 µy ≈ 0.0417 福地年，是正确子年刻度（Bible：现实 1 小时≈福地 15 天
    的口径在历法 Canon 定义前不进入核心计算）。
    """
    assert blessed_tick_delta(START, START + HOUR, NATURAL_TIME_RATE) == 41_666


def test_24_x_1h_equals_1_x_24h_no_drift():
    """分段求和与整段计算完全一致（同一速率共享余数进位，无累计 drift）。"""
    whole = blessed_tick_delta(START, START + DAY, NATURAL_TIME_RATE)
    pieces = [RateSegment(START + i * HOUR, START + (i + 1) * HOUR,
                          NATURAL_TIME_RATE, "natural")
              for i in range(24)]
    assert blessed_ticks_over_segments(pieces) == whole == 1_000_000


def test_carry_within_same_rate():
    """同一速率两段 1h：进位使结果等于整 2h 的精确 floor（83,333），
    而非逐段 floor 相加（83,332）。"""
    segs = [RateSegment(START, START + HOUR, NATURAL_TIME_RATE, "n"),
            RateSegment(START + HOUR, START + 2 * HOUR, NATURAL_TIME_RATE, "n")]
    assert blessed_ticks_over_segments(segs) == 83_333


def test_12h_rate_a_plus_12h_rate_b_segmented():
    """12h 自然态 + 12h 半速：必须严格按两段速率积分（750,000 ticks）。"""
    seg_a = RateSegment(START, START + 12 * HOUR, NATURAL_TIME_RATE, "A")
    seg_b = RateSegment(START + 12 * HOUR, START + DAY, HALF, "B")
    total = blessed_ticks_over_segments([seg_a, seg_b])
    assert total == 750_000
    # 禁止拿最新速率倒推历史：整段按 B 计算 = 500,000 ≠ 750,000
    wrong = blessed_ticks_over_segments(
        [RateSegment(START, START + DAY, HALF, "wrong-backdate")])
    assert wrong == 500_000
    assert wrong != total


def test_carry_resets_across_rate_change():
    """跨速率分段进位重置（余数量纲随速率变化，不得跨速率传递）。"""
    segs = [RateSegment(START, START + HOUR, NATURAL_TIME_RATE, "A"),
            RateSegment(START + HOUR, START + 2 * HOUR, HALF, "B")]
    # 自然态 1h = 41,666；半速 1h = 20,833；无跨速率进位 → 62,499
    assert blessed_ticks_over_segments(segs) == 41_666 + 20_833


def test_rate_display_derived_only():
    """派生展示：自然态 = 1 现实天 / 1 福地年（Fraction(1,1)）；仅 display/审计。"""
    assert blessed_years_per_real_day(NATURAL_TIME_RATE) == Fraction(1, 1)
    assert blessed_years_per_real_day(HALF) == Fraction(1, 2)


def test_rate_validation():
    with pytest.raises(ValueError):
        TimeRate(0, 1)
    with pytest.raises(ValueError):
        TimeRate(1, 0)
    with pytest.raises(ValueError):
        TimeRate(-1, 1)
    with pytest.raises(ValueError):
        TimeRate(1, -1)
    with pytest.raises(ValueError):
        TimeRate(1.0, 1)  # 禁止 float 分子


def test_naive_and_aware_mixed_inputs_normalized():
    naive = datetime(2026, 9, 6, 0, 0, 0)
    aware = datetime(2026, 9, 7, 0, 0, 0, tzinfo=timezone.utc)
    assert blessed_tick_delta(naive, aware, NATURAL_TIME_RATE) == 1_000_000


def test_zero_or_reversed_range():
    assert blessed_tick_delta(START, START, NATURAL_TIME_RATE) == 0
    assert blessed_tick_delta(START + DAY, START, NATURAL_TIME_RATE) == 0


def test_projection_year_and_subyear():
    tick = 3 * TICKS_PER_BLESSED_YEAR + 250_000
    assert blessed_year_index(tick) == 3
    assert blessed_subyear_tick(tick) == 250_000
    assert format_blessed_tick(tick) == "3y+250000µy"
    assert format_blessed_tick(None) == "NULL"


def test_overflow_headroom():
    """64-bit tick ≈ 9.2e12 福地年；自然态下 ≈ 9.2e12 现实天才溢出（≈2.5e10 现实年）。"""
    assert MAX_TICK // TICKS_PER_BLESSED_YEAR > 1_000_000_000_000
