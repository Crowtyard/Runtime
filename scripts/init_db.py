# -*- coding: utf-8 -*-
"""init_db：对正式库执行 migration 到 head + 播种版本元数据（开发环境工具）。

播种内容仅限：world_runtime（NOT_ACTIVATED）/ time_ratio_history 自然态 1 行
（blessed_effective_from_tick=NULL=未激活，属 World Rule 元数据而非世界激活）。
禁止生成任何人口/NPC/聚落/灾劫/纪年/事件。
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT.parent))
_PKG = PROJECT_ROOT.name

_settings = importlib.import_module(f"{_PKG}.config.settings")
_db = importlib.import_module(f"{_PKG}.database.db")
_invariants = importlib.import_module(f"{_PKG}.database.invariants")
_lifecycle = importlib.import_module(f"{_PKG}.services.db_lifecycle")


def main() -> None:
    settings = _settings.Settings()
    _lifecycle.migrate_database(settings.database_url, project_root=PROJECT_ROOT)
    engine = _db.create_db_engine(settings.database_url)
    session_factory = _db.make_session_factory(engine)
    _lifecycle.seed_database(engine, session_factory,
                             bible_dir=settings.bible_dir)
    _invariants.verify_event_immutability(engine)  # 事件历史不可变触发器在位
    print("seed done: world_runtime NOT_ACTIVATED; ratio history=1")


if __name__ == "__main__":
    main()
