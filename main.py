# -*- coding: utf-8 -*-
"""astrbot_plugin_blessed_land_runtime —— AstrBot 插件外壳（唯一 AstrBot 感知模块）。

PLUGIN SHELL ≠ DOMAIN CORE：
- 本文件只负责：AstrBot 生命周期（initialize/terminate）、只读 Web API 注册、
  Plugin Page 支撑（metadata.yaml pages + pages/blessed-land/）。
- 全部 Runtime 逻辑在 plugin_shell/runtime_host.py 与 domain/services/database，
  这些模块禁止 import astrbot（由测试强制）。

硬门禁：
- 只读。不提供 /activate /advance-time /seed /create-person /create-event 等任何
  mutation 端点；正式世界保持 NOT_ACTIVATED。
- 不自动 Catch-up、不激活 Seed、不推进正式世界（load/reload/status/page 皆然）。
"""
from __future__ import annotations

from astrbot.api import AstrBotConfig, logger
from astrbot.api.star import Context, Star

from .plugin_shell import runtime_host
from .plugin_shell.paths import resolve_plugin_data_dir

PLUGIN_NAME = "astrbot_plugin_blessed_land_runtime"


class BlessedLandRuntimePlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context, config)
        self._host: runtime_host.RuntimeHost | None = None

    async def initialize(self) -> None:
        """插件加载：解析 plugin_data → 建目录 → 定位/校验 authoritative DB →
        迁移 head → 完整性/不变量审计 → 初始化引擎。

        明确不做的：不推进正式世界、不自动 Catch-up、不 Activate Seed。
        """
        data_dir = resolve_plugin_data_dir()
        self._host = runtime_host.RuntimeHost(
            data_dir,
            enabled=bool(self._resolve_config("runtime_enabled", True)),
            log_level=str(self._resolve_config("diagnostic_log_level", "INFO")),
            backup_retention=int(self._resolve_config("backup_retention", 10)),
            page_refresh_interval=int(
                self._resolve_config("page_refresh_interval", 30)),
        )
        self._host.boot()
        self._register_apis()
        logger.info("[%s] initialized: world_status=%s db=%s",
                    PLUGIN_NAME,
                    self._host.status()["world_status"],
                    self._host.db_path)

    async def terminate(self) -> None:
        """插件卸载：释放引擎/连接；不产生任何世界时间推进或历史。"""
        if self._host is not None:
            self._host.shutdown()
            self._host = None

    def _resolve_config(self, key: str, default):
        value = self.config.get(key) if hasattr(self.config, "get") else None
        if value is None:
            try:
                value = self.config[key]
            except (KeyError, TypeError):
                value = default
        return value if value is not None else default

    # ---------------------------------------------------------------- 只读 Web API
    def _register_apis(self) -> None:
        reg = self.context.register_web_api
        reg("/status", self._api_status, ["GET"], "福地 Runtime 状态（只读）")
        reg("/diagnostics", self._api_diagnostics, ["GET"],
            "福地 Runtime 诊断（只读）")
        reg("/runtime-info", self._api_runtime_info, ["GET"],
            "福地 Runtime 运行信息（只读）")

    @staticmethod
    def _envelope(data: dict) -> dict:
        return {"success": True, "data": data}

    async def _api_status(self, *args, **kwargs) -> dict:  # noqa: ANN001, ANN002, ANN003
        return self._envelope(self._host.status())

    async def _api_diagnostics(self, *args, **kwargs) -> dict:  # noqa: ANN001, ANN002, ANN003
        return self._envelope(self._host.diagnostics())

    async def _api_runtime_info(self, *args, **kwargs) -> dict:  # noqa: ANN001, ANN002, ANN003
        return self._envelope(self._host.runtime_info())
