"""Real Time UTC 审计测试：aware UTC 边界、显式 ISO-8601 存储、旧数据兼容。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text

from database.base import utcnow
from database.models_core import WorldRuntime


def test_utcnow_is_aware():
    assert utcnow().tzinfo == timezone.utc
    assert utcnow().utcoffset() == timedelta(0)


def test_utc_columns_store_explicit_iso8601(migrated_db, seeded_session_factory):
    """新写入的现实时间在 DB 层为显式 ISO-8601 UTC（+00:00 后缀）。"""
    with migrated_db["engine"].connect() as c:
        raw = c.execute(text("SELECT created_at FROM world_runtime")).scalar()
    assert isinstance(raw, str)
    assert raw.endswith("+00:00")


def test_offset_input_normalized_to_utc(seeded_session_factory):
    """带 +08:00 的输入入库前归一化为 UTC（不受机器本地时区/DST 影响）。"""
    local = datetime(2026, 1, 1, 8, 0, 0, tzinfo=timezone(timedelta(hours=8)))
    with seeded_session_factory() as s:
        row = s.execute(select(WorldRuntime)).scalar_one()
        row.last_simulated_real_time = local
        s.commit()
    with seeded_session_factory() as s2:
        row2 = s2.execute(select(WorldRuntime)).scalar_one()
        assert row2.last_simulated_real_time == datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_naive_input_treated_as_utc(seeded_session_factory):
    """naive 输入按 UTC 解释（与旧 naive-UTC 数据兼容）。"""
    naive = datetime(2026, 2, 2, 12, 0, 0)
    with seeded_session_factory() as s:
        row = s.execute(select(WorldRuntime)).scalar_one()
        row.last_simulated_real_time = naive
        s.commit()
    with seeded_session_factory() as s2:
        row2 = s2.execute(select(WorldRuntime)).scalar_one()
        assert row2.last_simulated_real_time == naive.replace(tzinfo=timezone.utc)


def test_legacy_naive_row_reads_as_aware_utc(seeded_session_factory):
    """旧格式行（无 offset 后缀）读回仍为 aware UTC（boundary normalization）。"""
    with seeded_session_factory() as s:
        s.execute(text(
            "UPDATE world_runtime SET created_at = '2026-01-01 00:00:00.000000'"))
        s.commit()
    with seeded_session_factory() as s2:
        row = s2.execute(select(WorldRuntime)).scalar_one()
        assert row.created_at.tzinfo == timezone.utc
        assert row.created_at == datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_aware_roundtrip_preserves_instant(seeded_session_factory):
    dt = datetime(2026, 3, 3, 3, 3, 3, 333333, tzinfo=timezone.utc)
    with seeded_session_factory() as s:
        row = s.execute(select(WorldRuntime)).scalar_one()
        row.last_simulated_real_time = dt
        s.commit()
    with seeded_session_factory() as s2:
        row2 = s2.execute(select(WorldRuntime)).scalar_one()
        assert row2.last_simulated_real_time == dt
