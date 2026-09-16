"""M6C.1D smoke: build the synthetic world, self-check, then run 4 blessed years
through the REAL production pipeline.  Prints raw results; no pass/fail claims.
"""
from __future__ import annotations

import pathlib
import sys
import tempfile
import traceback

ROOT = pathlib.Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tests import m6c1d_runner as R  # noqa: E402
from tests import m6c1d_support as S  # noqa: E402
from XiaoguangBlessedLandRuntime.services.simulation.m3a_runner import (  # noqa: E402
    run_m3a_world)

work = pathlib.Path(tempfile.mkdtemp(prefix="m6c1d_smoke_"))
try:
    env = R.build_world(work, tag="smoke", via="direct")
    print("ACTIVATION_OUTCOME", getattr(env["outcome"], "outcome", env["outcome"]))
    check = R.self_check(env)
    for key, value in check.items():
        print("SELF_CHECK", key, "=", value)
    if not check["SELF_CHECK"]:
        print("SMOKE_STOP = SELF_CHECK_FAILED")
        raise SystemExit(2)
    coordinator = S.build_coordinator()
    report = run_m3a_world(env["factory"], coordinator=coordinator,
                           world_id=R.WORLD_ID, epoch0_us=R.EPOCH0_US, years=4)
    print("M3A_REPORT_FIELDS", [f for f in dir(report) if not f.startswith("_")])
    for field in ("years", "runs_count", "total_splits", "final_state_hash",
                  "event_hash", "event_history_hash", "state_hash", "metrics"):
        if hasattr(report, field):
            value = getattr(report, field)
            print("M3A_REPORT", field, "=", str(value)[:200])
    with env["factory"]() as session:
        from sqlalchemy import func, select
        from XiaoguangBlessedLandRuntime.database.models_world import (
            PopulationGroup)
        total = int(session.scalar(select(func.coalesce(
            func.sum(PopulationGroup.count), 0))) or 0)
        by_species = {sp: int(session.scalar(select(func.coalesce(
            func.sum(PopulationGroup.count), 0)).where(
                PopulationGroup.species == sp)) or 0) for sp, _ in S.SPECIES}
        rows = int(session.scalar(select(func.count())
                                  .select_from(PopulationGroup)) or 0)
    print("POP_T4", total, "ROWS", rows, "BY_SPECIES", by_species)
except SystemExit:
    raise
except Exception:
    print("SMOKE_EXCEPTION")
    traceback.print_exc()
    raise SystemExit(3)
