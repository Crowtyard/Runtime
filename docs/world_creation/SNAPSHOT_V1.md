# SNAPSHOT_V1（APPROVED）

STATUS = APPROVED　VERSION = SNAPSHOT_V1　OWNER_RATIFIED = TRUE　ENGINE_VERIFIED = TRUE　MATERIALIZATION_SPEC = AUTHORITATIVE　FORMAL_ACTIVATION_ALLOWED = FALSE

SNAPSHOT_V1_SHA256 = `592d23e2606ef9ff223aa264c64176a82a7f87bc1521d80e33152ffbaf3aa8b1`

## 世界

- 初始总人口 **12000**；种族 Hairy Men=4000、Rockmen=3000、Mermen=2500、Mushroommen=2500
- 聚落 12（4 MAIN × 2000 + 8 SATELLITE × 500）；`population_capacity = NULL`（引擎中性，无容量法则）
- RA-ALLOC-001 v1.0 名额矩阵 digest `8dfe3471c1ff9d9c93646df18e4f55335cb93ca634c4afc96a17c86b5b28c457`（列和 [2000, 2000, 2000, 2000, 500, 500, 500, 500, 500, 500, 500, 500]；行和 [4000, 3000, 2500, 2500]）

## 人口

- RA-COHORT-001 **v1.1**（APPROVED_PRODUCTION_BOOTSTRAP_RULE；open-ended final bucket：age ≥ N−1 的 survivor 全部累计到末桶；v1.0 已 SUPERSEDED）
- profile：`birth_rate = 53/1000`、`mortality = 1/60`、`cohort_buckets = 61`、fertile [15, 45]、lifespan 60、capacity NULL
- population_groups 行数 = **2928**（12 × 4 × 61）

## 资源 / 经济

- `FORMAL_RESOURCE_REGISTRY_ENTRIES = 8`、`MATERIALIZED_RESOURCE_PROFILE_ROWS = 7`、`CONSUMPTION_RESOURCE_KINDS = 7`、`RESOURCE_NODE_ROWS = 7`、`RESOURCE_STOCK_ROWS = 84`
- `RESOURCE_SLOT_08`：registered = TRUE / materialized = FALSE / node_count = 0 / stock·demand rows = 0
- 初始库存 = 1 local blessed-year baseline demand（minor units，`quantity_scale = 1000000`）；容量 = 11/10 × ACTUAL_SERVED_ANNUAL_DEMAND (global, not host-local)
- recipes 7 / production_state 84 / economic_pressure 84（exact machine payload）

## 生态 / 社会 / 灾劫

- E-B-v2：zone_count = 1（`ZONE-01`）、sensitivity = `1/279`、recovery_rate = `1/25`、ppp = 1、initial habitat_quality = FULL_QUALITY(1000000)
- S-B：每聚落 2 行 root（state + feedback）共 24 行；occupation / household **不是** authoritative bootstrap root
- T-B：schedules [{'schedule_id': 'SCHEDULE-REGULAR', 'tier': 'REGULAR', 'period_years': 10, 'enabled': True, 'semantic_version': 'formal-1.0'}, {'schedule_id': 'SCHEDULE-MAJOR', 'tier': 'MAJOR', 'period_years': 50, 'enabled': True, 'semantic_version': 'formal-1.0'}, {'schedule_id': 'SCHEDULE-CENTENNIAL', 'tier': 'CENTENNIAL', 'period_years': 100, 'enabled': True, 'semantic_version': 'formal-1.0'}] blessed years；first omen tick = 10000000；effect semantics = post-engine state + delta, exactly once；Materializer **不产生**灾劫效果
- History genesis：`WORLD_SEED_ACTIVATED`，GENESIS_COUNT = 1（由 Activation 事务创建）

## 校验

- `BLOCKED_REQUIRED_FIELDS = 0`、`UNRESOLVED_REQUIRED_FIELDS = 0`、`PLANNING_ONLY_MATERIALIZED_FIELDS = 0`
- `WORKING_NAME_ONLY` 身份（stable technical identity，非 lore display name）：MAIN-01, MAIN-02, MAIN-03, MAIN-04, SAT-01, SAT-02, SAT-03, SAT-04, SAT-05, SAT-06, SAT-07, SAT-08, RESOURCE_SLOT_08

