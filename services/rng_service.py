"""DETERMINISTIC_RNG_SERVICE（15/16 节）。

随机流派生自：world_seed / simulation_version / subsystem / blessed_period / entity_scope。
每个 subsystem 独立 RNG Stream —— 不同子系统互不消耗同一随机序列；
增加某子系统的随机调用不得改变其它子系统的结果。
禁止使用全局 random.seed()/random 实例做世界模拟随机。
"""
from __future__ import annotations

import hashlib
import random

SUBSYSTEMS = ("DEMOGRAPHY", "RESOURCE", "ECONOMY", "ECOLOGY",
              "SOCIAL", "TRIBULATION", "DISTURBANCE")


def derive_seed(*, world_id: str, simulation_version: str,
                blessed_period: int, subsystem: str, entity_scope: str = "WORLD") -> int:
    if subsystem not in SUBSYSTEMS:
        raise ValueError(f"未知 subsystem: {subsystem}")
    payload = "|".join([world_id, simulation_version, str(blessed_period),
                        subsystem, entity_scope]).encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


class RngStream:
    """每 (subsystem, entity_scope) 独立流；可 replay（同 seed 同序列）。"""

    def __init__(self, seed: int):
        self._rng = random.Random(seed)
        self.seed = seed

    def uniform(self, a: float = 0.0, b: float = 1.0) -> float:
        return self._rng.uniform(a, b)

    def randint(self, a: int, b: int) -> int:
        return self._rng.randint(a, b)

    def choice(self, seq):  # noqa: ANN001
        return self._rng.choice(seq)

    def chance(self, p: float) -> bool:
        return self._rng.random() < p


class RngService:
    """按 subsystem 提供独立流；每个 (period, subsystem, scope) 幂等派生。"""

    def __init__(self, *, world_id: str, simulation_version: str):
        self.world_id = world_id
        self.simulation_version = simulation_version

    def stream(self, *, subsystem: str, blessed_period: int,
               entity_scope: str = "WORLD") -> RngStream:
        seed = derive_seed(world_id=self.world_id,
                           simulation_version=self.simulation_version,
                           blessed_period=blessed_period,
                           subsystem=subsystem, entity_scope=entity_scope)
        return RngStream(seed)
