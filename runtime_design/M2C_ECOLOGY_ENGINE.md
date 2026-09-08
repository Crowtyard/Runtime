# M2C_ECOLOGY_ENGINE

> M2c 交付文档。CONFIRMED_EXISTING_SCOPE = 恢复自旧设计（09 号为主）；
> IMPLIED = 旧设计隐含但未定量；NEW_PROPOSAL = DSH 冻结决定；
> CONFLICT_FOUND = 与 M2c 任务的显式边界冲突及裁决。
> 正式生态参数保持 ECOLOGY_UNCONFIGURED；一切数值 TEST_FIXTURE_ONLY。

## 1. Scope
长期确定性生态状态演化：生态区 → 开采/人口/经济压力 → 质量变化 →
退化/恢复 → 再生能力 → 生态压力 → 下一周期反馈。回答「环境被长期使用后
发生什么」，不回答「今年发生什么灾难」。禁止：灾劫/洪水/地震/瘟疫/战争/
超凡灾害/历史叙事/物种演化/完整食物网/个体模拟/天气系统/气候 API/
污染产业系统/社会环境政策/生态 NPC。

## 2. Source Design Recovery
- CONFIRMED_EXISTING_SCOPE（09 号）：ecological_regions 聚合区域状态；
  超载 → 退化事件（CAUSE_BASED）；区域退化/新生概念；承载力约束使用
  强度；生态影响聚落扩张/农业产出/运输安全（跨引擎关系）。
- IMPLIED（09 号）：质量/恢复/再生能力作为区域状态的自然内涵，但未定量。
- CONFLICT_FOUND：09 号 food web / 异兽 / 季节波动 / 物种关系 > M2c
  范围 → 裁决：M2c 只做聚合环境质量层；兽群/食物链/季节属后续里程碑。
- CONFLICT_FOUND：09 号「生态事件：季节波动/兽患」与 M2c「无随机灾害」
  冲突 → M2c 不发随机扰动事件；external_shock_modifier 留 M3。
- 06/07/08 及 M2 Preflight/M2A/M2B 文档：管线顺序、staged feed-forward、
  双层 checkpoint、feedback latency 机制均沿用（无冲突）。
- DEPRECATED_RUNTIME_TIME_MODEL：旧文档无 /365 残留进入本实现；全程
  blessed tick 整数。

## 3. Ecology Engine Ownership
ECOLOGY 只能 propose：ecology_state / ecology_feedback_state
（ecology_zones 为只读配置）。不得直接修改 population / resource
reserve / inventory / economy stock / production / consumption /
social state（EC_INV_09/10/11）。跨系统影响只经
EcologyFeedbackSignal（committed ecology_feedback_state）。

## 4. Ecology Zone
ecology_zones：zone_id / world_id / region_ref / settlement_relation /
profile_ref / semantic_version。Ecology Zone ≠ Settlement ≠ Resource
Node：经 region_ref 关联资源节点、经 settlement_relation 关联聚落，
是独立领域概念（09 号 ecological_regions 的聚合实现载体）。

## 5. Ecology Profile
`EcologyProfile`（ecology.py）：profile_id / recovery_rate(Fraction) /
recovery_ceiling / sensitivity / pressure_weights（和为 1 的 4 权重）/
pop_pressure_per_person / renewable_regen_minor_per_full_quality /
thresholds(STRESSED/DEGRADED/CRITICAL 三阈值) / semantic_version。
注册表仅 `TEST-ECOLOGY-PROFILE-001`（TEST_FIXTURE_ONLY）；正式山林/
湖泊/河流/灵田/药园 profile 一律 `EcologyProfileUnconfigured`
（code ECOLOGY_UNCONFIGURED），绝不擅自赋予恢复率/承载力/阈值。

## 6. Fixed-Point State
ECOLOGY_STATE_SCALE_VERSION="m2c-scale-1"；ECOLOGY_STATE_SCALE=
1_000_000。质量/压力/再生容量 = 整数 0..SCALE；无 float 权威状态；
无 NaN/Inf（EC_INV_01/03/04/05）。退化/恢复 carry 整数持久化。

## 7. Pressure Model（NEW_PROPOSAL 公式，版本化）
每个输入先无量纲化再按 profile 权重加权（禁止无说明相加）：
- population_pressure = clamp(pop × per_person, 0, SCALE)
- extraction_pressure = clamp(本步开采 / (容量×年数) × SCALE)
- production_pressure = clamp(本步产出 / 登记配方本步理论产能 × SCALE)
- depletion_pressure = clamp(开采 / (剩余+开采) × SCALE)（耗尽→SCALE）
- external_pressure = 0（neutral 占位，M3 接）
total = Σ weight_i × pressure_i（Fraction，floor 到整数）。
输入只经 staged 视图声明读取（人口/节点/库存/配方/生产状态）；
不查其他引擎私有 DB；经济短缺不直接进入（EC19 实测）。

