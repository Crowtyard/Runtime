"""测试 9-11：Bible 哈希 / WORLD_NOT_ACTIVATED / 时钟异常。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, update

from database.models_core import WorldEvent, WorldRuntime
from domain.errors import ClockAnomaly, WorldBibleHashMismatch, WorldNotActivated
from services.bible_integrity import verify_bible, verify_runtime_binds_bible
from services.guard import create_simulation_event, require_world_activated
from services.repositories import RuntimeRepository, TimeRatioRepository
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


def test_runtime_binds_bible_strict_hash(seeded_session_factory, real_bible_dir):
    """manifest hash 必填且严格相等：空串也视为不一致。"""
    fp = verify_bible(real_bible_dir)
    with seeded_session_factory() as s:
        s.execute(update(WorldRuntime).where(WorldRuntime.world_id == "W").values(
            world_bible_manifest_hash=""))
        s.commit()
        with pytest.raises(WorldBibleHashMismatch):
            verify_runtime_binds_bible(RuntimeRepository(s), fp)


def test_world_not_activated_guard(seeded_session_factory):
    # seeded 行 = NOT_ACTIVATED → 所有推进类操作必须拒绝
    with seeded_session_factory() as s:
        for action in ("advance_world", "simulate_tick", "offline_catchup",
                       "create_world_event_from_simulation"):
            with pytest.raises(WorldNotActivated):
                require_world_activated(s, action)


def test_guard_requires_seed_version(seeded_session_factory):
    """status=ACTIVE 但 world_seed 未生效 → 仍拒绝（激活 = status + seed 双条件）。"""
    with seeded_session_factory() as s:
        row = s.execute(select(WorldRuntime)).scalar_one()
        row.runtime_status = "ACTIVE"
        s.commit()
        with pytest.raises(WorldNotActivated):
            require_world_activated(s, "advance_world")


def test_create_simulation_event_not_activated(seeded_session_factory):
    with seeded_session_factory() as s:
        with pytest.raises(WorldNotActivated):
            create_simulation_event(s, world_id="W", event_type="X",
                                    source="SIM", blessed_tick=1)
        assert s.execute(select(WorldEvent)).scalars().all() == []


def test_create_simulation_event_activated(activated_session_factory):
    with activated_session_factory() as s:
        ev = create_simulation_event(s, world_id="W", event_type="X",
                                     source="SIM", blessed_tick=1)
        s.commit()
        assert ev.event_uid
        assert s.execute(select(WorldEvent)).scalars().all() == [ev]


def test_metadata_creation_does_not_activate(seeded_session_factory):
    """创建 metadata / time rule ≠ 激活世界。"""
    with seeded_session_factory() as s:
        row = RuntimeRepository(s).get()
        assert row.runtime_status == "NOT_ACTIVATED"
        assert row.world_seed_version is None
        assert row.current_blessed_tick is None
        with pytest.raises(WorldNotActivated):
            require_world_activated(s, "advance_world")
        # 自然态 ratio 行 = World Rule 元数据（blessed_effective_from_tick=NULL=未开始计）
        ratios = TimeRatioRepository(s).list_all()
        assert len(ratios) == 1
        assert ratios[0].blessed_effective_from_tick is None
        assert ratios[0].ratio_value == 365.0


def test_clock_anomaly():
    now = datetime.now(timezone.utc)
    with pytest.raises(ClockAnomaly):
        check_clock_forward(now - timedelta(seconds=10), now)


def test_clock_forward_ok():
    last = datetime.now(timezone.utc) - timedelta(hours=1)
    check_clock_forward(last + timedelta(seconds=1), last)
