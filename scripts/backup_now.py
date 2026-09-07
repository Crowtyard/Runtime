# -*- coding: utf-8 -*-
"""手动备份入口：python scripts/backup_now.py [--pre-migration]"""
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
_backup = importlib.import_module(f"{_PKG}.services.backup_service")


def main() -> None:
    settings = _settings.Settings()
    engine = _db.create_db_engine(settings.database_url)
    dest = settings.backup_path / "world_backup.db"
    if "--pre-migration" in sys.argv:
        rec = _backup.pre_migration_backup(engine, settings.backup_path)
    else:
        rec = _backup.backup_sqlite(engine, dest, meta={"kind": "MANUAL"})
    print("backup:", rec)


if __name__ == "__main__":
    main()
