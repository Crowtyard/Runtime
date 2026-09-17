"""M6D.3 lane B — compare the E-B-v2 calibration artifact against the M6D.2 integrated run."""
from __future__ import annotations

import glob
import json
import os
import pathlib
import sys

PATHS = sys.argv[1:] or [
    os.path.expandvars(r"%TEMP%\m6c1d_ebv2_100.json"),
    os.path.expandvars(r"%TEMP%\m6c1d_ebv2_300.json"),
    os.path.expandvars(r"%TEMP%\m6d2_5ohuj6y7\RUN1_continuous.json"),
]
KEYS = ("habitat_quality", "ecological_stress", "population_pressure",
        "extraction_pressure", "production_pressure", "depletion_pressure",
        "external_pressure", "regeneration_capacity", "degradation_carry",
        "recovery_carry")


def show(path: str) -> None:
    if not os.path.exists(path):
        print("MISSING", path)
        return
    doc = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    print("=" * 100)
    print("FILE", path)
    print("  top keys:", sorted(doc.keys()))
    for k in ("via", "drop_kind", "birth_rate", "history_builder", "world_id",
              "python_hashseed", "final_state_hash", "overrides"):
        if k in doc:
            print("  %s = %s" % (k, str(doc[k])[:110]))
    sc = doc.get("self_check") or {}
    if sc:
        print("  self_check: SELF_CHECK=%s nodes=%s profiles=%s stocks=%s "
              "ecology_state=%s" % (sc.get("SELF_CHECK"), sc.get("RESOURCE_NODE_ROWS"),
                                    sc.get("RESOURCE_PROFILE_ROWS"),
                                    sc.get("RESOURCE_STOCK_ROWS"),
                                    sc.get("ECOLOGY_STATE_ROWS")))
    cps = doc.get("checkpoints") or {}
    for name in sorted(cps, key=lambda s: int(s[1:]) if s[1:].isdigit() else 0):
        payload = cps[name] or {}
        eco = payload.get("ecology") or {}
        state = payload.get("state_hash")
        print("  %-6s state=%s" % (name, str(state)[:16]))
        for key in KEYS:
            if key in eco:
                print("        %-24s %s" % (key, eco[key]))


for p in PATHS:
    show(p)
print("=" * 100)
print("candidate artifacts on disk:")
for pat in (os.path.expandvars(r"%TEMP%\m6c1d_*.json"),
            os.path.expandvars(r"%TEMP%\m6d*_*.json")):
    for f in sorted(glob.glob(pat)):
        print("   ", f)
