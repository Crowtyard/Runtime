"""M6D.3 §6 — explain the candidate byte differences (telemetry vs deterministic)."""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tests.golden_baseline import DEFAULT_TELEMETRY_KEYS, strip_telemetry  # noqa: E402

DOC = json.loads((ROOT / "reports" /
                  "M6D3_BASELINE_REFREEZE_CANDIDATES.json").read_text(
    encoding="utf-8"))
RUN1 = pathlib.Path(DOC["run1"]["dir"])
RUN2 = pathlib.Path(DOC["run2"]["dir"])


def walk(a, b, path="$", out=None):
    out = [] if out is None else out
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b)):
            walk(a.get(key), b.get(key), "%s.%s" % (path, key), out)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append((path, "list len %d != %d" % (len(a), len(b))))
        else:
            for i, (x, y) in enumerate(zip(a, b)):
                walk(x, y, "%s[%d]" % (path, i), out)
    elif a != b:
        out.append((path, "%r != %r" % (a, b)))
    return out


for name, row in DOC["comparison"].items():
    if row["equal"]:
        continue
    f1 = RUN1 / (name + ".dumped.json")
    f2 = RUN2 / (name + ".dumped.json")
    d1 = json.loads(f1.read_text(encoding="utf-8"))
    d2 = json.loads(f2.read_text(encoding="utf-8"))
    diffs = walk(d1, d2)
    s1 = strip_telemetry(d1, DEFAULT_TELEMETRY_KEYS)
    s2 = strip_telemetry(d2, DEFAULT_TELEMETRY_KEYS)
    print("=" * 90)
    print(name)
    print("  byte-level diffs:", len(diffs))
    for path, detail in diffs:
        key = path.rsplit(".", 1)[-1]
        tag = "TELEMETRY" if key in DEFAULT_TELEMETRY_KEYS else "DETERMINISTIC"
        print("    [%s] %s : %s" % (tag, path, detail))
    print("  telemetry-stripped equal:", s1 == s2)
    if s1 != s2:
        for path, detail in walk(s1, s2):
            print("    DET-DIFF %s : %s" % (path, detail))
print("=" * 90)
print("TELEMETRY_KEYS", sorted(DEFAULT_TELEMETRY_KEYS))
