# M2A_POPULATION_GROUP_ENGINE

> M2a 交付文档。CONFIRMED = 恢复自 runtime_design/06；NEW_PROPOSAL = DSH 冻结
> 决定（明确标注，不冒充旧设计）。正式种族参数保持 UNCONFIGURED。

## 1. Purpose
无 LLM 的长期确定性 Aggregate Population Simulation（Population Group 层）。

## 2. Scope
只实现 Population Group；Persistent Person（仅接口预留）、Lineage（M2d）、
Institution（M2d+）不实现。人口变化 ≠ 自动产生 NPC。

## 3. Population Group Model（CONFIRMED）
06 号：聚合维度 species × settlement × age_cohort × occupation_group ×
household_stats；**cohort = population_groups 行**；cohort 滚动（年龄+1）。

## 4. Cohort Model（NEW_PROPOSAL 细节）
- bucket 宽 = 1 福地年；`age_cohort` = bucket 序号字符串（整数排序）。
- bucket 数 N 由 SpeciesDemographyProfile 决定；末位 bucket [N-1, ∞) 聚合。
- 亚年区间：`age_advance_carry_ticks`（BigInteger）整数进位，零浮点累计；
  SimulationInterval 任意（0.5y/2y/adaptive）均有定义。
- fixture 必须为全部 bucket 0..N-1 建行（空 bucket 也占行——出生落入 bucket 0，
  缺行会丢失人口，违反 P_INV_12）。

## 5. Species Demography Profile（NEW_PROPOSAL 结构）
`SpeciesDemographyProfile`：species_id / cohort_buckets / fertile_min_age /
fertile_max_age / birth_rate(Fraction) / mortality_by_bucket(Fraction[],
len=N) / emigration_rate(Fraction) / migration_weights(Fraction[], 和=1)。
M2a 仅注册 synthetic `TEST-SPECIES-001`（TEST_FIXTURE_ONLY）；正式种族
（人/毛民/石人/鲛人/菇人）保持 UNKNOWN/UNCONFIGURED（查询即
DEMOGRAPHY_UNCONFIGURED）。06 号「石人千余已知、其余 UNDECIDED」不在此
阶段写入参数。

## 6. Birth Model（NEW_PROPOSAL 公式）
`expected = fertile_population × birth_rate × capacity_factor`；
`capacity_factor = max(capacity - total, 0) / capacity`（settlement.
population_capacity 软约束，无 capacity 时=1）；
`births = floor(expected) + Bernoulli(expected - floor(expected))`。
基于人口结构（fertile buckets），非 `population × 固定百分比`。

## 7. Mortality Model（NEW_PROPOSAL 公式）
每 bucket：`q_b = mortality_by_bucket[b] + external_mortality_modifier`；
`deaths_b = floor(n_b × q_b) + Bernoulli(余数)`，上限 n_b。不同 cohort 不同
死亡率；灾劫/战争/瘟疫/生态危机不实现（modifier 接口预留）。

## 8. Migration Model（NEW_PROPOSAL）
Basic Aggregate：`emigration = floor(end × rate) + Bernoulli(余数)`（≤ end），
从最高 bucket 向下扣减；迁入按 profile.migration_weights 用最大余数法整数
再分配，进入首个 fertile bucket。不做社会冲突/经济吸引/生态压力。

## 9. RNG（CONFIRMED 04 §4 + M1 实现）
DEMOGRAPHY 独立 substream（derive_seed 含 engine_id + step_start_tick）。
抽样顺序（进入引擎语义版本）：每 group 死亡 bucket 0..N-1 → 出生 →
逐 group 迁移。禁止全局 random/UUID4/wall-clock。

## 10. Modifiers（NEW_PROPOSAL DTO）
`PopulationModifiers`（food/ecology/social/disaster_pressure +
external_mortality_modifier，Fraction，默认 neutral）。引擎不查其他引擎 DB；
跨引擎信号未来经 coordinator staged context 供给（ctx.modifiers 槽已预留）。

## 11. Engine Ownership
DEMOGRAPHY 只写 population_groups；不写资源/经济/生态/社会/灾劫；跨系统
影响走 Domain Event 或 modifier signal。

## 12. Events
aggregate 机器级事件：POPULATION_BIRTHS / POPULATION_DEATHS /
POPULATION_MIGRATION（count + from），不逐人产生事件；事件 payload 参与
event_stream_hash（HP/PA17 实测：payload 不同 → 事件流哈希不同）。

## 13. State Hash（WORLD_STATE_HASH_SCHEMA_VERSION=2）
population_groups 全字段（含 count/carry/profile_ref/demography_version/
updated_blessed_tick）纳入 canonical hash；age_cohort 按整数排序；与行插入
顺序无关（PA20）。

## 14. Event Hash（EVENT_STREAM_HASH_SCHEMA_VERSION=1）
沿用 Preflight 增量链；aggregate 事件 payload 覆盖。

## 15. Checkpoint / Crash Recovery（原子模型 A）
TIME_COMMITTED + WORLD_COMMITTED 同事务原子提交——崩溃后两者都不存在，
不存在「时间 N+1 / 人口 N」脱节态（PA24/PA25 实测）。权威恢复 =
latest complete WORLD_COMMITTED。

## 16. 120y Baseline（TEST BASELINE，非 Canon）
mini_world_v1 + TEST-SPECIES-001 跑 120 福地年；
`tests/baselines/m2a_population_miniworld_120y_v1.json`
（fixture/版本/初始-终态/metrics/双哈希/runs/steps/checkpoints；
wall-clock 仅为性能字段，不参与确定性语义）。基线数值为测试基线，
真实 baseline 与正式种族参数待 Canon/Seed 来源。

## 17. Invariants（P_INV_01–12）
population≥0；cohort≥0；sum(cohorts)==total；births/deaths≥0；deaths≤源；
迁移不得移出超过源；整数；无 NaN/Inf；引用有效；迁移不复制个体；
守恒 end=start+births−deaths+immigration−emigration。全部由 PA 测试覆盖。

## 18. Performance Model
aggregate：每步 O(groups × buckets) 整数运算 + 每 bucket 至多 1 次 RNG 抽样；
120 年 × 2 聚落 × 40 buckets ≈ 万级运算/年，秒级完成；wall time 记录于基线
performance 字段（不进哈希）。可扩展至 ~12,000 人口（无需 12,000 对象）。

## 19. Future Persistent Person Boundary
M2a 不生成任何 persons 行（PA14/15）；未来 Persistent Person 由锚点选择
机制单独建立（llm_eligible 8~12 起步，上限 20~40，属后续里程碑），
与 aggregate 层单向衔接（事件/快照），不反向写入。

## 20. Known Limitations
- fixture 必须预建全部 bucket 行（缺失行会丢人口，由 PA28 守恒测试兜底）。
- 概率抽样概率经 float 传入 RNG（仅抽样参数；计数/哈希均为整数真值）。
- 迁移权重按 settlement 序映射（TEST 双聚落固定序；正式多聚落需 profile 化）。
- capacity 软约束使用 settlement.population_capacity（M0 字段）语义。
- 正式种族全部 UNCONFIGURED：出现即报错，不静默套用测试参数。
