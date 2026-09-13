"""Alembic 环境（M0）：URL 来自 BLR_DATABASE_URL 或 config.settings，不写死 ini。"""
from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, pool

# 允许直接运行 `alembic` 时导入工程包
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import Settings  # noqa: E402
from database import models_core, models_world  # noqa: F401,E402
from database.base import Base  # noqa: E402
from database.migration_contract import is_logging_config_skipped  # noqa: E402

config = context.config
# M5.1 事故不变量：进程内（embedded）迁移绝不改动宿主 logging。
# 是否 embedded 由显式 flag 声明（database/migration_contract.py），
# 不依据调用栈/模块名猜测。CLI（`alembic upgrade head`）不带该标记，
# 仍按 alembic.ini 自行配置 logging —— 那是 CLI 自身进程，与宿主无关。
if config.config_file_name is not None \
        and not is_logging_config_skipped(config.attributes):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _url() -> str:
    cfg = config.get_main_option("sqlalchemy.url")
    if cfg and not cfg.startswith("driver://"):
        return cfg
    return Settings().database_url


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata,
                      literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
