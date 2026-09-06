"""WORLD_BIBLE_INTEGRITY_CHECK（23/24 节）。

启动时校验冻结文件哈希；失败 → WORLD_BIBLE_HASH_MISMATCH，不静默继续。
World Bible 内容由 Knowledge 层管理；DB 只存 version + manifest hash，不复制内容。
"""
from __future__ import annotations

from pathlib import Path

from domain.versions import BibleFingerprint, check_bible_version, load_bible_fingerprint
from services.logging_setup import get_logger
from services.repositories import RuntimeRepository

log = get_logger("INTEGRITY")


def verify_bible(bible_dir: Path) -> BibleFingerprint:
    fp = load_bible_fingerprint(bible_dir)
    check_bible_version(fp)
    log.info("world bible integrity OK version=%s files=%d", fp.version, len(fp.manifest))
    return fp


def verify_runtime_binds_bible(repo: RuntimeRepository, fp: BibleFingerprint) -> None:
    """DB 记录的 bible 版本/manifest hash 必须与冻结文件一致（防双套真相）。

    hash 列必填且严格相等：空串/缺失也视为不一致（M0 DSH QA 收紧）。
    """
    from domain.errors import WorldBibleHashMismatch
    row = repo.get()
    if row is None:
        return
    if row.world_bible_version != fp.version:
        raise WorldBibleHashMismatch(
            f"DB 记录 bible {row.world_bible_version} != 冻结 {fp.version}")
    if row.world_bible_manifest_hash != fp.manifest_hex:
        raise WorldBibleHashMismatch(
            f"DB manifest hash {row.world_bible_manifest_hash!r} != 冻结 {fp.manifest_hex}")
