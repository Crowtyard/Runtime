"""手动备份入口：python scripts/backup_now.py [--pre-migration]"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import Settings  # noqa: E402
from database.db import create_db_engine  # noqa: E402
from services.backup_service import backup_sqlite, pre_migration_backup  # noqa: E402


def main() -> None:
    settings = Settings()
    engine = create_db_engine(settings.database_url)
    dest = settings.backup_path / "world_backup.db"
    if "--pre-migration" in sys.argv:
        rec = pre_migration_backup(engine, settings.backup_path)
    else:
        rec = backup_sqlite(engine, dest, meta={"kind": "MANUAL"})
    print("backup:", rec)


if __name__ == "__main__":
    main()
