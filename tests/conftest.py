"""pytest 共享设施：临时库 + migrations + seeded 世界（FK 前置行）。

所有测试只用 tmp_path 临时库，绝不触碰正式 world.db。

导入约定：核心模块使用插件包内相对导入（部署形态），开发测试统一用
包限定导入 `XiaoguangBlessedLandRuntime.*`（部署时顶层包名为
astrbot_plugin_blessed_land_runtime，包内相对导入与顶层名无关）。
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT.parent))
_PKG_NAME = _PROJECT_ROOT.name
importlib.import_module(_PKG_NAME)

import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from XiaoguangBlessedLandRuntime.config.settings import Settings  # noqa: E402, F401
from XiaoguangBlessedLandRuntime.database.base import utcnow  # noqa: E402
from XiaoguangBlessedLandRuntime.database.db import (  # noqa: E402
    create_db_engine, make_session_factory)
from XiaoguangBlessedLandRuntime.database.models_core import (  # noqa: E402
    WorldRuntime)
from XiaoguangBlessedLandRuntime.domain.blessed_time import (  # noqa: E402
    datetime_to_epoch_us)
from XiaoguangBlessedLandRuntime.domain.constants import RuntimeStatus  # noqa: E402
from XiaoguangBlessedLandRuntime.services.repositories import (  # noqa: E402
    RuntimeRepository, TimeRatioRepository)
from XiaoguangBlessedLandRuntime.services.writer_lock import (  # noqa: E402
    WriterLease)

PROJECT_ROOT = _PROJECT_ROOT
BIBLE_DIR = PROJECT_ROOT.parent / "XIAOGUANG_CROW_KB" / "world_bible"
HEAD_REVISION = "b7d2f4e9c1a5"  # m2b_resource_economy（当前 head）

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


@pytest.fixture(scope="session", autouse=True)
def formal_db_guard():
    """会话级正式库守护：记录 BLR_FORMAL_DB_PATH 的初始 checksum，
    由 zz_formal_db_guard.py 在套件末尾校验（测试全程不得触碰正式库）。"""
    path = os.environ.get("BLR_FORMAL_DB_PATH", "")
    if path and Path(path).exists():
        before = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    else:
        before = None
    yield before
