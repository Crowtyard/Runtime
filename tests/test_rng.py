"""测试 5-6：RNG 确定性 + 子系统隔离 + scope/version/world 隔离 + 调用数隔离。"""
from __future__ import annotations

from services.rng_service import RngService, derive_seed


def _draws(service, subsystem, period_tick, n=3, scope="WORLD"):
    return [service.stream(subsystem=subsystem, blessed_period_tick=period_tick,
                           entity_scope=scope).randint(0, 10**6)
            for _ in range(n)]


def test_rng_deterministic():
    a = RngService(world_id="W", simulation_version="v1")
    b = RngService(world_id="W", simulation_version="v1")
    sa = a.stream(subsystem="DEMOGRAPHY", blessed_period_tick=10)
    sb = b.stream(subsystem="DEMOGRAPHY", blessed_period_tick=10)
    assert [sa.randint(0, 10**6) for _ in range(5)] == \
        [sb.randint(0, 10**6) for _ in range(5)]


def test_rng_subsystem_isolated():
    """增加 ECONOMY 的随机调用不改变 DEMOGRAPHY 流。"""
    svc = RngService(world_id="W", simulation_version="v1")
    d1 = _draws(svc, "DEMOGRAPHY", 3_000_000)
    _ = svc.stream(subsystem="ECONOMY", blessed_period_tick=3_000_000).randint(0, 10**6)
    d2 = _draws(svc, "DEMOGRAPHY", 3_000_000)
    assert d1 == d2


def test_rng_cross_subsystem_callcount_isolation():
    """修改 ECONOMY 调用数量不得改变 DEMOGRAPHY/RESOURCE/TRIBULATION 随机流。"""
    svc = RngService(world_id="W", simulation_version="v1")
    baseline = {
        sub: _draws(svc, sub, 3_650_000)
        for sub in ("DEMOGRAPHY", "RESOURCE", "TRIBULATION")
    }
    # 大量消耗 ECONOMY 流
    econ = svc.stream(subsystem="ECONOMY", blessed_period_tick=3_650_000)
    for _ in range(50):
        econ.randint(0, 10**6)
    for sub in ("DEMOGRAPHY", "RESOURCE", "TRIBULATION"):
        assert _draws(svc, sub, 3_650_000) == baseline[sub]


def test_rng_seed_derivation_differs_by_field():
    s1 = derive_seed(world_id="W", simulation_version="v1", blessed_period_tick=1,
                     subsystem="SOCIAL")
    s2 = derive_seed(world_id="W", simulation_version="v1", blessed_period_tick=1,
                     subsystem="TRIBULATION")
    s3 = derive_seed(world_id="W", simulation_version="v1", blessed_period_tick=2,
                     subsystem="SOCIAL")
    assert len({s1, s2, s3}) == 3


def test_rng_scope_isolation():
    svc = RngService(world_id="W", simulation_version="v1")
    w1 = svc.stream(subsystem="RESOURCE", blessed_period_tick=1_000_000,
                    entity_scope="EAST")
    w2 = svc.stream(subsystem="RESOURCE", blessed_period_tick=1_000_000,
                    entity_scope="WEST")
    assert [w1.randint(0, 10**6) for _ in range(3)] != \
        [w2.randint(0, 10**6) for _ in range(3)]


def test_rng_simulation_version_separation():
    """simulation_version 变更 = 全新随机空间（旧版本流不得污染新版本）。"""
    a = RngService(world_id="W", simulation_version="v1")
    b = RngService(world_id="W", simulation_version="v2")
    assert _draws(a, "DEMOGRAPHY", 3_000_000) != _draws(b, "DEMOGRAPHY", 3_000_000)


def test_rng_world_separation():
    a = RngService(world_id="W1", simulation_version="v1")
    b = RngService(world_id="W2", simulation_version="v1")
    assert _draws(a, "TRIBULATION", 3_000_000) != _draws(b, "TRIBULATION", 3_000_000)
