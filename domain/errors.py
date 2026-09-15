"""错误分类（27 节）。禁止业务层 raise 裸 Exception。"""
from __future__ import annotations


class WorldRuntimeError(Exception):
    """基类：全部带 code 的分类错误。"""
    code = "WORLD_RUNTIME_ERROR"

    def __init__(self, message: str, *, detail: object = None):
        super().__init__(message)
        self.message = message
        self.detail = detail


class DatabaseError(WorldRuntimeError):
    code = "DATABASE_ERROR"


class MigrationError(WorldRuntimeError):
    code = "MIGRATION_ERROR"


class WorldBibleHashMismatch(WorldRuntimeError):
    code = "WORLD_BIBLE_HASH_MISMATCH"


class ClockAnomaly(WorldRuntimeError):
    code = "CLOCK_ANOMALY"


class WriterLockConflict(WorldRuntimeError):
    code = "WRITER_LOCK_CONFLICT"


class CheckpointError(WorldRuntimeError):
    code = "CHECKPOINT_ERROR"


class BackupError(WorldRuntimeError):
    code = "BACKUP_ERROR"


class SimulationVersionMismatch(WorldRuntimeError):
    code = "SIMULATION_VERSION_MISMATCH"


class WorldNotActivated(WorldRuntimeError):
    code = "WORLD_NOT_ACTIVATED"


class FencingViolation(WorldRuntimeError):
    """提交前 fencing token 校验失败：本 transaction 的写入授权已被撤销（M1）。"""
    code = "FENCING_VIOLATION"


class IntegrityError(WorldRuntimeError):
    code = "INTEGRITY_ERROR"


class WorldSeedIntegrityError(WorldRuntimeError):
    """World Seed 包完整性/身份校验失败（A8：MANIFEST checksum 必须通过）。

    绝不携带 seed 原值：detail 只允许指纹/版本/文件名层面的信息。
    """
    code = "WORLD_SEED_INTEGRITY_ERROR"


class ActivationRefused(WorldRuntimeError):
    """正式世界激活被拒绝（fail-closed）：前置条件不满足或缺少显式策略输入。

    - 世界已激活 / 已存在正式 world：拒绝且不做任何写入（幂等返回语义见 service）。
    - 缺少 canon 未定义的显式输入（如 initial tick）：拒绝，绝不使用默认值。
    """
    code = "ACTIVATION_REFUSED"


class ActivationOutcomeUnknown(WorldRuntimeError):
    """激活事务提交结果未知且无法从 durable truth 判定（fail-closed）。

    永不盲重试：调用方必须先 reconcile durable truth，再决定 COMMITTED /
    NOT_COMMITTED。本错误表示连 durable truth 都读不到。
    """
    code = "ACTIVATION_OUTCOME_UNKNOWN"
