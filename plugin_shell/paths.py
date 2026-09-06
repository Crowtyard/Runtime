# -*- coding: utf-8 -*-
"""plugin_data 路径解析（唯一允许触碰 AstrBot 路径 API 的适配点）。

硬门禁：正式世界数据绝不保存在插件源码目录/仓库根目录；DB 路径必须动态解析，
禁止硬编码任何磁盘绝对路径（含盘符、用户目录、Private Companion 路径、项目开发路径）。

测试可通过环境变量 BLR_TEST_PLUGIN_DATA_DIR 覆盖（仅测试 harness 使用）。
"""
from __future__ import annotations

import os
from pathlib import Path

PLUGIN_NAME = "astrbot_plugin_blessed_land_runtime"
AUTHORITATIVE_MARKER = "authoritative_db.json"


def resolve_plugin_data_dir() -> Path:
    """返回本插件专属持久数据目录：<astrbot data>/plugin_data/<plugin_name>。"""
    override = os.environ.get("BLR_TEST_PLUGIN_DATA_DIR")
    if override:
        return Path(override)
    # 官方稳定 API 优先
    try:
        from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path
        return Path(get_astrbot_plugin_data_path()) / PLUGIN_NAME
    except Exception:  # noqa: BLE001
        pass
    # 官方等价回退：data/plugin_data/<plugin_name>
    try:
        from astrbot.core.utils.astrbot_path import get_astrbot_data_path
        return Path(get_astrbot_data_path()) / "plugin_data" / PLUGIN_NAME
    except Exception:  # noqa: BLE001
        pass
    raise RuntimeError(
        "无法解析 AstrBot plugin_data 路径（缺少官方路径 API）")
