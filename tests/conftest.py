"""pytest 共享设施：临时库 + migrations + seeded 世界（FK 前置行）。

所有测试只用 tmp_path 临时库，绝不触碰正式 world.db。
"""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from config.settings import Settings  # noqa: F401
from database.base import utcnow
from database.db import create_db_engine, make_session_factory
from database.models_core import WorldRuntime
from domain.blessed_time import datetime_to_epoch_us
from domain.constants import RuntimeStatus
from services.repositories import RuntimeRepository, TimeRatioRepository
from services.writer_lock import WriterLease

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BIBLE_DIR = PROJECT_ROOT.parent / "XIAOGUANG_CROW_KB" / "world_bible"
HEAD_REVISION = "e6c0f4a1b3d9"  # m1_checkpoint_extension_and_interval_unique（当前 head）

EPOCH0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
EPOCH0_US = datetime_to_epoch_us(EPOCH0)
W = "W"  # 测试世界 world_id


def run_migrations(database_url: str) -> None:
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "database" / "alembic"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(cfg, "head")


@pytest.fixture()
def db_url(tmp_path: Path) -> str:
    return "sqlite:///" + str(tmp_path / "test_world.db").replace("\\", "/")


@pytest.fixture()
def migrated_db(db_url: str):
    run_migrations(db_url)
    engine = create_db_engine(db_url)
    factory = make_session_factory(engine)
    return {"url": db_url, "engine": engine, "factory": factory}


@pytest.fixture()
def session_factory(migrated_db):
    return migrated_db["factory"]


@pytest.fixture()
def seeded_session_factory(session_factory):
    """播种 world_runtime(NOT_ACTIVATED) + 自然态速率——FK 前置（不做任何推进）。"""
    with session_factory() as s:
        RuntimeRepository(s).create_not_activated(
            world_id="W", world_bible_version="1.0",
            simulation_version="0.1.0-dev", world_bible_manifest_hash="testhash")
        TimeRatioRepository(s).add(world_id="W",
                                   real_effective_from=utcnow(),
                                   rate_numerator=1_000_000,
                                   rate_denominator=86_400_000_000,
                                   reason="TEST", source="TEST")
        s.commit()
    return session_factory


@pytest.fixture()
def activated_session_factory(seeded_session_factory):
    """测试专用：把世界置为 ACTIVE（仅测试库；正式库必须保持 NOT_ACTIVATED）。"""
    with seeded_session_factory() as s:
        row = s.execute(select(WorldRuntime)).scalar_one()
        row.runtime_status = RuntimeStatus.ACTIVE
        row.world_seed_version = "SEED-TEST-1"
        row.current_blessed_tick = 0
        s.commit()
    return seeded_session_factory


@pytest.fixture()
def active_clock_factory(seeded_session_factory):
    """测试专用 ACTIVATED 世界 + 已初始化时钟：
    tick=0、现实游标=EPOCH0、自然态速率边界=EPOCH0、remainder=0。
    （catch_up 的全部前置状态；正式库绝不进入该状态。）"""
    with seeded_session_factory() as s:
        row = s.execute(select(WorldRuntime)).scalar_one()
        row.runtime_status = RuntimeStatus.ACTIVE
        row.world_seed_version = "SEED-TEST-1"
        row.current_blessed_tick = 0
        row.last_committed_real_us = EPOCH0_US
        row.time_rate_remainder = 0
        rate = TimeRatioRepository(s).list_all()[0]
        rate.real_effective_from = EPOCH0
        rate.real_effective_from_us = EPOCH0_US
        row.current_time_ratio_id = rate.ratio_id
        s.commit()
    return seeded_session_factory


@pytest.fixture()
def lease_helper(active_clock_factory):
    """acquire 一个 WriterLease，返回 (session, lease)（测试用 fencing 凭据来源）。"""
    def _acquire(seconds: int = 120):
        s = active_clock_factory()
        lease = WriterLease(s, W, seconds)
        lease.acquire()
        return s, lease
    return _acquire


@pytest.fixture()
def real_bible_dir() -> Path:
    return BIBLE_DIR


@pytest.fixture()
def fake_bible_dir(tmp_path: Path) -> Path:
    d = tmp_path / "bible"
    shutil.copytree(BIBLE_DIR, d)
    return d


def manifest_hash_of(bible_dir: Path) -> str:
    entries = []
    for line in (bible_dir / "MANIFEST.sha256.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        h, name = line.split("  ", 1)
        entries.append((name, h))
    return hashlib.sha256(
        json.dumps(sorted(entries), ensure_ascii=False).encode("utf-8")).hexdigest()
