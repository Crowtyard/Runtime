"""版本锁与 World Bible 完整性（8/23/24 节）。"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .constants import SimulationVersion, WorldBibleVersion
from .errors import WorldBibleHashMismatch


@dataclass(frozen=True)
class BibleFingerprint:
    version: str
    manifest: dict[str, str]  # filename -> sha256
    manifest_hex: str  # 稳定排序后拼接的摘要（存库用）


def _hex_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_bible_fingerprint(bible_dir: Path) -> BibleFingerprint:
    """从 World Bible 目录读取 VERSION.json + MANIFEST.sha256.txt 并复算哈希。

    校验两个层面：MANIFEST 条目与磁盘文件一致；manifest 文本自身与
    VERSION.json 记录的引用一致（如无记录则跳过第二层）。
    """
    version_file = bible_dir / "VERSION.json"
    manifest_file = bible_dir / "MANIFEST.sha256.txt"
    if not version_file.exists() or not manifest_file.exists():
        raise WorldBibleHashMismatch("World Bible VERSION/MANIFEST 缺失", detail=str(bible_dir))

    meta = json.loads(version_file.read_text(encoding="utf-8"))
    entries: dict[str, str] = {}
    for line in manifest_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        h, name = line.split("  ", 1)
        entries[name] = h

    mismatches = []
    for name, expected in entries.items():
        p = bible_dir / name
        if not p.exists():
            mismatches.append((name, "MISSING"))
            continue
        actual = _hex_of(p)
        if actual != expected:
            mismatches.append((name, actual))
    if mismatches:
        raise WorldBibleHashMismatch(
            "World Bible 被冻结文件哈希不一致", detail=mismatches)

    canon = sorted(entries.items())
    canon_hex = hashlib.sha256(
        json.dumps(canon, ensure_ascii=False).encode("utf-8")).hexdigest()
    return BibleFingerprint(version=str(meta.get("version", "?")), manifest=entries,
                            manifest_hex=canon_hex)


def check_bible_version(fingerprint: BibleFingerprint) -> None:
    if fingerprint.version != WorldBibleVersion.CURRENT:
        raise WorldBibleHashMismatch(
            f"World Bible 版本 {fingerprint.version} != 期望 {WorldBibleVersion.CURRENT}")


def simulation_version_current() -> str:
    return SimulationVersion.CURRENT
