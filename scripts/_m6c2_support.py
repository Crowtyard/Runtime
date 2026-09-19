"""M6C.2 — shared temp-DB helper for materializer verification (TEST ONLY)."""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

EPOCH0_US = 1_767_225_600_000_000
SIMULATION_VERSION = "0.3.0"


def build_empty_world(work: pathlib.Path, world_id: str) -> dict:
    """temp SQLite + runtime row（ACTIVE）+ canonical rate row；**不写 bootstrap row**。"""
    from datetime import datetime, timezone

    from sqlalchemy import select

    from XiaoguangBlessedLandRuntime.database.db import (
        create_db_engine, make_session_factory)
    from XiaoguangBlessedLandRuntime.database.models_core import WorldRuntime
    from XiaoguangBlessedLandRuntime.domain.constants import RuntimeStatus
    from XiaoguangBlessedLandRuntime.services.db_lifecycle import migrate_database
    from XiaoguangBlessedLandRuntime.services.repositories import (
        RuntimeRepository, TimeRatioRepository)

    work.mkdir(parents=True, exist_ok=True)
    db_path = work / "m6c2_world.db"
    url = "sqlite:///" + str(db_path).replace("\\", "/")
    migrate_database(url, project_root=ROOT)
    factory = make_session_factory(create_db_engine(url))
    with factory() as session:
        RuntimeRepository(session).create_not_activated(
            world_id=world_id, world_bible_version="1.0",
            simulation_version=SIMULATION_VERSION,
            world_bible_manifest_hash="m6c2-verification")
        row = session.execute(select(WorldRuntime)).scalar_one()
        row.runtime_status = RuntimeStatus.ACTIVE
        row.world_seed_version = "SYNTHETIC-M6C2-SEED"
        row.current_blessed_tick = 0
        row.last_committed_real_us = EPOCH0_US
        row.time_rate_remainder = 0
        rate = TimeRatioRepository(session).add(
            world_id=world_id,
            real_effective_from=datetime.fromtimestamp(
                EPOCH0_US / 1_000_000, tz=timezone.utc),
            rate_numerator=1_000_000, rate_denominator=86_400_000_000,
            reason="TEST", source="TEST")
        row.current_time_ratio_id = rate.ratio_id
        session.commit()
    return {"url": url, "factory": factory, "db_path": db_path}
