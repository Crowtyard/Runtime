"""M6C.2 §4 — verify the production cohort primitive matches the ratified
RA-COHORT-001 v1.1 distribution used for the owner payload.

Compares:
  production: services/activation/bootstrap_canon.py::cohort_counts (v1.0 label)
  audited   : scripts/m6c1c_sweep.py::cohort_distribution (RA-COHORT-001 v1.1,
              the implementation used to produce the approved payload)

over the approved inputs (61 buckets, mortality 1/60) and the RA-ALLOC-001 cell
totals of the approved allocation matrix.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys
from fractions import Fraction

ROOT = pathlib.Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from XiaoguangBlessedLandRuntime.services.activation import (  # noqa: E402
    bootstrap_canon as BC)

spec = importlib.util.spec_from_file_location(
    "m6c1c_sweep", ROOT / "scripts" / "m6c1c_sweep.py")
sweep = importlib.util.module_from_spec(spec)
sys.modules["m6c1c_sweep"] = sweep
spec.loader.exec_module(sweep)

BUCKETS = 61
MORTALITY = Fraction(1, 60)
MATRIX = BC.allocate((4000, 3000, 2500, 2500), (2000,) * 4 + (500,) * 8)

mismatches = []
checked = 0
for row in MATRIX:
    for total in row:
        a = list(BC.cohort_counts([MORTALITY] * BUCKETS, total))
        b = list(sweep.cohort_distribution(BUCKETS, MORTALITY, total))
        checked += 1
        if a != b:
            mismatches.append({"total": total, "production": a[:8],
                               "audited_v11": b[:8],
                               "sum_production": sum(a), "sum_audited": sum(b)})
print("CELLS_CHECKED", checked)
print("MISMATCHES", len(mismatches))
for m in mismatches[:5]:
    print("  ", m)
print("PRODUCTION_RULE", BC.RULE_COHORT_ID, BC.RULE_COHORT_VERSION)
print("ALLOCATION_DIGEST", BC.allocation_digest(MATRIX))
print("COLUMN_TOTALS", BC.column_totals(MATRIX))
print("ROW_TOTALS", BC.row_totals(MATRIX))
print("V11_MATCHES_PRODUCTION =", not mismatches)
