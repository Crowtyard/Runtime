"""测试 9-11：Bible 哈希 / WORLD_NOT_ACTIVATED / 时钟异常。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import update

from database.models_core import WorldRuntime
from domain.errors import ClockAnomaly, WorldBibleHashMismatch, WorldNotActivated
from services.bible_integrity import verify_bible, verify_runtime_binds_bible
from services.guard import require_world_activated
from services.repositories import RuntimeRepository
from services.time_service import check_clock_forward


def test_bible_integrity_ok(real_bible_dir):
    fp = verify_bible(real_bible_dir)
    assert fp.version == "1.0"


def test_bible_integrity_mismatch_detected(fake_bible_dir):
    target = fake_bible_dir / "14_glossary.md"
    target.write_text(target.read_text(encoding="utf-8") + "\n# tampered\n",
                      encoding="utf-8")
    with pytest.raises(WorldBibleHashMismatch):
        verify_bible(fake_bible_dir)


def test_runtime_binds_bible(seeded_session_factory, real_bible_dir):
    fp = verify_bible(real_bible_dir)
    with seeded_session_factory() as s:
        s.execute(update(WorldRuntime).where(WorldRuntime.world_id == "W").values(
            world_bible_manifest_hash=fp.manifest_hex))
        s.commit()
        verify_runtime_binds_bible(RuntimeRepository(s), fp)


def test_world_not_activated_guard(seeded_session_factory):
    # seeded 行 = NOT_ACTIVATED → 所有推进类操作必须拒绝
    with seeded_session_factory() as s:
        for action in ("advance_world", "simulate_tick", "offline_catchup",
                       "create_world_event_from_simulation"):
            with pytest.raises(WorldNotActivated):
                require_world_activated(s, action)


def test_clock_anomaly():
    now = datetime.now(timezone.utc)
    with pytest.raises(ClockAnomaly):
        check_clock_forward(now - timedelta(seconds=10), now)


def test_clock_forward_ok():
    last = datetime.now(timezone.utc) - timedelta(hours=1)
    check_clock_forward(last + timedelta(seconds=1), last)
