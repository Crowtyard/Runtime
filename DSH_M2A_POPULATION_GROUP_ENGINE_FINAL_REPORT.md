# DSH_M2A_POPULATION_GROUP_ENGINE_FINAL_REPORT

> 执行方：DSH。阶段：M2A_POPULATION_GROUP_ENGINE（第一个真实模拟引擎）。
> 交付：确定性 Aggregate 人口引擎（零 LLM / 零网络 / 零 wall-clock 真值，
> 无 12,000 Persistent Person）。仅 synthetic `TEST-SPECIES-001`；正式种族
> 保持 UNKNOWN/UNCONFIGURED。基线：M2_PREFLIGHT_HARDENED（137515e，
> tag m2-preflight-hardened，159/159）。
> 完成后 STOP：不进入 M2b、不进入 M3、不激活 World Seed。

## 1. 任务结论
M2a 人口聚合引擎已实现、测试、基线、迁移、终检全部完成：
`M2A_POPULATION_ENGINE_READY`。

## 2. 交付范围（synthetic-only）
只实现 Population Group 聚合层；Persistent Person / Lineage / Institution 不
实现。人口变化不产生 persons 行（PA14/PA15）。正式种族（人/毛民/石人/鲛人/
菇人）一律 UNKNOWN/UNCONFIGURED：引擎遇到即抛
`DemographyProfileUnconfigured`（code `DEMOGRAPHY_UNCONFIGURED`），绝不
静默套用测试参数（PA13）。

## 3. Engine Protocol 契约
`simulate(snapshot, interval, rng, context) -> EngineResult`：引擎只读快照、
只经 `StagedWorld.propose()` 提出 `StateChange`，**零直接 DB commit**
（PA1/PA2）。`ENGINE_ORDER = ("DEMOGRAPHY","RESOURCE","ECONOMY",
"ECOLOGY","SOCIAL")`，DEMOGRAPHY 居首；TRIBULATION=NOT_REGISTERED。

## 4. PopulationGroupEngine
`services/simulation/population.py`：`PopulationGroupEngine`
（engine_id="DEMOGRAPHY"，engine_version="m2a-1"）。注册表
`SPECIES_PROFILES = {"TEST-SPECIES-001": TEST_SPECIES_PROFILE}`。
每行 propose：count + age_advance_carry_ticks + species_profile_ref +
demography_version + updated_blessed_tick。

## 5. SpeciesDemographyProfile
species_id / cohort_buckets=40 / fertile 15–39 / birth_rate=Fraction(3,50) /
mortality_by_bucket（len=40 tuple）/ emigration_rate=Fraction(1,100) /
migration_weights=(1/2,1/2)。全部 Fraction 整数有理率；整数 bucket。

## 6. 正式种族 UNCONFIGURED 语义
registry 缺 key 或 profile 未配置 → `DemographyProfileUnconfigured`，
simulate 报错（带 species_id），不产出任何 propose。06 号文档「石人千余
已知、其余 UNDECIDED」参数不写入本阶段。

## 7. Cohort 模型
bucket 宽 = 1 福地年；`age_cohort` = bucket 序号字符串（canonical 哈希按
整数排序，与行序无关，PA20）；末位 bucket [39,∞) 聚合。亚年区间由
`age_advance_carry_ticks`（BigInteger 整数进位）承载，零浮点累计，任意
SimulationInterval（0.5y/2y/adaptive）有定义。

## 8. Migration a7b3e9f1c5d2（m2a_population_cohorts）
population_groups 增 3 列：`age_advance_carry_ticks`（BigInteger NOT NULL
server_default '0'）、`species_profile_ref`（String64 NULL）、
`demography_version`（String32 NULL）。只 ADD、不 squash：alembic 历史
保持 10 步完整链（7253f352f69e → … → a7b3e9f1c5d2）。
HEAD_REVISION 同步更新：tests/conftest.py、plugin_shell/runtime_host.py
EXPECTED_SCHEMA_HEAD、scripts/migrate_db_to_plugin_data.py。

## 9. Pipeline 顺序（进入引擎语义版本）
age advance（carry 进位）→ deaths → births → migration → reconcile。
抽样顺序：每 group 死亡 bucket 0..N-1 → 出生 → 逐 group 迁移。reconcile
保证 P_INV_12 守恒闭合。

## 10. 出生模型
`expected = fertile_population × birth_rate × capacity_factor`；
`capacity_factor = max(capacity − total, 0) / capacity`（无 capacity 时=1）；
`births = floor(expected) + Bernoulli(余数)`（ctx.rng.chance）。基于人口
结构（fertile buckets），非总数×固定百分比；新生落入 bucket 0。

## 11. 死亡模型
每 bucket：`deaths_b = floor(n_b × q_b) + Bernoulli(余数)`，上限 n_b。
不同 cohort 不同死亡率（profile 表驱动）；external_mortality_modifier
接口预留（灾劫/战争/瘟疫/生态危机不实现）。

