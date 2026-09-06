# -*- coding: utf-8 -*-
"""astrbot_plugin_blessed_land_runtime —— 小光福地 Runtime（独立 AstrBot 插件）。

PLUGIN SHELL ≠ DOMAIN CORE：
- main.py 是唯一 AstrBot 感知模块（生命周期 + 只读 Web API）。
- 全部 Runtime 逻辑在 plugin_shell/ 与 domain/services/database（禁止 import astrbot）。
"""
RUNTIME_VERSION = "0.1.1"
PLUGIN_NAME = "astrbot_plugin_blessed_land_runtime"
