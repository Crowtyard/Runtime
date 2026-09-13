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
from astrbot.api.event.filter import on_llm_request
from astrbot.api.star import Context, Star

try:  # 官方注入点（builtin stars 同路径；旧版本 fallback dict）
    from astrbot.core.agent.message import TextPart
except ImportError:  # pragma: no cover
    TextPart = None

from .plugin_shell import runtime_host
from .plugin_shell.paths import resolve_plugin_data_dir

PLUGIN_NAME = "astrbot_plugin_blessed_land_runtime"


class BlessedLandRuntimePlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context, config)
        # 注意：官方 Star.__init__ 不保存 config —— 插件必须自行保存
        # （AstrBot v4.28 实测行为；config 为 dict-like AstrBotConfig）。
        self.config = config if config is not None else {}
        self._host: runtime_host.RuntimeHost | None = None
        self._scheduler_start_pending = None
        self._m5_builder_cache = None

    async def initialize(self) -> None:
        """插件加载：解析 plugin_data → 建目录 → 定位/校验 authoritative DB →
        迁移 head → 完整性/不变量审计 → 初始化引擎 → 附加 Scheduler（M4）。

        明确不做的：不推进正式世界、不自动 Catch-up、不 Activate Seed。
        Scheduler 检测到 NOT_ACTIVATED → DORMANT（零 mutation、零租约）。
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
        self._attach_scheduler()
        self._register_apis()
        logger.info("[%s] initialized: world_status=%s db=%s",
                    PLUGIN_NAME,
                    self._host.status()["world_status"],
                    self._host.db_path)

    def _attach_scheduler(self) -> None:
        """M4：构造 RuntimeScheduler（不启动世界推进；DORMANT 语义见 core）。"""
        if not self._resolve_config("scheduler_enabled", True):
            return
        from datetime import datetime, timezone

        from .domain.blessed_time import datetime_to_epoch_us
        from .services.scheduler import RuntimeScheduler, SchedulerConfig

        if self._host.session_factory is None:
            return  # host 未 boot（runtime_enabled=false）
        with self._host.session_factory() as s:
            from sqlalchemy import select
            from .database.models_core import WorldRuntime
            row = s.execute(select(WorldRuntime).limit(1)) \
                .scalar_one_or_none()
        world_id = row.world_id if row is not None else "FORMAL-UNSEEDED"
        config = SchedulerConfig(
            enabled=bool(self._resolve_config("scheduler_enabled", True)),
            poll_interval_ms=int(self._resolve_config(
                "scheduler_poll_interval_ms", 5000)),
            catch_up_max_ticks_per_cycle=int(self._resolve_config(
                "scheduler_catch_up_max_ticks_per_cycle", 100_000_000)),
            lease_ttl_ms=int(self._resolve_config(
                "scheduler_lease_ttl_ms", 120_000)),
            heartbeat_interval_ms=int(self._resolve_config(
                "scheduler_heartbeat_interval_ms", 30_000)),
            shutdown_grace_ms=int(self._resolve_config(
                "scheduler_shutdown_grace_ms", 5000)),
        )
        scheduler = RuntimeScheduler(
            session_factory=self._host.session_factory,
            world_id=world_id,
            config=config,
            # 生产现实锚：墙钟 epoch µs（冻结 blessed_time 原语）；
            # coordinator 接线属 M6（未接线且世界已激活 → FAILED fail-closed）
            real_now_us_provider=lambda: datetime_to_epoch_us(
                datetime.now(timezone.utc)),
            state_dir=self._host.runtime_state_dir,
        )
        self._host.attach_scheduler(scheduler)
        try:
            import asyncio
            task = asyncio.create_task(
                self._host.start_scheduler_task())
            self._scheduler_start_pending = task
        except RuntimeError:
            pass  # 无事件循环（测试/同步上下文）→ 任务由调用方显式启动

    async def terminate(self) -> None:
        """插件卸载：先停 Scheduler（无孤儿循环、释放写权限），再释放引擎/
        连接；不产生任何世界时间推进或历史。"""
        if self._host is not None:
            await self._host.stop_scheduler_task()
            self._host.detach_scheduler()
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

    # ---------------------------------------------------------------- M5 查询集成
    @on_llm_request()
    async def _on_llm_request_world_context(self, event, req) -> None:  # noqa: ANN001, ANN002, ANN003
        """M5 官方 hook：每 ProviderRequest 至多追加一份世界上下文。

        - 只 APPEND extra_user_content_parts；绝不修改 system_prompt/prompt/
          contexts/conversation（不覆盖 Persona / Private Companion 上下文）。
        - 普通闲聊（NO_WORLD_CONTEXT）不注入任何内容。
        - 任何异常 → 不注入（fail-closed），绝不让查询层炸掉聊天链路。
        """
        if not self._resolve_config("query_integration_enabled", True):
            return
        text = self._m5_world_context_for(event)
        if not text:
            return
        if TextPart is not None:
            req.extra_user_content_parts.append(
                TextPart(text=text).mark_as_temp())
        else:  # pragma: no cover —— 极旧版本 fallback
            req.extra_user_content_parts.append(
                {"type": "text", "text": text})

    def _m5_world_context_for(self, event) -> str | None:
        """确定性路由 + 只读查询 + 渲染（RUNTIME_QUERY_LLM_CALLS=0）。"""
        try:
            user_text = getattr(event, "message_str", "") or ""
        except Exception:  # noqa: BLE001
            user_text = ""
        try:
            builder = self._m5_builder()
            if builder is None:
                return None
            return builder.build_and_render(str(user_text))
        except Exception:  # noqa: BLE001
            logger.exception("[%s] M5 context build failed (fail-closed)",
                             PLUGIN_NAME)
            return None

    def _m5_builder(self):
        """惰性构建 ContextBuilder（只读；绝不 start/resume scheduler）。"""
        if self._m5_builder_cache is not None:
            return self._m5_builder_cache
        if self._host is None or self._host.session_factory is None:
            return None
        from sqlalchemy import select

        from .database.models_core import WorldRuntime
        from .services.query import (
            ContextBuilder, WorldQueryIntentRouter, WorldQueryService)

        with self._host.session_factory() as s:
            row = s.execute(select(WorldRuntime).limit(1)) \
                .scalar_one_or_none()
        world_id = row.world_id if row is not None else "FORMAL-UNSEEDED"
        svc = WorldQueryService(
            session_factory=self._host.session_factory,
            world_id=world_id,
            scheduler_status_provider=(
                self._host._scheduler.get_scheduler_status
                if self._host._scheduler is not None else None))
        self._m5_builder_cache = ContextBuilder(
            query_service=svc, router=WorldQueryIntentRouter(),
            source="OFFICIAL")
        return self._m5_builder_cache

    # ---------------------------------------------------------------- 只读 Admin API（M5 §32）
    def _register_query_apis(self) -> None:
        reg = self.context.register_web_api
        reg(f"/{PLUGIN_NAME}/runtime/query/status", self._api_query_status,
            ["GET"], "只读：世界查询状态（M5）")
        reg(f"/{PLUGIN_NAME}/runtime/query/world", self._api_query_world,
            ["GET"], "只读：世界快照查询（M5）")
        reg(f"/{PLUGIN_NAME}/runtime/query/history", self._api_query_history,
            ["GET"], "只读：历史查询（M5）")

    async def _api_query_status(self, *args, **kwargs) -> dict:  # noqa: ANN001, ANN002, ANN003
        return self._envelope(self._m5_query_payload("status"))

    async def _api_query_world(self, *args, **kwargs) -> dict:  # noqa: ANN001, ANN002, ANN003
        return self._envelope(self._m5_query_payload("world"))

    async def _api_query_history(self, *args, **kwargs) -> dict:  # noqa: ANN001, ANN002, ANN003
        return self._envelope(self._m5_query_payload("history"))

    def _m5_query_payload(self, kind: str) -> dict:
        """只读查询入口（NOT_ACTIVATED → UNKNOWN 语义由查询层保证）。"""
        from .services.query import WorldQueryService
        if self._host is None or self._host.session_factory is None:
            return {"status": "RUNTIME_UNAVAILABLE", "reason": "HOST_NOT_BOOTED"}
        from sqlalchemy import select
        from .database.models_core import WorldRuntime
        with self._host.session_factory() as s:
            row = s.execute(select(WorldRuntime).limit(1)) \
                .scalar_one_or_none()
        world_id = row.world_id if row is not None else "FORMAL-UNSEEDED"
        svc = WorldQueryService(
            session_factory=self._host.session_factory,
            world_id=world_id,
            scheduler_status_provider=(
                self._host._scheduler.get_scheduler_status
                if self._host._scheduler is not None else None))
        try:
            if kind == "status":
                return svc.get_runtime_status()
            if kind == "world":
                return svc.get_world_snapshot()
            return svc.get_history_timeline()
        except Exception:  # noqa: BLE001
            return {"status": "RUNTIME_UNAVAILABLE",
                    "reason": "QUERY_FAILED"}

    # ---------------------------------------------------------------- 只读 Web API
    def _register_apis(self) -> None:
        # AstrBot v4.28 契约：路由必须包含插件名段 —— WebUI 调用
        # /api/v1/plugins/extensions/<plugin>/<route>，后端以 <plugin>/<route>
        # 匹配注册路由（页面桥 bridge.apiGet("/status") 由 WebUI 自动加插件前缀）。
        reg = self.context.register_web_api
        reg(f"/{PLUGIN_NAME}/status", self._api_status, ["GET"],
            "福地 Runtime 状态（只读）")
        reg(f"/{PLUGIN_NAME}/diagnostics", self._api_diagnostics, ["GET"],
            "福地 Runtime 诊断（只读）")
        reg(f"/{PLUGIN_NAME}/runtime-info", self._api_runtime_info, ["GET"],
            "福地 Runtime 运行信息（只读）")
        self._register_query_apis()

    @staticmethod
    def _envelope(data: dict) -> dict:
        return {"success": True, "data": data}

    async def _api_status(self, *args, **kwargs) -> dict:  # noqa: ANN001, ANN002, ANN003
        return self._envelope(self._host.status())

    async def _api_diagnostics(self, *args, **kwargs) -> dict:  # noqa: ANN001, ANN002, ANN003
        return self._envelope(self._host.diagnostics())

    async def _api_runtime_info(self, *args, **kwargs) -> dict:  # noqa: ANN001, ANN002, ANN003
        return self._envelope(self._host.runtime_info())
