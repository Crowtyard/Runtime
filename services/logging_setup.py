"""结构化日志（26 节）：按子系统分类；日志≠世界历史。"""
from __future__ import annotations

import logging
import sys

LOG_CHANNELS = [
    "RUNTIME", "DATABASE", "MIGRATION", "BACKUP",
    "TIME", "SIMULATION", "LOCK", "INTEGRITY",
    "SCHEDULER",
]


def _make_logger(channel: str) -> logging.Logger:
    name = f"blr.{channel.lower()}"
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
    return logger


def get_logger(channel: str) -> logging.Logger:
    channel = channel.upper()
    if channel not in LOG_CHANNELS:
        raise ValueError(f"未知日志通道: {channel}")
    return _make_logger(channel)