## 12. 迁移模型
`emigration = floor(end × rate) + Bernoulli(余数)`（≤ end），从最高 bucket
向下扣减；迁入按 migration_weights 最大余数法整数再分配，进入首个 fertile
bucket（`_allocate_migration`）。不做社会冲突/经济吸引/生态压力。

## 13. RNG
DEMOGRAPHY 独立 substream（derive_seed 含 engine_id + step_start_tick，
rng_schema_version=m1-derive-seed-v1）。禁止全局 random/UUID4/wall-clock
（PA4）。抽样参数概率经 float 传入 RNG（仅抽样参数；计数/哈希均为整数真值）。

## 14. 事件
aggregate 机器级事件：POPULATION_BIRTHS / POPULATION_DEATHS /
POPULATION_MIGRATION（count + from），不逐人产生事件。payload 参与
event_stream_hash（PA17：payload 不同 → 事件流哈希不同）。

## 15. 哈希三件套
world_state_hash v2（population_groups 全字段含 count/carry/profile_ref/
demography_version/updated_blessed_tick 纳入 canonical）；event_stream_hash
v1 增量链沿用 Preflight；deterministic_event_uid v1（128-bit，含
event_type）。PA16/PA18/PA19/PA20 全部实测通过。

## 16. 引擎所有权
DEMOGRAPHY 只写 population_groups；不写资源/经济/生态/社会/灾劫；跨系统
影响走 Domain Event 或 modifier signal。

## 17. Modifiers DTO
`PopulationModifiers`（food/ecology/social/disaster_pressure +
external_mortality_modifier，Fraction，默认 neutral）。
`SimulationContext` 增 `modifiers: dict` 槽（coordinator 现传 `{}`）；跨引擎
信号未来经 staged context 供给，引擎不查其他引擎 DB。

## 18. 守恒与不变量（P_INV_01–12）
population≥0；cohort≥0；sum(cohorts)==total；births/deaths≥0；deaths≤源；
迁移不得移出超过源；整数；无 NaN/Inf；引用有效；迁移不复制个体；守恒
`end = start + births − deaths + immigration − emigration`。PA5/PA9/PA10/
PA11/PA28 实测覆盖。

## 19. 性能模型
aggregate：每步 O(groups × buckets) 整数运算 + 每 bucket 至多 1 次 RNG
抽样。120 年 × 2 聚落 × 40 buckets ≈ 万级运算/年。120y 基线 wall=7.358s
（wall time 仅为性能字段，不进确定性语义）。

## 20. 零 LLM / 零网络 / 零 wall-clock
PA30/PA31：全流程无 LLM 调用、无网络访问（synthetic 引擎纯本地运算）。
PA32：模拟真值不读 wall clock（blessed tick 驱动）。

## 21. World Seed 零消费
PA33：120y 运行后 Phase1.8 Seed Package（XIAOGUANG_CROW_KB/world_seed/）
21 文件逐字节不变；正式库 world_seed_version 仍为 NULL。

## 22. Mini-World fixture（关键修复）
`mini_world.py`：所有 bucket 0..39 建行（空 bucket 0..14 也占行，
count=0）；初始人口只落在 15..39（A=12/B=4 × 25 bucket = 400）。修复前仅
建 15..39 行 → 出生写入不存在的 bucket-0 行丢人口，违反 P_INV_12
（PA28 守恒测试兜底捕获）。

## 23. 120y 基线（TEST BASELINE，非 Canon）
fixture_version=mini_world_v1；simulation_version=0.2.0-preflight；
population_engine_version=m2a-1。120 福地年结果：

| 指标 | 值 |
| --- | --- |
| population 400 → 552（A=374, B=178） | 守恒 400+790−638+624−624=552 ✓ |
| births / deaths | 790 / 638 |
| immigration / emigration | 624 / 624（净 0，闭合） |
| event_count | 832（120 TIME_ADVANCE + 712 aggregate） |
| runs / steps / checkpoints | 120 / 120 / 240（TIME+WORLD 双 checkpoint） |
| wall_seconds | 7.358 |

## 24. 基线双哈希
final_world_state_hash = `1d126d0395485c328094a5edd38ee1fbac5b0db7edde
20d5049567a84f49eb89`；
final_event_stream_hash = `5d7a4434856906d10b34e6e22fe2eb75f4d2b8d18
0a960f209fda28fe1d45c12`。
基线文件：`tests/baselines/m2a_population_miniworld_120y_v1.json`
（fixture/版本/初始-终态含 80 cohort 明细/metrics/双哈希/runs/steps/
checkpoints/performance）。`test_baseline_artifact_reproducible` 每次全
套件重放 120y 并逐字节比对，确定性锁定。

## 25. 崩溃与恢复（原子模型 A）
PA24/PA25（崩溃矩阵 c1–c10 ×6 注入点）：TIME_COMMITTED 与
WORLD_COMMITTED 同事务原子提交——崩溃后两者都不存在，无「时间 N+1 /
人口 N」脱节态。权威恢复 = latest complete WORLD_COMMITTED。

