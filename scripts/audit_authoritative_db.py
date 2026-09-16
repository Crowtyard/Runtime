"""M6C.1B — 正式库权威解析审计（owner §4/§5/§6）。

只读：不写任何文件、不改任何 DB、不激活、不物化。
正式库 = `<plugin_data>/runtime_state/authoritative_db.json` 指向的 DB
（生产架构：`plugin_shell/runtime_host.py:212-225` 写出该 marker）。

用法（**必须显式给出** plugin_data 目录；脚本自身不硬编码任何路径）：
    python scripts/audit_authoritative_db.py --plugin-data-dir <path>
                                             [--extra-root <path>]... [--json]

退出码：0 = RESOLVED/PASS；2 = AMBIGUOUS（FAIL CLOSED）；3 = ABSENT（无可审计正式库）。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tests.formal_db import (  # noqa: E402
    AuthoritativeDbAmbiguous, redline_report)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plugin-data-dir", required=True,
                    help="Runtime plugin_data 目录（显式给出；不硬编码）")
    ap.add_argument("--extra-root", action="append", default=[],
                    help="额外的发现根（仅用于检测非权威副本，不用于选择）")
    ap.add_argument("--explicit", default=None,
                    help="显式正式库路径（等价 BLR_FORMAL_DB_PATH，须与 marker 一致）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    try:
        report = redline_report(plugin_data_dir=args.plugin_data_dir,
                                extra_roots=args.extra_root,
                                explicit_path=args.explicit)
    except AuthoritativeDbAmbiguous as exc:
        print("AUTHORITATIVE_DB_RESOLUTION = AMBIGUOUS")
        print("FAIL_CLOSED = TRUE（禁止 activation / materialization / formal mutation）")
        print(f"REASON = {exc}")
        return 2

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        for key, value in report.items():
            if key == "NON_AUTHORITATIVE_DBS":
                print(f"{key} = {len(value)}")
                for item in value:
                    print("    - path = %s" % item["path"])
                    print("      world_runtime_rows = %s (consulted_for_redline=%s)"
                          % (item["world_runtime_rows"], item["consulted_for_redline"]))
                    print("      sha256 = %s" % item["sha256"])
            else:
                print(f"{key} = {value}")
    if report["AUTHORITATIVE_DB_RESOLUTION"] != "PASS":
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
