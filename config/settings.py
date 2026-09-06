"""配置（25 节）：工程参数。世界规则不进这里（由 World State/World Rule 表管理）。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _default_db() -> str:
    return os.environ.get(
        "BLR_DATABASE_URL",
        "sqlite:///" + str((_PROJECT_ROOT / "world.db").resolve()).replace("\\", "/"),
    )


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=_default_db)
    backup_path: Path = field(default_factory=lambda: _PROJECT_ROOT / "backups")
    log_level: str = "INFO"
    runtime_mode: str = "LOCAL"  # LOCAL | NAS | VPS(未来)
    bible_dir: Path = field(
        default_factory=lambda: _PROJECT_ROOT.parent / "XIAOGUANG_CROW_KB" / "world_bible")
    writer_lease_seconds: int = 120
    checkpoint_interval_years: int = 10  # M1 起使用；M0 仅配置


def load_settings() -> Settings:
    return Settings()
