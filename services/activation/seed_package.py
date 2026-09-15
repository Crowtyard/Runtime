# -*- coding: utf-8 -*-
"""World Seed 包访问（M6A / A8）—— **唯一**允许读取正式 Seed 的模块。

规则（owner §4，硬约束）：

- 正式 Seed **原值**永不进入日志/异常/报告/Git/测试夹具/聊天/repr/JSON dump；
  允许对外暴露的只有：**指纹 + 版本 + 消费状态**（``public_view()``）；
- Seed 包是**只读输入物料**（immutable canon）：本模块绝不写入、绝不删除、
  绝不"标记已消费"——消费状态记录在正式库（durable truth），因为改写 Seed 字节
  会同时破坏 A8 的 MANIFEST 校验；
- 完整性校验复用既有冻结算法 ``domain.versions.load_bible_fingerprint``
  （VERSION.json + MANIFEST.sha256.txt 逐文件 sha256 复算），**不新写第二套**；
- 只读取包身份层（``VERSION.json``）；**不读取**任何 baseline 数据文件内容。

访问 allowlist：本模块与 ``services/activation/`` 是
``WORLD_SEED_ACTIVATION_ACCESS_ALLOWLIST = M6_ACTIVATION_SERVICE_ONLY`` 的唯一成员
（静态门禁见 ``tests/test_m6_world_seed_safety.py``）。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from ...domain.constants import WorldSeedVersion
from ...domain.errors import WorldBibleHashMismatch, WorldSeedIntegrityError
from ...domain.versions import load_bible_fingerprint

#: Seed 包目录名（相对知识库根）
SEED_PACKAGE_DIRNAME = "world_seed"

#: canon 声明的激活前状态（00_WORLD_SEED_MASTER / WORLD_SEED_INDEX / VERSION.json）
REQUIRED_DECLARED_STATUS = "PREPARED_NOT_ACTIVATED"

VERSION_FILE = "VERSION.json"
MANIFEST_FILE = "MANIFEST.sha256.txt"


@dataclass(frozen=True)
class SeedPackage:
    """Seed 包身份（**只含指纹/版本/状态，绝不含 seed 原值**）。"""

    seed_id: str
    seed_version: str
    declared_status: str
    fingerprint: str        # sha256(MANIFEST.sha256.txt 字节) —— 与 owner 已记录值同口径
    manifest_digest: str    # load_bible_fingerprint 的 canonical 摘要
    manifest_entries: int
    seed_dir: str

    def public_view(self) -> dict:
        """可对外暴露的视图（§4：只允许指纹/版本/状态）。"""
        return {
            "seed_version": self.seed_version,
            "declared_status": self.declared_status,
            "seed_fingerprint": self.fingerprint,
            "seed_manifest_digest": self.manifest_digest,
            "seed_manifest_entries": self.manifest_entries,
        }


def default_seed_dir(project_root: Path | None = None) -> Path:
    """正式 Seed 包默认位置（与 config.settings.bible_dir 同一知识库根）。"""
    root = Path(project_root) if project_root is not None else \
        Path(__file__).resolve().parents[2]
    return (root.parent / "XIAOGUANG_CROW_KB" / SEED_PACKAGE_DIRNAME)


def load_seed_package(seed_dir: Path, *,
                      expected_seed_version: str = WorldSeedVersion.CURRENT,
                      ) -> SeedPackage:
    """校验并加载 Seed 包身份（只读；失败即 ``WorldSeedIntegrityError``）。

    校验顺序（全部通过才返回，任一失败即拒绝 —— fail-closed）：
    1. 包目录 + VERSION.json + MANIFEST.sha256.txt 存在；
    2. MANIFEST 逐文件 sha256 复算（A8；复用冻结算法）；
    3. 包自声明状态必须为 ``PREPARED_NOT_ACTIVATED``（可激活前置条件）；
    4. 包版本必须等于期望版本（防止用错 Seed 激活）。
    """
    seed_dir = Path(seed_dir)
    if not seed_dir.is_dir():
        raise WorldSeedIntegrityError("World Seed 包目录不存在",
                                      detail={"seed_dir": str(seed_dir)})
    if not (seed_dir / VERSION_FILE).exists() or \
            not (seed_dir / MANIFEST_FILE).exists():
        raise WorldSeedIntegrityError(
            "World Seed 包缺少 VERSION.json / MANIFEST.sha256.txt",
            detail={"seed_dir": str(seed_dir)})

    # 2) A8：MANIFEST 逐文件复算（复用 domain.versions 的冻结实现）
    try:
        fp = load_bible_fingerprint(seed_dir)
    except WorldBibleHashMismatch as exc:
        # 只暴露文件名层面的 detail（exc.detail 由 load_bible_fingerprint 生成）
        raise WorldSeedIntegrityError(
            "World Seed MANIFEST 校验失败（A8）",
            detail={"seed_dir": str(seed_dir)}) from exc
    except Exception as exc:  # noqa: BLE001
        # 畸形 MANIFEST 行 / 非法 UTF-8 等：一律归入 Seed 完整性失败
        # （绝不裸抛 ValueError / UnicodeDecodeError 给调用方）
        raise WorldSeedIntegrityError(
            "World Seed MANIFEST 无法解析",
            detail={"seed_dir": str(seed_dir), "error": type(exc).__name__}
        ) from exc

    import json  # 局部导入：本模块的 seed 访问面越小越好

    try:
        meta = json.loads((seed_dir / VERSION_FILE).read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise WorldSeedIntegrityError(
            "World Seed VERSION.json 无法解析",
            detail={"seed_dir": str(seed_dir), "error": type(exc).__name__}
        ) from exc
    if not isinstance(meta, dict):
        raise WorldSeedIntegrityError(
            "World Seed VERSION.json 结构非法（应为对象）",
            detail={"seed_dir": str(seed_dir)})
    seed_version = str(meta.get("version", "") or "")
    declared_status = str(meta.get("status", "") or "")
    seed_id = str(meta.get("seed_id", "") or "")

    if declared_status != REQUIRED_DECLARED_STATUS:
        raise WorldSeedIntegrityError(
            "World Seed 包自声明状态不是可激活状态",
            detail={"declared_status": declared_status,
                    "required": REQUIRED_DECLARED_STATUS})
    if seed_version != expected_seed_version:
        raise WorldSeedIntegrityError(
            "World Seed 版本与期望不一致",
            detail={"seed_version": seed_version,
                    "expected": expected_seed_version})

    fingerprint = hashlib.sha256(
        (seed_dir / MANIFEST_FILE).read_bytes()).hexdigest()
    return SeedPackage(
        seed_id=seed_id,
        seed_version=seed_version,
        declared_status=declared_status,
        fingerprint=fingerprint,
        manifest_digest=fp.manifest_hex,
        manifest_entries=len(fp.manifest),
        seed_dir=str(seed_dir),
    )
