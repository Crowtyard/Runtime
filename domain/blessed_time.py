"""CANONICAL_BLESSED_TICK + 有量纲有理速率（M0 DSH TIME_MODEL_UNIT_BLOCKER 修正）。

## 时间单位定义（量纲明确）

- 世界时间坐标：整数 canonical tick。**1 tick = 1 micro-blessed-year（µy，
  1e-6 福地年）**。年/月/日只是 projection；禁止浮点累计世界时间。
- 现实时间：aware UTC；增量以**整数微秒（µs）**计算。

## 自然态速率定义（Bible WS-0201）

- Canon 原文：**现实约 1 天 ≈ 福地约 1 年（约 365 倍）**。
- Runtime 正式速率 = 有量纲有理速率（禁止 float 作长期世界规则真值）：

  ```
  NATURAL_TIME_RATE = 1,000,000 blessed ticks / 86,400,000,000 real µs
  ```

  即：现实 86,400,000,000 µs（= 1 现实天）→ 1,000,000 ticks（= 1 福地年）。
  "约 365 倍"仅作为 Bible 原文的派生展示语，不进入核心计算、不入库。

## 转换公式（单位推导）

  ticks = (µ_real × rate_numerator) // rate_denominator

- µ_real 单位：real microseconds（µs）
- rate_numerator 单位：blessed ticks
- rate_denominator 单位：real microseconds（µs）
- 结果单位：blessed ticks
- 量纲校验：(µs × ticks) / µs = ticks ✓
- 舍入政策：整数向下取整（floor）；同一速率的连续分段共享余数进位
  （有理精确累加，无累计 drift）；跨速率分段进位重置（量纲不同不得跨速率传递）。
- 禁止 float.as_integer_ratio() 保存长期世界时间规则；速率真值从数据库起就是
  INTEGER numerator + INTEGER denominator（可审计、可复现、无浮点漂移）。

## 历法 Canon 边界（不变）

- tick 只锚定 Bible 唯一定义的时间量"福地年"；Bible 未定义一年多少天/月制/纪年，
  本模块不发明任何历法；year 只是算术投影，禁止生成叙事纪年。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from fractions import Fraction

TICKS_PER_BLESSED_YEAR = 1_000_000  # 1 canonical tick = 1 µy（micro-blessed-year）
SECONDS_PER_REAL_DAY = 86_400
MICROS_PER_REAL_DAY = 86_400_000_000
MAX_TICK = (1 << 63) - 1  # SQLite 64-bit INTEGER / PostgreSQL BIGINT 上限
MIN_TICK = -(1 << 63)


@dataclass(frozen=True)
class TimeRate:
    """有量纲有理速率：blessed_ticks / real_micros（tick 每现实微秒）。

    - 不做自动约分：入库值即真值，保持可审计。
    - 自然态 = TimeRate(1_000_000, 86_400_000_000) = NATURAL_TIME_RATE。
    """
    blessed_ticks: int  # 分子：blessed ticks
    real_micros: int    # 分母：real microseconds

    def __post_init__(self) -> None:
        if not isinstance(self.blessed_ticks, int) or not isinstance(self.real_micros, int) \
                or isinstance(self.blessed_ticks, bool) or isinstance(self.real_micros, bool):
            raise ValueError("TimeRate 分子/分母必须为整数")
        if self.blessed_ticks <= 0 or self.real_micros <= 0:
            raise ValueError("TimeRate 分子/分母必须为正整数")


NATURAL_TIME_RATE = TimeRate(
    blessed_ticks=1_000_000,          # 1 福地年 = 1,000,000 ticks
    real_micros=86_400_000_000,       # 1 现实天 = 86,400,000,000 µs
)


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def real_micros_between(real_start: datetime, real_end: datetime) -> int:
    """现实时间跨度 → 整数微秒（负/零跨度的结果为 0）。"""
    micros = (_to_utc(real_end) - _to_utc(real_start)) // timedelta(microseconds=1)
    return micros if micros > 0 else 0


def blessed_tick_delta(real_start: datetime, real_end: datetime,
                       rate: TimeRate) -> int:
    """一段现实时间 → canonical tick 增量（纯整数、向下取整、确定可复算）。

    公式：ticks = (µ_real × rate.blessed_ticks) // rate.real_micros
    µ_real [µs]；rate 为 ticks/µs 有理速率；结果 [ticks]。全程无浮点。
    """
    micros = real_micros_between(real_start, real_end)
    return (micros * rate.blessed_ticks) // rate.real_micros


def blessed_years_per_real_day(rate: TimeRate) -> Fraction:
    """派生展示（仅 display/审计，不参与核心计算）：1 现实天 = 多少福地年。

    推导：ticks/天 = num/den × 86,400,000,000；福地年/天 = ticks/天 ÷ 1,000,000。
    自然态 = Fraction(1, 1)（即 Canon"现实约 1 天 ≈ 福地约 1 年"）。
    """
    return Fraction(rate.blessed_ticks * MICROS_PER_REAL_DAY,
                    rate.real_micros * TICKS_PER_BLESSED_YEAR)


def blessed_year_index(tick: int) -> int:
    """算术投影：tick 所在的福地年序号（0 基）。仅 display 用途，非叙事纪年。"""
    return tick // TICKS_PER_BLESSED_YEAR


def blessed_subyear_tick(tick: int) -> int:
    """算术投影：福地年内的 µy 余数（0 .. TICKS_PER_BLESSED_YEAR-1）。"""
    return tick % TICKS_PER_BLESSED_YEAR


def format_blessed_tick(tick: int | None) -> str:
    """技术坐标渲染（非历法）：如 365250000 → \"365y+250000µy\"。"""
    if tick is None:
        return "NULL"
    y, r = divmod(tick, TICKS_PER_BLESSED_YEAR)
    return f"{y}y+{r:06d}µy"
