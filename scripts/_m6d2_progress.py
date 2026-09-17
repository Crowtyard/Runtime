"""M6D.2 — report the blessed tick of every M6D.2 world DB (READ-ONLY)."""
from __future__ import annotations

import glob
import os
import sqlite3

PATTERN = os.path.expandvars(r"%TEMP%\m6d2_*\run*\m6c1d_world.db")
for path in sorted(glob.glob(PATTERN)):
    stage = os.path.basename(os.path.dirname(path))
    root = os.path.basename(os.path.dirname(os.path.dirname(path)))
    try:
        con = sqlite3.connect("file:" + path.replace("\\", "/") + "?mode=ro",
                              uri=True)
        tick = con.execute(
            "SELECT current_blessed_tick FROM world_runtime").fetchone()[0] or 0
        con.close()
        print("%-18s %-5s year=%6.1f MB=%7.1f" % (
            root, stage, tick / 1_000_000, os.path.getsize(path) / 1048576))
    except Exception as exc:  # pragma: no cover
        print("%-18s %-5s ERR %s" % (root, stage, exc))
