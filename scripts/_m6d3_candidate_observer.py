"""M6D.3 §4/§6 — READ-ONLY candidate observer (pytest plugin).

Purpose: capture the artifact a golden-baseline test *computed* (the candidate) at
the moment the deterministic comparison fails, so that the NEW side of the
authorized refreeze can be recorded and its two-run determinism proven — WITHOUT
writing anything into tests/baselines and WITHOUT altering GB10 behaviour.

The comparison itself is left untouched: the original function's AssertionError is
always re-raised, so normal pytest semantics are unchanged.

Usage:
  set M6D3_CANDIDATE_OUT=%TEMP%\m6d3_candidates_run1
  python -m pytest -p _m6d3_candidate_observer <artifact test nodes>
  (PYTHONPATH must include scripts/)
"""
from __future__ import annotations

import json
import os
import pathlib

_OUT: pathlib.Path | None = None


def pytest_configure(config):
    global _OUT
    raw = os.environ.get("M6D3_CANDIDATE_OUT")
    if not raw:
        return
    _OUT = pathlib.Path(raw)
    _OUT.mkdir(parents=True, exist_ok=True)

    from tests import golden_baseline as gb
    original = gb.assert_deterministic_equal

    def observed(golden, candidate, *, label, telemetry_keys=None, **kw):
        try:
            if telemetry_keys is None:
                return original(golden, candidate, label=label, **kw)
            return original(golden, candidate, label=label,
                            telemetry_keys=telemetry_keys, **kw)
        except AssertionError as exc:
            safe = label.replace("/", "__").replace("\\", "__")
            doc = {
                "label": label,
                "golden": golden,
                "candidate": candidate,
                "assertion": str(exc).splitlines()[0],
            }
            (_OUT / (safe + ".json")).write_text(
                json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True),
                encoding="utf-8", newline="\n")
            # 观察用：候选按 dump_artifact 的写法另存，便于计算 NEW sha256
            (_OUT / (safe + ".dumped.json")).write_text(
                json.dumps(candidate, ensure_ascii=False, indent=1),
                encoding="utf-8")
            if os.environ.get("M6D3_CANDIDATE_CONTINUE") == "1":
                # 诊断模式：继续收集其它文件的候选（该模式下比较不再是门禁，
                # 仅用于采集；普通 pytest / scripts/update_baselines.py 不受影响）
                return None
            raise

    gb.assert_deterministic_equal = observed
