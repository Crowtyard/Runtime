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


class IntegrityError(WorldRuntimeError):
    code = "INTEGRITY_ERROR"