## 26. 重启/续跑与切块等价
PA26：restart/resume 后终态 + 各指标合计与连续运行一致（起始人口不同属
设计内）。PA29：120y 一次跑 == 120 次 1y 切块跑（同一初始状态 → 同一终态
与哈希，blessed tick 分块驱动）。

## 27. 幂等重试
PA21：同一 interval 重试零重复 DEMOGRAPHY 变更（M1 区间 skip + 确定性
uid 唯一约束）。PA22：事件零重复。

## 28. 老化写者 fencing
PA23：stale writer（过期 lease）commit 被 fencing 拒绝，不得写入人口
变更。

## 29. 正式库迁移
正式权威库 `D:\MY SELF\AstrBot\data\plugin_data\astrbot_plugin_
blessed_land_runtime\blessed_land.sqlite`：
先备份 `blessed_land.sqlite.pre-m2a-backup`（sha256 与迁移前一致
7a2223266fd136cf…）；`python scripts/init_db.py`（BLR_DATABASE_URL 指向
正式库）执行 alembic `e6c0f4a1b3d9 -> a7b3e9f1c5d2` + 幂等 seed +
event-immutability 触发器在位校验。迁移后 alembic_version=a7b3e9f1c5d2，
population_groups 12 列含新 3 列。

## 30. 正式库终检（FORMAL_AUDIT=PASS）
NOT_ACTIVATED；seed=NULL；tick=NULL；cursor=NULL；16 张业务/基建表全 0
（persons/population_groups/settlements/resource_nodes/tribulations/
world_events/timeline_entries/simulation_run/simulation_checkpoints/
narrative_records/ecological_regions/industries/institutions/lineages/
cultural_elements/runtime_lock）；TIME_ADVANCE=0；M2 checkpoint=0。
迁移后新 sha256 = `5a379a6169ab47537fbc4774d352dc8cba303baafc08d3ab1
faa2393ecb1658a`。

## 31. 测试总量（TOTAL_TESTS=198, TOTAL_PASS=198）
159 旧套件全保留 + 39 M2a 项（PA1–PA24 计 24、PA25 崩溃矩阵 6 参数、
PA26–PA35 计 8（PA30/31、PA34/35 为合并对）、基线复现 1）。全套件
`BLR_FORMAL_DB_PATH` 会话级正式库守护开启下 198/198 PASS，0 skip，
exit 0；guard 测试（zz_formal_db_guard + PA34/PA35 正式库保护）单独复跑
EXIT=0，lastfailed 为空。

## 32. 文档
`runtime_design/M2A_POPULATION_GROUP_ENGINE.md`（20 节：Purpose/Scope/
Group Model/Cohort/Profile/Birth/Mortality/Migration/RNG/Modifiers/
Ownership/Events/State Hash/Event Hash/Checkpoint/120y Baseline/
Invariants/Performance/Persistent Person Boundary/Known Limitations；
CONFIRMED 与 NEW_PROPOSAL 明确标注）。同步副本已复制到
`XIAOGUANG_CROW_KB/runtime_design/`（KB 非 git）。

## 33. 基线文件
`tests/baselines/m2a_population_miniworld_120y_v1.json`（8,215 B）为测试
基线；真实 baseline 与正式种族参数待 Canon/Seed 来源。

## 34. Git 提交
- `<M2A>` DSH M2a population group engine: aggregate demography
  (births/deaths/migration, carry ticks), a7b3e9f1c5d2 migration,
  SPECIES_PROFILES synthetic-only, PA1-35 + 120y baseline（独立提交，
  不 squash；tag m2-preflight-hardened 保留指向 137515e）。
- 变更：services/simulation/{population.py 新增, contracts/coordinator/
  harness/mini_world/snapshot.py 改}；database/alembic/versions/
  a7b3e9f1c5d2_m2a_population_cohorts.py 新增；database/models_world.py、
  plugin_shell/runtime_host.py、scripts/migrate_db_to_plugin_data.py、
  tests/conftest.py 改；tests/{test_m2a_population.py, baselines/} 新增；
  runtime_design/M2A_POPULATION_GROUP_ENGINE.md 新增。

## 35. 已知限制与下一步
- fixture 必须预建全部 bucket 行（缺失行丢人口，PA28 兜底）。
- 迁移权重按 settlement 序映射（TEST 双聚落固定序；正式多聚落需
  profile 化）。
- capacity 软约束使用 settlement.population_capacity（M0 字段）语义。
- 正式种族全部 UNCONFIGURED：出现即报错。
- **STOP**：不进入 M2b、不进入 M3、不激活 World Seed、不消耗 Seed 包。
  等待主人下一条明确批准。

---

```
M2A_POPULATION_ENGINE_READY
```

（完成后 STOP。TOTAL_TESTS=198, TOTAL_PASS=198；正式库 FORMAL_AUDIT=
PASS；120y 基线 400→552，births=790 deaths=638 imm=624 emi=624，
state_hash=1d126d03…eb89，event_hash=5d7a4434…5c12。）
