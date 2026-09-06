"""init_db：对正式库执行 migration 到 head + 播种版本元数据。

播种内容仅限：world_runtime（NOT_ACTIVATED）/ time_ratio_history 自然态 1 行
（blessed_effective_from_tick=NULL=未激活，属 World Rule 元数据而非世界激活）。
禁止生成任何人口/NPC/聚落/灾劫/纪年/事件。
同时：校正 schema_version 到当前 alembic head；校验事件不可变触发器在位。
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402


from config.settings import Settings  # noqa: E402
from database.base import utcnow  # noqa: E402
from database.db import create_db_engine, make_session_factory  # noqa: E402
from database.invariants import verify_event_immutability  # noqa: E402
from domain.constants import RatioReasons, SimulationVersion, WorldBibleVersion  # noqa: E402
from services.bible_integrity import verify_bible  # noqa: E402
from services.repositories import (RuntimeRepository,  # noqa: E402
                                   TimeRatioRepository)


def migrate(settings: Settings) -> None:
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "database" / "alembic"))
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(cfg, "head")


def seed(settings: Settings) -> None:
    engine = create_db_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    fp = verify_bible(settings.bible_dir)
    with session_factory() as session:
        repo = RuntimeRepository(session)
        if repo.get() is None:
            repo.create_not_activated(
                world_id="BL-0001",
                world_bible_version=WorldBibleVersion.CURRENT,
                simulation_version=SimulationVersion.CURRENT,
                world_bible_manifest_hash=fp.manifest_hex,
            )
        repo.sync_schema_version()  # 版本锁三要素之一：schema_version 必须 = head
        tr = TimeRatioRepository(session)
        if not tr.list_all():
            tr.add(world_id="BL-0001",
                   real_effective_from=utcnow(),
                   ratio_value=365.0,
                   reason=RatioReasons.BIBLE_NATURAL,
                   source="WORLD_BIBLE_V1.0_WS-0201",
                   blessed_effective_from_tick=None)
        session.commit()
    verify_event_immutability(engine)  # 事件历史不可变触发器在位
    print("seed done: world_runtime NOT_ACTIVATED; ratio history=1; bible",
          fp.version)


if __name__ == "__main__":
    settings = Settings()
    migrate(settings)
    seed(settings)
