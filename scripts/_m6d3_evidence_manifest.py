"""M6D.3 §1 — M6D.2 forensic evidence manifest (READ-ONLY; never modifies the DBs).

Writes filename / size / sha256 / role for every M6D.2 world DB and marks the set
M6D2_FORENSIC_EVIDENCE_READ_ONLY = TRUE.

Usage: python scripts/_m6d3_evidence_manifest.py [--root DIR] [--out JSON]
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import pathlib

ROLES = {
    "run1": "RUN1_CONTINUOUS_300Y_REFERENCE (determinism reference, hashseed unpinned)",
    "run2": "RUN2_CONTINUOUS_300Y_DETERMINISM_REPLICA (independent process, hashseed unpinned)",
    "run3": "RUN3_RESTART_CHAIN (0->100y @seed0 written here, then NEW process 100->300y @seed42 continued the same file)",
}


def sha256_of(path: str, chunk: int = 1 << 22) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    default_root = os.path.expandvars(r"%TEMP%\m6d2_5ohuj6y7")
    ap.add_argument("--root", default=default_root)
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    root = pathlib.Path(args.root)
    entries = []
    for path in sorted(glob.glob(str(root / "run*" / "m6c1d_world.db"))):
        stage = pathlib.Path(path).parent.name
        entries.append({
            "filename": str(pathlib.Path(path)),
            "relative": "%s/m6c1d_world.db" % stage,
            "size_bytes": os.path.getsize(path),
            "sha256": sha256_of(path),
            "role": ROLES.get(stage, "UNKNOWN"),
        })
    for path in sorted(glob.glob(str(root / "*.json"))):
        entries.append({
            "filename": str(pathlib.Path(path)),
            "relative": pathlib.Path(path).name,
            "size_bytes": os.path.getsize(path),
            "sha256": sha256_of(path),
            "role": "M6D.2 stage artifact (runner/driver output)",
        })
    doc = {
        "packet": "M6D3_M6D2_FORENSIC_EVIDENCE_MANIFEST",
        "root": str(root),
        "M6D2_FORENSIC_EVIDENCE_READ_ONLY": True,
        "note": "这些 DB 不得修改；后续修复验证一律使用新的 temporary DB。",
        "entries": entries,
    }
    print(json.dumps(doc, ensure_ascii=False, indent=1))
    if args.out:
        pathlib.Path(args.out).write_text(
            json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True),
            encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