## 8. Degradation
`degradation/year = total_pressure × sensitivity × vulnerability`；
vulnerability = (2×SCALE − quality)/(2×SCALE)（低质量更脆弱）。
不得随机制造退化事件；全部 CAUSE_BASED（09 号）。

## 9. Recovery
`recovery/year = recovery_rate × (1 − pressure/SCALE) ×
(ceiling − quality)`。低压力恢复、高压力压制；ceiling 显式 —— 恢复
不等于无限恢复（禁止每年固定 +X%）。

## 10. Carry
degradation_carry / recovery_carry（resource_nodes.
regeneration_carry 属 Resource 侧）：rate×interval 不整除时整数进位
持久化；continuous == chunked == restart（EC9/EC37/EC38 实测）；
adaptive interval（0.5y/1y/2y）全部经 carry 有定义，不假设年度步。

## 11. Renewable Resource Feedback
Ecology 输出（每 zone）：
- regeneration_capacity_minor_per_year = quality × 满质量年再生量 / SCALE
- yield_modifier = extraction_modifier = 3/4 + quality/(4×SCALE)
  （m2c-yield-v1：质量=SCALE 时 1，=0 时 3/4）
- habitat_stress_level / environmental_stress（num/den 约分）

## 12. Nonrenewable Boundary
profile.renewability != "RENEWABLE" 或无 reserve_ceiling_minor →
再生输出 = 0（EC_INV_08，EC10 实测：矿藏绝不自动长回来）。

## 13. Carrying Pressure
EnvironmentalCarryingPressureSignal = ecological_stress +
habitat_stress_level + environmental_stress（表达环境压力随人口/资源/
质量/消费变化），不是神秘固定人口上限；M2c 不直接杀人口。

## 14. Ecology→Resource
Ecology 决定「环境允许恢复多少」（EcologyResourceFeedback）；
Resource 决定「authoritative reserve 怎么变化」：下一 committed step
ResourceEngine 读 ecology_feedback_state → 可再生节点应用
`min(再生×年数(+carry), ceiling − reserve)`；yield modifier 缩放有效
开采容量。禁止 Ecology 直接写 remaining_reserve（EC12/EC17 实测）。

## 15. Ecology→Demography
demography_ecology_pressure_modifier（feedback.py）：
environmental_stress × ECOLOGY_MORTALITY_SENSITIVITY(1/500)，仅
TEST-SPECIES-001（TEST_FIXTURE_ONLY）；正式种族 modifier sensitivity
= UNKNOWN → 0（EC18 实测通道与 synthetic 映射）。

## 16. Ecology→Economy
允许输出 production_environment_modifier / resource_yield_modifier /
environmental_constraint —— M2c 未接线（无已声明消费规则），下一 Step
才可读取的通道语义冻结；不直接改 production_output/inventory/demand。

## 17. Feedback Lag
ECOLOGY_FEEDBACK_LATENCY = NEXT_COMMITTED_STEP。Year N Ecology 结果
绝不回写 Year N 的 DEMOGRAPHY/RESOURCE/ECONOMY（EC16 实测：第 1 步
再生=0、DEMOGRAPHY/ECONOMY 与无生态夹具全等）；Year N+1 RESOURCE/
DEMOGRAPHY 读 Year N committed 反馈（EC17/EC18 实测）。

## 18. Events
aggregate 机器事件：ECOLOGY_THRESHOLD_CROSSED（direction 入
payload：from_level/to_level/quality_before/after/pressure）。
不逐数值发事件 —— 仅跨级发（1000 年事件流不爆炸）。

## 19. Thresholds
THRESHOLD_SCHEMA_VERSION="m2c-threshold-v1"；HEALTHY ≥ 800,000 >
STRESSED ≥ 500,000 > DEGRADED ≥ 200,000 > CRITICAL（profile 固定
阈值，禁止 LLM 判断）。

## 20. RNG
ECOLOGY 独立 substream（coordinator 派生）；算法本身零 RNG（§42：
确定性模型优先；无随机灾害 —— EC26/EC27 实测）。

## 21. World State Hash
WORLD_STATE_HASH_SCHEMA_VERSION 3 → 4：v4 覆盖 ecology zones/state/
feedback + 全部既有状态域；canonical、行序无关（EC25）、restart 稳定。
v3（M2b 12 表）与 v2（M2a 7 表）显式冻结 —— M2a/M2b 基线逐字节复现
（回归实测）。

## 22. Event Hash
EVENT_STREAM_HASH_SCHEMA_VERSION=1 不变；生态事件 canonical payload
全覆盖（EC23 实测：quality 800k→700k vs →500k 哈希必不同）。

