# -*- coding: utf-8 -*-
"""RuntimeHost —— AstrBot 插件生命周期与 Runtime 核心之间的宿主。

硬约束（本模块不 import astrbot）：
- boot()：建目录 → 定位 authoritative DB → alembic head → 完整性/不变量审计 →
  初始化引擎。绝不推进正式世界、绝不自动 Catch-up、绝不激活 Seed。
- status()/diagnostics()/runtime_info()：只读（可重复调用、零世界写入）。
- shutdown()：只释放引擎/连接。
- backup_now()：备份写入 plugin_data/backups（§24）。

ACTIVATION TIME TRAP 保证：NOT_ACTIVATED 世界无论 plugin load/reload/status/
page/diagnostics 多少次、现实经过多久，last_committed_real_us 与
current_blessed_tick 都保持 NULL，不产生 simulation_run / TIME_ADVANCE。
激活纪元的建立属于 M2 Activation Transaction。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..database.db import create_db_engine, make_session_factory
from ..database.invariants import (event_immutability_triggers_present,
                                 verify_event_immutability)
from ..database.models_core import (RuntimeLock, SimulationCheckpoint,
                                  SimulationRun, TimeRatioHistory, WorldEvent,
                                  WorldRuntime)
from ..domain.blessed_time import NATURAL_TIME_RATE
from ..domain.constants import RuntimeStatus
from ..services.backup_service import backup_sqlite, integrity_check
from ..services.db_lifecycle import (current_schema_version, migrate_database,
                                   sync_runtime_schema_version)
from ..services.logging_setup import get_logger

log = get_logger("RUNTIME")

RUNTIME_VERSION = "0.1.1"
PLUGIN_NAME = "astrbot_plugin_blessed_land_runtime"
DB_FILENAME = "blessed_land.sqlite"
AUTHORITATIVE_MARKER = "authoritative_db.json"
EXPECTED_SCHEMA_HEAD = "f2a7c4e9b1d6"  # PRE-M6 PG head（+TRUNCATE 不可变保护）

BUSINESS_TABLES = {
    "persons": "persons",
    "population_groups": "population_groups",
    "settlements": "settlements",
    "resource_nodes": "resource_nodes",
    "tribulations": "tribulations",
    "world_events": "world_events",
    "timeline_entries": "timeline_entries",
    "simulation_run": "simulation_run",
    "simulation_checkpoints": "simulation_checkpoints",
    "narrative_records": "narrative_records",
    "world_state_changes": "world_state_changes",
    "runtime_lock": "runtime_lock",
    "cultural_elements": "cultural_elements",
    "ecological_regions": "ecological_regions",
    "industries": "industries",
    "institutions": "institutions",
    "lineages": "lineages",
    "system_configuration": "system_configuration",
}


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RuntimeHost:
    """托管小光福地世界数据库（只读控制台 + 生命周期；无世界推进）。"""

    def __init__(self, data_dir: Path, *, enabled: bool = True,
                 log_level: str = "INFO", backup_retention: int = 10,
                 page_refresh_interval: int = 30,
                 project_root: Path | None = None):
        self.data_dir = Path(data_dir)
        self.enabled = enabled
        self.log_level = log_level
        self.backup_retention = backup_retention
        self.page_refresh_interval = page_refresh_interval
        self.project_root = (project_root or
                             Path(__file__).resolve().parent.parent)
        self.db_path = self.data_dir / DB_FILENAME
        self.backups_dir = self.data_dir / "backups"
        self.exports_dir = self.data_dir / "exports"
        self.runtime_state_dir = self.data_dir / "runtime_state"
        self.logs_dir = self.data_dir / "logs"
        self.engine: Engine | None = None
        self.session_factory: sessionmaker[Session] | None = None
        self._boot_errors: list[str] = []
        # M4 scheduler（可选附加；astrbot-free，由插件生命周期驱动）
        self._scheduler = None
        self._scheduler_task = None

    # ------------------------------------------------------------- 生命周期
    def boot(self) -> None:
        self._ensure_dirs()
        if not self.enabled:
            log.info("runtime disabled by config; engine not created")
            return
        if not self.db_path.exists():
            self._create_fresh_db()
        else:
            migrate_database("sqlite:///" + str(self.db_path).replace("\\", "/"),
                             project_root=self.project_root)
        self.engine = create_db_engine(
            "sqlite:///" + str(self.db_path).replace("\\", "/"))
        self.session_factory = make_session_factory(self.engine)
        try:
            verify_event_immutability(self.engine)
            with self.session_factory() as s:
                sync_runtime_schema_version(s)
                s.commit()
        except Exception as exc:  # noqa: BLE001
            self._boot_errors.append(str(exc))
            log.error("boot invariant check failed: %s", exc)
        self._write_authoritative_marker()
        log.info("runtime host booted: db=%s integrity=%s",
                 self.db_path, self._integrity_or_none())

    def shutdown(self) -> None:
        if self.engine is not None:
            self.engine.dispose()
        self.engine = None
        self.session_factory = None
        log.info("runtime host shut down (no world advance, no history)")

    # ------------------------------------------------------------- M4 scheduler
    def attach_scheduler(self, scheduler) -> None:
        """附加 RuntimeScheduler（M4）。重复 attach 幂等替换旧实例。"""
        self._scheduler = scheduler
        log.info("scheduler attached: %s", type(scheduler).__name__)

    def detach_scheduler(self) -> None:
        self._scheduler = None

    async def start_scheduler_task(self) -> bool:
        """AstrBot 生命周期：启动 scheduler 循环任务（幂等；不产生双循环）。

        返回 False 表示已有任务在跑。
        """
        import asyncio
        if self._scheduler is None:
            log.warning("no scheduler attached; task not started")
            return False
        if self._scheduler_task is not None \
                and not self._scheduler_task.done():
            return False
        if not self._scheduler.start():
            return False
        poll_ms = self._scheduler.config.poll_interval_ms

        async def _loop():
            while True:
                try:
                    self._scheduler.run_cycle()
                except Exception as exc:  # noqa: BLE001
                    log.error("scheduler cycle error: %s", exc)
                await asyncio.sleep(poll_ms / 1000.0)

        self._scheduler_task = asyncio.create_task(_loop())
        log.info("scheduler task started poll_ms=%s", poll_ms)
        return True

    async def stop_scheduler_task(self) -> None:
        """AstrBot 生命周期：取消循环任务（无孤儿 task）、释放写权限。"""
        import asyncio
        if self._scheduler is not None:
            self._scheduler.stop()
        if self._scheduler_task is not None:
            task = self._scheduler_task
            self._scheduler_task = None
            task.cancel()
            try:
                await asyncio.gather(task, return_exceptions=True)
            except Exception as exc:  # noqa: BLE001
                log.warning("scheduler task cancel: %s", exc)
        log.info("scheduler task stopped (no orphan loops)")

    def _ensure_dirs(self) -> None:
        for d in (self.data_dir, self.backups_dir, self.exports_dir,
                  self.runtime_state_dir, self.logs_dir):
            d.mkdir(parents=True, exist_ok=True)

    def _create_fresh_db(self) -> None:
        """首次安装：仅建 schema（alembic head）。世界行由正式 DB 迁移或
        Bible 校验后的 seed 提供 —— 绝不伪造 manifest hash、绝不激活。"""
        migrate_database("sqlite:///" + str(self.db_path).replace("\\", "/"),
                         project_root=self.project_root)
        log.info("fresh schema created at %s (world NOT seeded)", self.db_path)

    def _integrity_or_none(self) -> str | None:
        if self.engine is None:
            return None
        try:
            return integrity_check(self.engine)
        except Exception as exc:  # noqa: BLE001
            return f"error: {exc}"

    # ------------------------------------------------------------- 权威 DB 标记
    def _scheduler_section(self) -> dict:
        """M4 只读：scheduler 状态段（未附加 → DETACHED）。"""
        if self._scheduler is None:
            return {"scheduler_state": "DETACHED"}
        return self._scheduler.get_scheduler_status()

    def _write_authoritative_marker(self) -> None:
        """单一权威：运行时只打开这一个正式世界 DB（AUTHORITATIVE_DB_PATH）。"""
        record = {
            "plugin": PLUGIN_NAME,
            "authoritative_db_path": str(self.db_path),
            "checksum_sha256": _sha256_file(self.db_path)
            if self.db_path.exists() else None,
            "written_at": datetime.now(timezone.utc).isoformat(),
        }
        marker = self.runtime_state_dir / AUTHORITATIVE_MARKER
        tmp = marker.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(record, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        tmp.replace(marker)

    def read_authoritative_marker(self) -> dict | None:
        marker = self.runtime_state_dir / AUTHORITATIVE_MARKER
        if not marker.exists():
            return None
        try:
            return json.loads(marker.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return None

    # ------------------------------------------------------------- 只读状态
    def _read_world_row(self, s: Session) -> WorldRuntime | None:
        return s.execute(select(WorldRuntime).limit(1)).scalar_one_or_none()

    def _entity_counts(self, s: Session) -> dict:
        counts = {}
        for key, table in BUSINESS_TABLES.items():
            counts[key] = s.execute(
                text(f'SELECT COUNT(*) FROM "{table}"')).scalar()
        return counts

    def _writer_view(self, s: Session) -> dict:
        lock = s.execute(select(RuntimeLock).limit(1)).scalar_one_or_none()
        if lock is None:
            return {"lease": "INACTIVE", "note": "Not required (no writer)"}
        now = datetime.now(timezone.utc)
        expired = lock.expires_at.tzinfo is None or lock.expires_at <= now
        return {
            "lease": "EXPIRED" if expired else "HELD",
            "writer_id": lock.owner,
            "fencing_token": lock.lease_token,
            "acquired_at": str(lock.acquired_at),
            "expires_at": str(lock.expires_at),
        }

    def status(self) -> dict:
        """只读状态快照（页面 /status）。绝不写入世界状态。"""
        if self.engine is None:
            return self._status_unbooted()
        with self.session_factory() as s:
            row = self._read_world_row(s)
            counts = self._entity_counts(s)
            writer = self._writer_view(s)
            schema_head = current_schema_version(s)
        if row is None:
            return {
                "plugin_status": "RUNNING",
                "runtime_version": RUNTIME_VERSION,
                "world_status": "NOT_ACTIVATED",
                "world_row_present": False,
                "seed_present": False,
                "current_blessed_tick": None,
                "scheduler": self._scheduler_section(),
                "tick_unit": "1 tick = 1 µy (micro-blessed-year)",
                "natural_rate": {
                    "numerator": NATURAL_TIME_RATE.blessed_ticks,
                    "denominator": NATURAL_TIME_RATE.real_micros,
                    "meaning": "现实约 1 天 ≈ 福地约 1 年",
                },
                "db": {
                    "path": str(self.db_path),
                    "integrity": self._integrity_or_none(),
                    "schema_version": schema_head,
                },
                "writer": writer,
                "entity_counts": counts,
            }
        return {
            "plugin_status": "RUNNING",
            "runtime_version": RUNTIME_VERSION,
            "world_status": row.runtime_status,
            "world_row_present": True,
            "seed_present": row.world_seed_version is not None,
            "world_seed_version": row.world_seed_version,
            "current_blessed_tick": row.current_blessed_tick,
            "last_committed_real_us": row.last_committed_real_us,
            "simulation_version": row.simulation_version,
            "scheduler": self._scheduler_section(),
            "tick_unit": "1 tick = 1 µy (micro-blessed-year)",
            "natural_rate": {
                "numerator": NATURAL_TIME_RATE.blessed_ticks,
                "denominator": NATURAL_TIME_RATE.real_micros,
                "meaning": "现实约 1 天 ≈ 福地约 1 年",
            },
            "db": {
                "path": str(self.db_path),
                "integrity": self._integrity_or_none(),
                "schema_version": schema_head,
            },
            "writer": writer,
            "entity_counts": counts,
        }

    def _status_unbooted(self) -> dict:
        return {
            "plugin_status": "DISABLED" if not self.enabled else "BOOT_FAILED",
            "runtime_version": RUNTIME_VERSION,
            "world_status": RuntimeStatus.NOT_ACTIVATED,
            "seed_present": False,
            "current_blessed_tick": None,
            "scheduler": self._scheduler_section(),
            "tick_unit": "1 tick = 1 µy (micro-blessed-year)",
            "natural_rate": {
                "numerator": NATURAL_TIME_RATE.blessed_ticks,
                "denominator": NATURAL_TIME_RATE.real_micros,
                "meaning": "现实约 1 天 ≈ 福地约 1 年",
            },
            "db": {"path": str(self.db_path),
                   "integrity": None, "schema_version": None},
            "writer": {"lease": "INACTIVE", "note": "host not booted"},
            "entity_counts": {},
        }

    def diagnostics(self) -> dict:
        """只读诊断（页面 /diagnostics）。"""
        checks: dict = {}
        if self.engine is None:
            return {"m0": "FAIL", "m1": "FAIL", "time_engine": "READY",
                    "offline_catchup": "READY", "world_activation": "LOCKED",
                    "checks": {"boot": "host not booted"}}
        checks["db_integrity"] = self._integrity_or_none()
        with self.session_factory() as s:
            checks["alembic_head"] = current_schema_version(s)
            checks["event_immutability_triggers"] = (
                event_immutability_triggers_present(self.engine))
            row = self._read_world_row(s)
            counts = self._entity_counts(s)
        checks["world_audit"] = {
            "world_status": row.runtime_status if row else "NO_ROW",
            "seed": row.world_seed_version if row else None,
            "current_blessed_tick": row.current_blessed_tick if row else None,
            "entity_counts": counts,
        }
        m0 = "PASS" if (checks["db_integrity"] == "ok"
                        and checks["alembic_head"] == EXPECTED_SCHEMA_HEAD
                        and checks["event_immutability_triggers"]) else "FAIL"
        m1 = "PASS" if m0 == "PASS" else "FAIL"
        return {
            "m0": m0,
            "m1": m1,
            "time_engine": "READY",
            "offline_catchup": "READY",
            "world_activation": "LOCKED",
            "checks": checks,
        }

    def runtime_info(self) -> dict:
        """只读运行信息（页面 /runtime-info）。"""
        marker = self.read_authoritative_marker()
        return {
            "plugin_name": PLUGIN_NAME,
            "runtime_version": RUNTIME_VERSION,
            "enabled": self.enabled,
            "log_level": self.log_level,
            "backup_retention": self.backup_retention,
            "page_refresh_interval": self.page_refresh_interval,
            "data_dir": str(self.data_dir),
            "db_path": str(self.db_path),
            "backups_dir": str(self.backups_dir),
            "authoritative_db": marker,
            "world_time_model": {
                "tick_unit": "1 tick = 1 µy",
                "natural_rate": [NATURAL_TIME_RATE.blessed_ticks,
                                 NATURAL_TIME_RATE.real_micros],
                "rate_kind": "integer rational (tick / real µs)",
            },
        }

    # ------------------------------------------------------------- 备份
    def backup_now(self) -> dict:
        """备份到 plugin_data/backups（§24：备份不随插件代码更新丢失）。"""
        if self.engine is None:
            raise RuntimeError("runtime host not booted")
        return backup_sqlite(self.engine, self.backups_dir / "blessed_land.db",
                             meta={"kind": "PLUGIN_MANUAL"})
