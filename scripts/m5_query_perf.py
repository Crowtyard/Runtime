#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""M5 Query 性能测量（§60）：synthetic 300y DB 上各查询 p50/p95/max。

目标不是极端优化：普通聊天世界查询不应每次扫描全部历史。
只读；不动任何 golden baseline / 正式世界 / Seed。
"""
from __future__ import annotations

import statistics
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO.parent))
sys.path.insert(0, str(REPO))

from tests.test_m3_integrated_long import (_fresh_m3, _m3_run,  # noqa: E402
                                           M3_LONG_WORLD_IDS)
from XiaoguangBlessedLandRuntime.services.query import (  # noqa: E402
    WorldQueryService)


def bench(fn, n: int = 7) -> dict:
    fn()  # warm-up
    ts = []
    for _ in range(n):
        t = time.perf_counter()
        fn()
        ts.append((time.perf_counter() - t) * 1000)
    ts_sorted = sorted(ts)
    return {"p50_ms": round(statistics.median(ts), 2),
            "p95_ms": round(ts_sorted[min(n - 1, int(n * 0.95))], 2),
            "max_ms": round(max(ts), 2)}


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="m5_perf_"))
    env = _fresh_m3(tmp, 1, M3_LONG_WORLD_IDS[0])
    _m3_run(env, years=300)
    svc = WorldQueryService(session_factory=env["factory"],
                            world_id=M3_LONG_WORLD_IDS[0])
    print("=== M5 query latency on synthetic 300y DB (ms) ===")
    results = {}
    results["runtime_status"] = bench(svc.get_runtime_status)
    results["population_summary"] = bench(svc.get_population_summary)
    results["world_snapshot"] = bench(svc.get_world_snapshot)
    results["recent_changes_30y"] = bench(
        lambda: svc.get_changes_between_ticks(start_tick=270_000_000,
                                              end_tick=300_000_000))
    results["history_timeline"] = bench(svc.get_history_timeline)
    results["explain_state"] = bench(
        lambda: svc.explain_state(entity_type="ecology_state",
                                  entity_id=_first_eco(svc),
                                  field="habitat_quality"))
    for name, r in results.items():
        print(f"{name:24s} p50={r['p50_ms']:>9} p95={r['p95_ms']:>9} "
              f"max={r['max_ms']:>9}")
    return 0


def _first_eco(svc) -> str:
    from sqlalchemy import select
    from XiaoguangBlessedLandRuntime.database.models_world import EcologyState
    with svc.session_factory() as s:
        z = s.execute(select(EcologyState).where(
            EcologyState.world_id == svc.world_id)).scalars().first()
    return str(z.id)


if __name__ == "__main__":
    raise SystemExit(main())