## 23. Checkpoint
TIME_COMMITTED + WORLD_COMMITTED 双层原子；权威恢复 = latest
complete WORLD_COMMITTED；M2c 状态随 WORLD checkpoint/hash 全覆盖
（EC34 实测 checkpoint hash == DB 状态 v4 哈希，绝无跨层错位）。

## 24. Crash Recovery（E1–E7）
E1 after Economy staged（engine:ECOLOGY）/ E2 mid Ecology
（mid:ECOLOGY）/ E3 after Ecology staged（after_engines）/ E4 during
ecology DB write（during_apply）/ E5 during ecology feedback
persistence（before_checkpoint）/ E6 before fencing recheck（token 窃取
→ FENCING_VIOLATION）/ E7 durable commit + ACK lost（复用 M2b
hardened 注入）。恢复后 tick/population/resource/inventory/economy/
ecology/feedback/events/双哈希/checkpoints 全一致（EC31/32/33/E1-E6 实测）。

## 25. Commit Ambiguity
同 M2b CA 语义：durable commit → ACK lost → restart →
ALREADY_COMMITTED；生态状态不二次退化/恢复、反馈不二次累加、事件不
重复（EC33 实测）。PRE_ACTIVATION_PG_COMMIT_AMBIGUITY_GATE =
REQUIRED 继续生效。

## 26. Fencing
Writer A 算完四引擎但 lease 已丢 → commit 被 FENCING_VIOLATION 拒绝；
A 的 ecology 状态 0 authoritative write（EC30/E6 实测）。

## 27. Idempotency
同 interval retry：零重复生态退化/恢复/反馈信号/生态事件/checkpoint/
时间推进（EC28/EC29 实测）。

## 28. 120y Baseline
mini_world_v1（M2c integrated：2 settlements + TEST_SPECIES_001 +
TEST_RESOURCE_001/002/003（可再生 TEST-TIMBER）+ TEST 经济 profile +
TEST_ECOLOGY_PROFILE_001，2 生态区），120 福地年，四引擎真实全部
执行；`tests/baselines/m2c_ecology_miniworld_120y_v1.json`。场景设计：
Zone A（开采+生产+人口）长期压力 → 质量缓慢下降并跨入 STRESSED；
Zone B（可再生采伐）恢复与压力竞争、再生反馈供下一 Step 采伐。全部
TEST_FIXTURE_ONLY，非 Canon。

## 29. Performance
aggregate：每步 O(zones × (nodes + stocks))整数运算；无每棵树/每株草/
每条鱼对象。120y wall time 记录于基线 performance 字段（不进哈希）。

## 30. PostgreSQL Compatibility
BigInteger 全整数权威列（SQLite INTEGER 64-bit ↔ PG BIGINT）；核心
算法不依赖 json_extract/rowid/隐式类型；唯一约束显式命名。
**NOT LIVE VERIFIED**（未实跑 PG）；PRE_ACTIVATION_PG_GATE =
REQUIRED 与 PRE_ACTIVATION_PG_COMMIT_AMBIGUITY_GATE = REQUIRED
继续登记。

## 31. Tribulation Boundary
绝不实现灾劫/天灾/超凡冲击；external_pressure /
external_shock_modifier 占位 neutral，M3 才接。

## 32. Social Boundary
禁止环保制度/资源法规/居民抗议/土地制度/文化环境观/环保组织/公共
治理（M2d 或以后）。

## 33. Known Limitations
- 生态区与资源节点经 region_ref 关联（1 区多节点聚合）；跨区流动
  （水/风/物种扩散）不建模。
- 生态压力只读 staged 声明输入；economy production 经 cum 计数器
  差分读取（与行更新时机强耦合，属已声明契约）。
- Ecology→Economy 通道未接线（无已声明消费规则）。
- EXHAUSTED→STABLE 再生恢复由 Resource 引擎状态纠正（无独立事件）。
- 正式生态 profile 全 UNCONFIGURED：出现即报错（EC42 实测）。
- PG 兼容为代码级审计，NOT LIVE VERIFIED。

## 34. NEW_PROPOSAL / CONFLICT_FOUND 汇总
- CONFLICT_FOUND：09 号 food web/异兽/季节波动 > M2c（裁决见 §2）。
- CONFLICT_FOUND：无随机灾害 vs 09 号兽患/季节事件（裁决：不发）。
- NEW_PROPOSAL：整数 fixed-point 质量模型（SCALE=1e6，m2c-scale-1）；
  四压力加权公式（版本化）；退化=压力×敏感×脆弱；恢复=率×(1−压力)×
  距 ceiling；recovery_ceiling；carry 持久化；threshold schema
  m2c-threshold-v1；yield modifier m2c-yield-v1；EcologyResourceFeedback
  字段集；ecology_feedback_state committed 表；feedback.py 生态映射
  （1/500，TEST-only）；world_state_hash v4（v2/v3 冻结）。
