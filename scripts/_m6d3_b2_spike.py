"""M6D.3 B2 spike — does the M3a world expose an authoritative state hash to the
query service, and where does it live?  (READ-ONLY diagnostic.)"""
from __future__ import annotations

import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from sqlalchemy import select, text  # noqa: E402

from tests.test_m3a_tribulation import _fresh_m3a, _run  # noqa: E402
from XiaoguangBlessedLandRuntime.database.models_core import (  # noqa: E402
    SimulationCheckpoint)
from XiaoguangBlessedLandRuntime.services.query import WorldQueryService  # noqa: E402
from XiaoguangBlessedLandRuntime.services.simulation.mini_world import (  # noqa: E402
    MINI_WORLD_ID)

tmp = pathlib.Path(tempfile.mkdtemp(prefix="m6d3_b2_spike_"))
env = _fresh_m3a(tmp, 900)
rep = _run(env, years=10)
print("world_id", MINI_WORLD_ID, "report state hash", str(rep.final_state_hash)[:20])
with env["factory"]() as s:
    tables = [r[0] for r in s.execute(text(
        "SELECT name FROM sqlite_master WHERE type='table'")).all()]
    print("checkpoint tables:", [t for t in tables if "checkpoint" in t])
    try:
        rows = s.execute(select(SimulationCheckpoint)).scalars().all()
        print("SimulationCheckpoint rows:", len(rows))
        for row in rows[:3]:
            print("   tick", row.blessed_tick, "hash",
                  str(getattr(row, "world_state_hash", None))[:24])
    except Exception as exc:  # noqa: BLE001
        print("SimulationCheckpoint query error:", exc)
svc = WorldQueryService(session_factory=env["factory"], world_id=MINI_WORLD_ID)
print("fingerprint:", svc._fingerprint())
