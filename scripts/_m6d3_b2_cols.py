"""M6D.3 B2 spike — SimulationCheckpoint columns (no world build)."""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from XiaoguangBlessedLandRuntime.database.models_core import (  # noqa: E402
    SimulationCheckpoint)

print("columns:", [c.name for c in SimulationCheckpoint.__table__.columns])
