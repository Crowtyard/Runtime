# -*- coding: utf-8 -*-
"""迁移调用契约（M5.1 live 事故根因修复，2026-09-12）。

事故经过：Runtime 在 AstrBot 进程内执行 ``alembic upgrade`` 时，``env.py`` 调用了
``logging.config.fileConfig(alembic.ini)``。该调用以默认
``disable_existing_loggers=True`` 执行，副作用有二：

1. 禁用当时**已存在**的全部 logger（含 AstrBot 的 ``astrbot`` 全树）；
2. 用 ini 的 root 配置（``level=WARNING``、handler=``StreamHandler(sys.stderr)``）
   替换宿主 root handler（AstrBot 的 loguru 桥被移除）。

后果：宿主 ``core_lifecycle`` 的 ``logger.info("AstrBot started.")`` 被静默丢弃，
Launcher 的 stdout 就绪标记永不出现 → ``startup timed out (300s)`` → force kill。

不变量（本模块是该不变量的唯一权威定义）：

    ALEMBIC_MIGRATION_MAY_MUTATE_DATABASE_SCHEMA
    BUT
    ALEMBIC_MIGRATION_MUST_NOT_MUTATE_HOST_LOGGING

Runtime 是 AstrBot 进程内插件，**不拥有**宿主 logging configuration：

- ``CLI`` 调用（``alembic upgrade head``）：alembic 可按 ``alembic.ini`` 自行配置 logging；
- ``embedded`` 进程内调用：alembic 必须原样继承宿主 logging，一字不改。

运行模式由**显式 flag**（``Config.attributes``）声明，
**绝不依据调用栈、模块名或 sys.argv 隐式猜测**。
"""
from __future__ import annotations

from typing import Mapping

#: 写入 alembic ``Config.attributes`` 的显式标记：进程内迁移跳过 ini 的 logging 配置。
SKIP_LOGGING_CONFIG_ATTR = "skip_logging_config"


def embedded_migration_attributes() -> dict[str, bool]:
    """进程内（embedded）迁移必须写入 ``Config.attributes`` 的标记集合。"""
    return {SKIP_LOGGING_CONFIG_ATTR: True}


def is_logging_config_skipped(attributes: Mapping[str, object]) -> bool:
    """是否已显式声明跳过 ``alembic.ini`` 的 logging 配置。"""
    return bool(attributes.get(SKIP_LOGGING_CONFIG_ATTR, False))


__all__ = [
    "SKIP_LOGGING_CONFIG_ATTR",
    "embedded_migration_attributes",
    "is_logging_config_skipped",
]
