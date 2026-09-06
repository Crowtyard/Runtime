# -*- coding: utf-8 -*-
"""stub astrbot 官方路径 API（仅测试 harness）。"""
import os
from pathlib import Path


def get_astrbot_data_path() -> Path:
    return Path(os.environ.get("BLR_STUB_DATA_PATH", "."))


def get_astrbot_plugin_data_path() -> Path:
    return Path(os.environ.get(
        "BLR_STUB_PLUGIN_DATA_ROOT",
        os.environ.get("BLR_STUB_DATA_PATH", "."))) / "plugin_data"
