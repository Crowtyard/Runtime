"""CANONICAL_BLESSED_TICK —— Runtime 唯一世界时间坐标（M0 DSH 独立 QA 接管修正）。

背景：前序实现把 blessed 时间定义为"整数福地年"，无法表达子年事件
（季度/月度演化、灾劫前兆、灾后恢复、资源演替、NPC 人生节点、time-ratio 变更、
adaptive time resolution）。本模块将其替换为整数 canonical tick。

## 单位选择：1 canonical tick = 1 micro-blessed-year（µy，1e-6 福地年）

- 精度：1 µy 远小于所有已知子年需求粒度。自然态 ratio=365（现实 1 天 = 365 福地年）下
  1 tick ≈ 0.24 ms 现实时间；ratio=1 时 1 tick ≈ 86.4 ms 现实时间。
- 溢出安全：64-bit 有符号整数 ≈ 9.22e18 tick = 9.22e12 福地年；
  自然态 ratio 下 ≈ 6.9e7 现实年才溢出。SQLite INTEGER（64-bit affinity）与
  PostgreSQL BIGINT 均原生承载。
- 转换成本：年投影 = tick // TICKS_PER_BLESSED_YEAR（纯整数 div/mod，零浮点）。
- 禁止浮点累计世界时间：canonical 坐标只做整数加法；每段增量由
  :func:`blessed_tick_delta` 用有理数精确整数运算得出，绝不累计浮点。

## 历法 Canon 边界（重要）

- Canonical tick 只是 Runtime 技术时间坐标，不等于任何历法制度。
- World Bible 唯一定义的时间量是"福地年"（WS-0201 natural ratio：现实 1 天 = 365 福地年），
  因此 tick 锚定在"福地年"上，不锚定日/月/季。
- Bible 未定义：一年多少天、月/季制度、纪年纪元年号 → 本模块不发明任何历法。
- year/month/day 只是 projection / display；month/day 的投影在历法 Canon 定义之前
  只以 µy 余数呈现，禁止生成叙事纪年。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

TICKS_PER_BLESSED_YEAR = 1_000_000  # 1 canonical tick = 1 µy（micro-blessed-year）
SECONDS_PER_REAL_DAY = 86_400
MICROS_PER_REAL_DAY = 86_400_000_000
MAX_TICK = (1 << 63) - 1  # SQLite 64-bit INTEGER / PostgreSQL BIGINT 上限
MIN_TICK = -(1 << 63)


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def blessed_tick_delta(real_start: datetime, real_end: datetime,
                       ratio_per_day: float) -> int:
    """一段现实时间 → canonical tick 增量（精确整数运算，确定可复算）。

    ratio 语义（Bible WS-0201）：现实 1 天 = ratio 福地年。

    推导：ticks = µ_real × ratio / 86400（µ_real 为现实微秒数）。
    ratio 以 ``float.as_integer_ratio()`` 精确还原为有理数后全程整数运算，
    结果只做一次整数除法 —— 世界时间坐标永不浮点累计。
    """
    if ratio_per_day <= 0:
        raise ValueError("ratio 必须为正")
    micros = (_to_utc(real_end) - _to_utc(real_start)) // timedelta(microseconds=1)
    if micros <= 0:
        return 0
    p, q = float(ratio_per_day).as_integer_ratio()
    return (micros * p * TICKS_PER_BLESSED_YEAR) // (q * MICROS_PER_REAL_DAY)


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
