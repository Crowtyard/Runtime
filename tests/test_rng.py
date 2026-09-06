"""测试 5-6：RNG 确定性 + 子系统隔离。"""
from __future__ import annotations

from services.rng_service import RngService, derive_seed


def test_rng_deterministic():
    a = RngService(world_id="W", simulation_version="v1")
    b = RngService(world_id="W", simulation_version="v1")
    sa = a.stream(subsystem="DEMOGRAPHY", blessed_period=10)
    sb = b.stream(subsystem="DEMOGRAPHY", blessed_period=10)
    assert [sa.randint(0, 10**6) for _ in range(5)] == \
        [sb.randint(0, 10**6) for _ in range(5)]


def test_rng_subsystem_isolated():
    """增加 ECONOMY 的随机调用不改变 DEMOGRAPHY 流。"""
    svc = RngService(world_id="W", simulation_version="v1")
    d1 = [svc.stream(subsystem="DEMOGRAPHY", blessed_period=3).randint(0, 10**6)
          for _ in range(3)]
    # 消耗一次 ECONOMY 流
    _ = svc.stream(subsystem="ECONOMY", blessed_period=3).randint(0, 10**6)
    d2 = [svc.stream(subsystem="DEMOGRAPHY", blessed_period=3).randint(0, 10**6)
          for _ in range(3)]
    assert d1 == d2


def test_rng_seed_derivation_differs_by_field():
    s1 = derive_seed(world_id="W", simulation_version="v1", blessed_period=1,
                     subsystem="SOCIAL")
    s2 = derive_seed(world_id="W", simulation_version="v1", blessed_period=1,
                     subsystem="TRIBULATION")
    s3 = derive_seed(world_id="W", simulation_version="v1", blessed_period=2,
                     subsystem="SOCIAL")
    assert len({s1, s2, s3}) == 3


def test_rng_scope_isolation():
    svc = RngService(world_id="W", simulation_version="v1")
    w1 = svc.stream(subsystem="RESOURCE", blessed_period=1, entity_scope="EAST")
    w2 = svc.stream(subsystem="RESOURCE", blessed_period=1, entity_scope="WEST")
    assert [w1.randint(0, 10**6) for _ in range(3)] != \
        [w2.randint(0, 10**6) for _ in range(3)]
