# -*- coding: utf-8 -*-
"""M6A 激活测试支撑：**合成** World Seed 包 + 合成正式世界环境。

铁律（owner §21 / §25）：

- 全部测试使用临时 SQLite + **合成** seed（``synthetic_world_seed``）+
  合成 world_id；**绝不读取/消费正式 World Seed**，绝不触碰正式库；
- 合成 seed 与正式 Seed 包结构相同（VERSION.json + MANIFEST.sha256.txt +
  若干数据文件），因此走**同一条**校验/激活代码路径；
- 这里不预设任何 canon 数值：初始 tick / 年锚都是**显式测试输入**。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select, text

from tests.conftest import PROJECT_ROOT, W, run_migrations

from XiaoguangBlessedLandRuntime.database.models_core import (
    RuntimeLock, WorldEvent, WorldRuntime)
from XiaoguangBlessedLandRuntime.domain.blessed_time import (
    TICKS_PER_BLESSED_YEAR, datetime_to_epoch_us)
from XiaoguangBlessedLandRuntime.services.activation import ActivationRequest
from XiaoguangBlessedLandRuntime.services.durable_truth import (
    GENESIS_EVENT_TYPE)
from XiaoguangBlessedLandRuntime.services.repositories import (
    RuntimeRepository, TimeRatioRepository)

SYNTHETIC_SEED_NAME = "synthetic_world_seed"
SYNTHETIC_SEED_ID = "SYNTHETIC_TEST_WORLD_SEED_v1.0"
SYNTHETIC_DATA_FILES = (
    "01_synthetic_identity.json",
    "02_synthetic_baseline.json",
)

#: 合成世界原点（测试锚；**不是** canon 取值）。时间规则的有效起点与世界原点
#: 一致 —— 与 conftest ``active_clock_factory`` 的既有约定同构。
M6_EPOCH0 = datetime(2027, 1, 1, tzinfo=timezone.utc)
M6_EPOCH0_US = datetime_to_epoch_us(M6_EPOCH0)


def seed_m6_world(session_factory):
    """构造 M6 合成正式世界环境（供 ``m6_world`` fixture 使用）。

    与生产 ``seed_database`` 的产物同构（NOT_ACTIVATED 行 + 1 行自然态速率，
    ``blessed_effective_from_tick=NULL``），只把速率行的现实起点对齐到合成世界
    原点（``M6_EPOCH0_US``），使冻结 ``rate_at`` 能覆盖激活时刻。
    绝不触碰正式库。
    """
    with session_factory() as s:
        RuntimeRepository(s).create_not_activated(
            world_id=W, world_bible_version="1.0",
            simulation_version="0.1.0-dev", world_bible_manifest_hash="testhash")
        TimeRatioRepository(s).add(
            world_id=W, real_effective_from=M6_EPOCH0,
            rate_numerator=1_000_000, rate_denominator=86_400_000_000,
            reason="TEST", source="TEST")
        s.commit()
    return session_factory


def new_synthetic_world(tmp_path: Path):
    """独立的临时库 + M6 合成环境（供确定性/并发/进程级测试使用）。"""
    tmp_path = Path(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    url = "sqlite:///" + str(tmp_path / "m6_world.db").replace("\\", "/")
    run_migrations(url)
    from XiaoguangBlessedLandRuntime.database.db import (
        create_db_engine, make_session_factory)
    engine = create_db_engine(url)
    factory = make_session_factory(engine)
    with factory() as s:
        RuntimeRepository(s).create_not_activated(
            world_id=W, world_bible_version="1.0",
            simulation_version="0.1.0-dev", world_bible_manifest_hash="testhash")
        TimeRatioRepository(s).add(
            world_id=W, real_effective_from=M6_EPOCH0,
            rate_numerator=1_000_000, rate_denominator=86_400_000_000,
            reason="TEST", source="TEST")
        s.commit()
    return {"url": url, "engine": engine, "factory": factory,
            "epoch0_us": M6_EPOCH0_US, "root": PROJECT_ROOT}


def build_synthetic_seed(tmp_path: Path, *, version: str = "1.0",
                         status: str = "PREPARED_NOT_ACTIVATED",
                         seed_id: str = SYNTHETIC_SEED_ID,
                         name: str = SYNTHETIC_SEED_NAME,
                         marker: str = "SYNTHETIC",
                         tamper: str | None = None) -> Path:
    """构造合成 seed 包（结构与正式包一致：VERSION.json + MANIFEST）。

    ``marker``：写入数据文件的合成标记 —— 不同的 marker 得到**不同指纹**的
    两个 seed（用于"换 Seed 再激活必须被拒"这类测试）。
    ``tamper``：把 MANIFEST 中某文件的哈希写错（模拟 A8 校验失败）。
    """
    seed_dir = tmp_path / name
    seed_dir.mkdir(parents=True, exist_ok=True)
    payloads = {
        SYNTHETIC_DATA_FILES[0]: json.dumps(
            {"file": SYNTHETIC_DATA_FILES[0], "purpose": "SYNTHETIC TEST ONLY",
             "seed_marker": marker}, ensure_ascii=False, indent=1),
        SYNTHETIC_DATA_FILES[1]: json.dumps(
            {"file": SYNTHETIC_DATA_FILES[1], "purpose": "SYNTHETIC TEST ONLY",
             "entries": [], "seed_marker": marker}, ensure_ascii=False, indent=1),
    }
    for fname, body in payloads.items():
        (seed_dir / fname).write_text(body, encoding="utf-8")
    (seed_dir / "VERSION.json").write_text(json.dumps({
        "package": "SYNTHETIC_TEST_SEED_PACKAGE",
        "version": version,
        "status": status,
        "seed_id": seed_id,
        "note": "SYNTHETIC TEST FIXTURE — 绝不是正式 World Seed",
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    lines = []
    for fname in sorted(list(payloads) + ["VERSION.json"]):
        digest = hashlib.sha256((seed_dir / fname).read_bytes()).hexdigest()
        if tamper == fname:
            digest = "0" * 64
        lines.append(f"{digest}  {fname}")
    (seed_dir / "MANIFEST.sha256.txt").write_text("\n".join(lines) + "\n",
                                                  encoding="utf-8")
    return seed_dir


def synthetic_request(seed_dir: Path, *, world_id: str = W,
                      initial_blessed_tick: int = 0,
                      epoch0_us: int = M6_EPOCH0_US,
                      runtime_epoch0_us: int | None = None,
                      **kwargs) -> ActivationRequest:
    """构造激活请求（tick / 年锚均为显式测试输入，不是 canon 取值）。

    ``runtime_epoch0_us`` 默认与 ``epoch0_us`` 相同（即 Runtime 与激活年锚一致 ——
    这是唯一能产出"可推进世界"的组合）。
    """
    return ActivationRequest(
        world_id=world_id, seed_dir=Path(seed_dir), epoch0_us=epoch0_us,
        initial_blessed_tick=initial_blessed_tick,
        runtime_epoch0_us=(epoch0_us if runtime_epoch0_us is None
                           else runtime_epoch0_us),
        operator="M6_TEST", **kwargs)


def year_tick(years: int) -> int:
    """整年 tick（满足冻结 planner 的整年对齐不变量）。"""
    return years * TICKS_PER_BLESSED_YEAR


def world_counts(session_factory) -> dict:
    """合成世界的 canonical 计数（激活断言统一口径）。"""
    with session_factory() as s:
        rows = s.execute(select(WorldRuntime)).scalars().all()
        events = s.execute(select(WorldEvent)).scalars().all()
        genesis = [e for e in events
                   if e.event_type == GENESIS_EVENT_TYPE]
        active = [r for r in rows if r.runtime_status == "ACTIVE"]
        rates = s.execute(text(
            "SELECT ratio_id, blessed_effective_from_tick "
            "FROM time_ratio_history ORDER BY ratio_id")).all()
        locks = s.execute(select(RuntimeLock)).scalars().all()
        runs = int(s.execute(text("SELECT COUNT(*) FROM simulation_run")).scalar())
        ckpts = int(s.execute(text(
            "SELECT COUNT(*) FROM simulation_checkpoints")).scalar())
    return {
        "world_runtime_rows": len(rows),
        "active_worlds": len(active),
        "world_events": len(events),
        "genesis_events": len(genesis),
        "genesis_uids": [e.event_uid for e in genesis],
        "seed_consumption_count": len(genesis),
        "rate_rows": len(rates),
        "rate_blessed_starts": [r[1] for r in rates],
        "runtime_lock_rows": len(locks),
        "simulation_runs": runs,
        "checkpoints": ckpts,
    }


def business_row_counts(session_factory) -> dict:
    """M2/M3 业务表计数（A9：激活不得物化任何实例数据）。"""
    tables = ("settlements", "population_groups", "persons", "households",
              "lineages", "institutions", "resource_nodes", "resource_stocks",
              "production_state", "economic_pressure_state", "ecology_zones",
              "ecology_state", "ecology_feedback_state",
              "settlement_social_state", "social_feedback_state",
              "tribulation_episodes", "tribulation_profiles",
              "tribulation_schedules", "industries", "ecological_regions",
              "world_state_changes", "timeline_entries", "narrative_records")
    out: dict[str, int] = {}
    with session_factory() as s:
        for t in tables:
            try:
                out[t] = int(s.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar())
            except Exception:  # noqa: BLE001
                out[t] = -1  # 表不存在（schema 差异）
    return out


def genesis_event(session_factory):  # noqa: ANN001
    with session_factory() as s:
        return s.execute(
            select(WorldEvent).where(WorldEvent.event_type == GENESIS_EVENT_TYPE)
            .order_by(WorldEvent.id).limit(1)).scalar_one_or_none()
