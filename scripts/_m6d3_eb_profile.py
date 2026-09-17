"""M6D.3 lane B — dump the audited E-B ecology payload and the effective profile."""
from __future__ import annotations

import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tests import m6c1d_support as S  # noqa: E402

print("PACKET_DATA", S.PACKET_DATA)
for key, label in (("E1", "E-B"), ("E1", "E-A")):
    try:
        cand = S.candidate(key, label)
        print("%s/%s VALUES = %s" % (key, label, json.dumps(
            cand.get("VALUES"), ensure_ascii=False)))
    except Exception as exc:
        print("%s/%s ERR %s" % (key, label, exc))
print("env M6C1D_ECOLOGY_SENSITIVITY =",
      os.environ.get("M6C1D_ECOLOGY_SENSITIVITY", "<unset>"))
prof = S.ecology_profile()
print("EFFECTIVE profile: recovery_rate=%s recovery_ceiling=%s sensitivity=%s "
      "pop_pressure_per_person=%s weights=%s thresholds=%s"
      % (prof.recovery_rate, prof.recovery_ceiling, prof.sensitivity,
         prof.pop_pressure_per_person, prof.pressure_weights, prof.thresholds))
