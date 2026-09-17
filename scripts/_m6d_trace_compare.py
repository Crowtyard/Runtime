"""M6D.1 — compare RNG/entity traces across PYTHONHASHSEED values.

Runs the trace probe in fresh processes:
  H0 / H1            (as-is)
  H0N / H1N          (TEST-ONLY canonical settlement rank)

and reports:
  FIRST_DIFFERENT_ENTITY_POSITION, FIRST_DIVERGENT_RNG_CALL_INDEX, the
  case A / case B classification, and whether the test-only canonical ordering
  removes the divergence.

Usage: python scripts/_m6d_trace_compare.py [--years 1]
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROBE = ROOT / "scripts" / "_m6d_trace_probe.py"


def run(label: str, hashseed: str, years: int, normalize: bool,
        out_dir: pathlib.Path) -> dict:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONHASHSEED"] = hashseed
    out = out_dir / f"{label}.json"
    cmd = [sys.executable, str(PROBE), "--years", str(years), "--out", str(out),
           "--label", label]
    if normalize:
        cmd.append("--normalize-order")
    proc = subprocess.run(cmd, cwd=str(ROOT), env=env, capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          timeout=1800)
    print((proc.stdout or "").strip()[-1500:])
    if proc.returncode != 0:
        print("PROBE_FAILED", label, proc.returncode)
        print((proc.stderr or "")[-3000:])
        raise SystemExit(2)
    return json.loads(out.read_text(encoding="utf-8"))


def first_diff(a: list, b: list) -> tuple[int | None, object, object]:
    for i in range(min(len(a), len(b))):
        if a[i] != b[i]:
            return i, a[i], b[i]
    if len(a) != len(b):
        return min(len(a), len(b)), f"<len {len(a)}>", f"<len {len(b)}>"
    return None, None, None


def summarize(name: str, a: dict, b: dict) -> None:
    print(f"\n=== {name} ===")
    print("per_year_A", json.dumps(a["per_year"], ensure_ascii=False))
    print("per_year_B", json.dumps(b["per_year"], ensure_ascii=False))
    ga = [e for e in a["trace"] if e["kind"] == "GROUP"]
    gb = [e for e in b["trace"] if e["kind"] == "GROUP"]
    pos, ea, eb = first_diff([(g["settlement"], g["species"]) for g in ga],
                             [(g["settlement"], g["species"]) for g in gb])
    print("GROUP_STEPS", len(ga), len(gb))
    print("FIRST_DIFFERENT_ENTITY_POSITION =", pos)
    if pos is not None:
        print("  A:", ea, "| B:", eb)
    sa = [(g["settlement"], g["species"]) for g in ga]
    sb = [(g["settlement"], g["species"]) for g in gb]
    print("SAME_ENTITY_SET =", sorted(sa) == sorted(sb))
    order_a = {e: i for i, e in enumerate(sa)}
    order_b = {e: i for i, e in enumerate(sb)}
    perm = [e for e in order_a if order_a[e] != order_b.get(e)]
    print("ENTITY_POSITION_MISMATCH_COUNT =", len(perm))
    print("FIRST_MOVED_ENTITIES =", perm[:5])

    ra = [e for e in a["trace"] if e["kind"] == "RNG"]
    rb = [e for e in b["trace"] if e["kind"] == "RNG"]
    p, da, db = first_diff([(e["stream"], e["stream_call_index"], e["p"],
                             e["result"]) for e in ra],
                           [(e["stream"], e["stream_call_index"], e["p"],
                             e["result"]) for e in rb])
    print("RNG_DRAWS", len(ra), len(rb))
    print("FIRST_DIVERGENT_RNG_CALL_INDEX =", p)
    if p is not None:
        print("  A:", da, "| B:", db)
    print("RNG_PROBABILITY_SEQUENCE_IDENTICAL =",
          [e["p"] for e in ra] == [e["p"] for e in rb])
    print("RNG_RESULT_SEQUENCE_IDENTICAL =",
          [e["result"] for e in ra] == [e["result"] for e in rb])
    # case A vs B: same draw (p,result) but consumed by a different entity?
    print("RNG_STREAM_START_TAGS_A", [e["stream"] for e in ra[:4]])
    print("RNG_STREAM_START_TAGS_B", [e["stream"] for e in rb[:4]])
    print("STATE_HASH_EQUAL =", a["per_year"] == b["per_year"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, default=1)
    ap.add_argument("--only-normalized", action="store_true")
    args = ap.parse_args()
    out_dir = pathlib.Path(tempfile.mkdtemp(prefix="m6d_tracecmp_"))
    if not args.only_normalized:
        h0 = run("H0", "0", args.years, False, out_dir)
        h1 = run("H1", "1", args.years, False, out_dir)
        summarize("AS-IS  H0 vs H1", h0, h1)
    h0n = run("H0N", "0", args.years, True, out_dir)
    h1n = run("H1N", "1", args.years, True, out_dir)
    summarize("NORMALIZED (test-only canonical settlement rank) H0N vs H1N",
              h0n, h1n)
    print("\nARTIFACT_DIR", out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
