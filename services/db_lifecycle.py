# -*- coding: utf-8 -*-
"""DB 生命周期助手（供 scripts/init_db.py 与 plugin_shell/runtime_host.py 复用）。

- migrate_database：alembic upgrade head（幂等；不 squash、不 reset 历史）。
- seed_database：播种 world_runtime(NOT_ACTIVATED) + 自然态速率行（绝不激活世界）。
- sync_runtime_schema_version：把 runtime 行的 schema_version 校正为当前 head。
"""
from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from ..database.base import utcnow
from ..domain.blessed_time import NATURAL_TIME_RATE
from ..domain.constants import RateReasons, SimulationVersion, WorldBibleVersion
from .repositories import RuntimeRepository, TimeRatioRepository


def migrate_database(database_url: str, *, project_root: Path) -> None:
    """alembic upgrade head。"""
    cfg = Config(str(project_root / "alembic.ini"))
    cfg.set_main_option("script_location",
                        str(project_root / "database" / "alembic"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(cfg, "head")


def current_schema_version(session: Session) -> str:
    row = session.execute(
        text("SELECT version_num FROM alembic_version LIMIT 1")).fetchone()
    return row[0] if row else "0000"


def sync_runtime_schema_version(session: Session) -> None:
    """版本锁三要素之一：schema_version 必须 = 当前 alembic head。"""
    repo = RuntimeRepository(session)
    row = repo.get()
    if row is None:
        return
    current = current_schema_version(session)
    if row.schema_version != current:
        row.schema_version = current


def seed_database(engine: Engine, session_factory: sessionmaker[Session], *,
                  bible_dir: Path | None = None,
                  world_id: str = "BL-0001") -> dict:
    """播种版本元数据（幂等）。bible_dir 为 None 时跳过 Bible 指纹校验与
    world_runtime 行创建（世界保持未播种，绝不伪造 manifest hash）。"""
    result = {"seeded_world": False, "seeded_rate": False}
    with session_factory() as session:
        repo = RuntimeRepository(session)
        if bible_dir is not None:
            from .bible_integrity import verify_bible
            fp = verify_bible(bible_dir)
            if repo.get() is None:
                repo.create_not_activated(
                    world_id=world_id,
                    world_bible_version=WorldBibleVersion.CURRENT,
                    simulation_version=SimulationVersion.CURRENT,
                    world_bible_manifest_hash=fp.manifest_hex,
                )
                result["seeded_world"] = True
        sync_runtime_schema_version(session)
        tr = TimeRatioRepository(session)
        if not tr.list_all():
            tr.add(world_id=world_id,
                   real_effective_from=utcnow(),
                   rate_numerator=NATURAL_TIME_RATE.blessed_ticks,
                   rate_denominator=NATURAL_TIME_RATE.real_micros,
                   reason=RateReasons.BIBLE_NATURAL,
                   source="WORLD_BIBLE_V1.0_WS-0201",
                   blessed_effective_from_tick=None)
            result["seeded_rate"] = True
        session.commit()
    return result
