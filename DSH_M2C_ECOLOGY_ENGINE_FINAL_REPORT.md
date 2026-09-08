# DSH_M2C_ECOLOGY_ENGINE_FINAL_REPORT

> 执行方：DSH。阶段：M2C_ECOLOGY_ENGINE（ECOLOGY Engine，唯一新增
> Pipeline Stage）。禁止：Social/Tribulation/History/Scheduler/
> Companion/World Seed Activation。
> 基线：M2B_RESOURCE_ECONOMY_ENGINE（a6134ec）+ M2B_COMMIT_AMBIGUITY_
> HARDENING（196a8ca）= 273/273，tag m2b-resource-economy-ready。
> 完成后 STOP：不进入 M2d/M3/M4/M5/M6，不激活世界。

## 1. Baseline
tag m2b-resource-economy-ready @ 196a8ca（含 a6134ec）；273/273 全
保留；M2a/M2b 120y 基线逐字节复现（v2/v3 冻结表集字段集）。

## 2. Source Design Recovery
只读审计 runtime_design 06/07/08/09 + M2 Preflight/M2A/M2B 文档：
- CONFIRMED_EXISTING_SCOPE（09 号）：生态区域聚合状态；超载→退化
  （CAUSE_BASED）；区域退化/新生；承载力约束；跨引擎影响（聚落扩张/
  农业产出/运输安全）。
- IMPLIED：质量/恢复/再生能力的定量化。
- CONFLICT_FOUND：见 §3。
- DEPRECATED_RUNTIME_TIME_MODEL：本实现全程 blessed tick 整数，无
  /365 残留。

## 3. Conflicts Found
- C1：09 号 food web / 异兽 / 季节波动 / 物种关系 > M2c 范围 → 裁决：
  M2c 只做聚合环境质量层，兽群/食物链/季节属后续里程碑。
- C2：09 号生态事件（季节波动/兽患）vs M2c「无随机灾害」→ 裁决：
  M2c 不发随机扰动事件；external_shock_modifier 占位留 M3。

## 4. New Proposals
整数 fixed-point 质量模型（m2c-scale-1，SCALE=1e6）；四压力加权公式
（版本化，逐项无量纲）；退化=压力×敏感×脆弱；恢复=率×(1−压力)×距
ceiling；recovery_ceiling；degradation/recovery carry 持久化；阈值
schema m2c-threshold-v1；yield modifier m2c-yield-v1；
EcologyResourceFeedback 字段集；ecology_feedback_state committed 表；
feedback.py 生态→人口映射（1/500，TEST-only）；world_state_hash v4。
全部标注于 M2C_ECOLOGY_ENGINE.md §34。

## 5. Ecology Schema
migration d4f7b2e9c1a6：ecology_zones / ecology_state（质量/再生容量/
生态压力/四压力分量/carry×2/min-max 见证值/版本）/ ecology_feedback_
state（年再生量/yield 与 extraction modifier/habitat 等级/环境压力
fixed-point）；resource_nodes 扩展 reserve_ceiling_minor +
regeneration_carry。全部 BigInteger；唯一约束显式命名。

## 6. Ecology Zone Model
独立领域概念（≠ Settlement，≠ Resource Node）：zone_id / region_ref
（关联资源节点）/ settlement_relation（关联聚落）/ profile_ref /
semantic_version。

## 7. Ecology Profile
EcologyProfile：recovery_rate(1/25)/recovery_ceiling(900,000)/
sensitivity(1/100)/pressure_weights(2/8,3/8,2/8,1/8)/pop_pressure_per_
person(1,000)/renewable_regen_minor_per_full_quality(220 units/年)/
thresholds(800k/500k/200k)。仅注册 TEST-ECOLOGY-PROFILE-001；
正式生态 profile = ECOLOGY_UNCONFIGURED（出现即报错，EC42 实测）。

## 8. Fixed-Point Model
ECOLOGY_STATE_SCALE_VERSION="m2c-scale-1"；质量/压力/再生容量 =
整数 0..1,000,000；无 float 权威状态（EC4/EC5/EC36 实测）。

## 9. Pressure Algorithm
四输入先无量纲化再按权重加权（版本化公式，禁止无说明相加）：
population/extraction（本步开采÷(容量×年数)）/production（本步产出÷
登记配方理论产能）/depletion（开采÷(剩余+开采)，耗尽→SCALE）/
external（neutral 占位）。只经 staged 视图声明读取；经济短缺不直接
进入（EC19 实测：改 B 粮食库存造成短缺 → 生态结果逐字段不变）。

## 10. Degradation Algorithm
`deg/年 = total_pressure × sensitivity × vulnerability`；
vulnerability=(2×SCALE−quality)/(2×SCALE)（低质量更脆弱）；纯
CAUSE_BASED，无随机退化（EC7 确定性实测）。

## 11. Recovery Algorithm
`rec/年 = recovery_rate × (1−pressure/SCALE) × (ceiling−quality)`；
低压力恢复、高压力压制；ceiling 显式 —— 无无限恢复（EC8 实测）。

## 12. Carry Model
degradation_carry / recovery_carry 整数持久化（rate×interval 不整除
时）；resource_nodes.regeneration_carry 属 Resource 侧。EC9 实测
1+1 restart == 2y continuous（carry 逐字段相等）。

## 13. Renewable Resource Feedback
Ecology 输出 regeneration_capacity_minor_per_year = quality × 满质量
年再生量/SCALE + yield/extraction modifier = 3/4 + quality/(4×SCALE)
（m2c-yield-v1）。RESOURCE 下一 committed step 应用（EC17 实测：
第 2 步再生>0、yield ≤ 1）。

## 14. Resource Ownership Boundary
Ecology 决定「环境允许恢复多少」，Resource 决定「authoritative
reserve 怎么变化」。Ecology 不写 resource_nodes（EC12 实测：
ecology-only 运行资源储备逐字节不变）；非可再生再生=0（EC10 实测）。

## 15. Population Feedback
demography_ecology_pressure_modifier = environmental_stress × 1/500
（TEST-SPECIES-001 only；正式种族 UNKNOWN → 0）。EC18 实测：
preseed CRITICAL 压力 → max_ecology_stress_level=3、deaths ≥ 基线。

## 16. Economy Feedback
Ecology→Economy 通道语义冻结（production_environment_modifier /
resource_yield_modifier / environmental_constraint，仅下一 Step），
M2c 未接线（无已声明消费规则）—— 如实记录，不伪造实现。

## 17. Next-Step Feedback Verification
ECOLOGY_FEEDBACK_LATENCY = NEXT_COMMITTED_STEP。EC16 实测：第 1 步
再生=0（生态本步结果不回写本步 RESOURCE），DEMOGRAPHY/ECONOMY 与无
生态夹具全等；EC17/EC18 实测 Year 2 起 RESOURCE/DEMOGRAPHY 收到
Year 1 committed 反馈。§32 闭环（DEMO↔ECO/ECOL 跨 Step）在 120y
基线内持续成立（zone A 压力→质量→yield→开采→压力 循环可观测）。

## 18. Event Model
aggregate 机器事件 ECOLOGY_THRESHOLD_CROSSED（仅跨级发；direction +
quality before/after + pressure 入 payload）；不逐数值发事件。
ECOLOGY_DEGRADED 等纯机器事件，零自然语言叙事。

## 19. Event Stream Hash
EVENT_STREAM_HASH_SCHEMA_VERSION=1；payload 全覆盖（EC23 实测：
800k→700k vs →500k 哈希必不同）；uid v1 128-bit（EC22 实测）。

## 20. World State Hash
WORLD_STATE_HASH_SCHEMA_VERSION 3 → 4：v4 覆盖生态 zones/state/
feedback + 全部既有状态域；canonical 行序无关（EC25 实测）；v2/v3
显式冻结（M2a/M2b 基线逐字节复现回归实测）。

## 21. RNG
ECOLOGY 独立 substream；算法零 RNG（无随机灾害；唯一 ctx.rng 引用为
测试旋钮 —— EC26/EC27 实测：extra_draws 不改任何引擎结果/哈希）。

## 22. Engine Ownership
ECOLOGY → {ecology_state, ecology_feedback_state}；ecology_zones 只读
配置；不写人口/资源/经济/社会（EC_INV_09/10/11，EC12-14 实测）。

## 23. Fencing
EC30/E6 实测：stale writer（token 被窃）→ FENCING_VIOLATION，
ecology/事件/checkpoint 全部 0 authoritative write。

## 24. Idempotency
同 interval retry：零重复退化/恢复/反馈/事件/checkpoint/时间推进
（EC28/EC29 实测）。

## 25. Crash Matrix（E1–E7）
E1 after Economy staged / E2 mid Ecology / E3 after Ecology staged /
E4 during ecology DB write / E5 during ecology feedback persistence /
E6 before fencing recheck（token 窃取）/ E7 durable commit + ACK lost。
参数化矩阵 + EC31/EC32/E6 + EC33 实测：任何注入点恢复后
tick/population/resource/inventory/economy/ecology/feedback/events/
双哈希/checkpoints 全一致，干净重试 == 一次成功。

## 26. Commit Ack Lost
EC33 实测（复用 M2b hardened 注入）：durable commit → ACK lost →
restart → ALREADY_COMMITTED；生态不二次退化/恢复、反馈不二次累加、
事件不重复。PRE_ACTIVATION_PG_COMMIT_AMBIGUITY_GATE = REQUIRED 继续
生效。

## 27. Checkpoint Consistency
TIME_COMMITTED + WORLD_COMMITTED 双层原子；权威恢复 = latest
complete WORLD_COMMITTED；EC34 实测 checkpoint hash == DB 状态 v4
哈希、engine_versions 含 ECOLOGY —— 绝无「Year 50 Ecology / Year 51
Economy / Year 51 Time」跨层错位。

## 28. 120-Year Integrated Baseline
mini_world_v1（M2c integrated：2 settlements + TEST_SPECIES_001 +
TEST_RESOURCE_001/002/003（TEST-TIMBER 可再生）+ TEST 经济 profile +
TEST_ECOLOGY_PROFILE_001，2 生态区），120 福地年，四引擎真实全部
执行。数值见报告末 TOTAL 段。场景：Zone A 长期压力 → 900,000 →
657,322（STRESSED，跨 800k 阈值 1 次）；Zone B 可再生采伐与恢复竞争
（900,000 → 819,995 HEALTHY，min 819,971）；TEST-TIMBER 120 年
开采 ≈ 生态再生（5,000 → 4,999 units，绝不超 ceiling）。全数字
TEST_FIXTURE_ONLY，非 Canon。

## 29. Continuous / Chunked / Restart
EC37：120y == 30y×4 chunked（哈希/人口/资源/经济/生态/metrics 全等）；
EC38：120y == 60+60 restart（终态哈希/人口 end/储量/终态质量 + 分片
metrics 合计全等）；EC9：carry 在 restart 下逐字段保留。

## 30. Performance
120y integrated wall = 7.271s（四引擎；仅性能字段，不进哈希）。
aggregate：每步 O(zones×(nodes+stocks)) 整数运算，无个体对象。

## 31. LLM=0
ecology.py/feedback.py 零 LLM 符号（EC39 源码扫描）；完整四引擎路径
LLM_CALLS=0。

## 32. Network=0
EC40 实测：socket/urllib/http.client 全炸 → 5 年整合运行正常。

## 33. Wall Clock Isolation
EC41 实测：ecology.py 无 datetime.now/time.time/perf_counter/
time_ns/date.today；只认 SimulationInterval。

## 34. PostgreSQL Compatibility
BigInteger 全整数权威列；无 json_extract/rowid/隐式类型依赖；唯一
约束显式命名。**NOT LIVE VERIFIED**（未实跑 PG）；
PRE_ACTIVATION_PG_GATE = REQUIRED、PRE_ACTIVATION_PG_COMMIT_
AMBIGUITY_GATE = REQUIRED 继续登记。

## 35. Formal DB Audit
pre-m2c 备份（blessed_land.sqlite.pre-m2c-backup，与 pre-m2a/pre-m2b
并存保留；备份 sha256 与迁移前一致 23561030…c71d）；迁移后
FORMAL_AUDIT_M2C=PASS：head=d4f7b2e9c1a6；NOT_ACTIVATED；seed=NULL；
tick=NULL；24 张业务/基建表全 0（含 ecology_zones/ecology_state/
ecology_feedback_state）；TIME_ADVANCE=0；M2 checkpoint=0；integrity
ok。迁移后新 sha256 =
`97e989657c4e639ea06cb0e3ff24948e8781eaaa707f93ab3eebc526b73b8908`。

## 36. World Seed Freeze Audit
EC43 实测：SIM 目录零 world_seed/零 04_population_baseline 引用；
03 geography / 09 resource / 10 ecology provisional 内容未写入任何
DB；mini_world 全 synthetic。M6 才允许正式初始化。

## 37. Alembic Migration
d4f7b2e9c1a6_m2c_ecology：只 ADD（2 节点列 + 3 表），不改旧 migration；
历史 12 步完整链；EXPECTED_SCHEMA_HEAD 三处同步（runtime_host /
migrate_db_to_plugin_data / conftest）；表数 25 → 28（test_database
同步）。

## 38. Regression Results
TOTAL_TESTS / TOTAL_PASS 见报告末（273 旧 + 52 新：EC1–EC45 + E1–E5
参数化 + E6 + 120y 基线复现）。

## 39. New Test Matrix
EC1/2 协议与管线；EC3 零 commit；EC4/5 fixed-point/有界；EC6-8 压力/
退化/恢复确定性；EC9 carry 重启；EC10 非可再生再生=0；EC11 可再生
确定性；EC12-14 所有权；EC15 反馈持久；EC16/17/18 同 step 禁止 +
双通道下一 step 生效；EC19 短缺≠退化；EC20 耗尽≠自动退化；EC21 阈值
确定性；EC22/23 uid/事件哈希；EC24/25 v4 覆盖/行序无关；EC26/27 RNG
隔离/无随机灾害；EC28/29 幂等；EC30/E6 fencing；EC31/32/E1-E5 崩溃
矩阵；EC33 ack lost；EC34 checkpoint 覆盖；EC35/36 120y 完成+全不变
量；EC37/38 chunk/restart；EC39-41 LLM/网络/wallclock；EC42 正式
profile UNCONFIGURED；EC43-45 Seed/正式库空/完整性。

## 40. Git Commit / Tag
独立 M2c commit（不混 M2d/M3/M4/M5/M6）；tag
m2b-resource-economy-ready @ 196a8ca 保留；既有 tag
m1-golden-baseline / m1.1-live-verified / m2-preflight-hardened /
m2a-population-ready 保留。

## 41. Workspace Clean
`git status` clean（world.db*、backups/*.db 由 .gitignore 排除；M2a/
M2b 基线产物在测试重写后已还原为冻结版本）。

## 42. Known Risks
- PG 兼容 NOT LIVE VERIFIED（代码级审计）。
- 生态区经 region_ref 关联节点（1 区多节点聚合）；跨区流动不建模。
- Ecology→Economy 通道未接线（无已声明消费规则）。
- EXHAUSTED→STABLE 再生恢复无独立事件（状态纠正）。
- 120y 基线为 TEST_FIXTURE_ONLY，不构成任何正式世界推断。

---

```
M2C_ECOLOGY_ENGINE_READY
```

```
TOTAL_TESTS = 325
TOTAL_PASS = 325

WORLD_RUNTIME_STATUS = NOT_ACTIVATED
seed = NULL
current_blessed_tick = NULL
formal_population = 0
formal_resource_nodes = 0
formal_resource_stocks = 0
formal_ecology_zones = 0
formal_ecology_state = 0
official_world_events = 0

120y baseline（TEST_FIXTURE_ONLY）：
initial_population = 400
final_population = 456
births = 928
deaths = 872
immigration = 526
emigration = 526

initial_resource_reserve = 405,000,000,000 minor（405,000 units）
final_resource_reserve = 278,441,462,873 minor（278,441.46 units）
total_extracted = 147,779,958,673 minor
total_regeneration_applied = 21,221,421,546 minor

initial_ecology_quality = {A: 900,000, B: 900,000}
final_ecology_quality = {A: 657,322, B: 819,995}
minimum_ecology_quality = {A: 657,322, B: 819,971}
maximum_ecology_quality = {A: 900,000, B: 900,000}
total_degradation = 751,150 minor
total_recovery = 428,467 minor
threshold_crossings = 1（Zone A：HEALTHY → STRESSED）
ecology_feedback_applications = 240

final_world_state_hash = 4168f1774e73aafdcadeb5c8f348cf79304799de4bf6a0cccec346cdca392729
final_event_stream_hash = 84b826fcf848a189956cda559850aae5f026808c14d3e4596613dbd97b005cba

runs = 120
steps = 120
checkpoints = 240
events = 1678（threshold 1）
wall_seconds = 7.271（仅性能字段）

formal_db_sha256_after_migration = 97e989657c4e639ea06cb0e3ff24948e8781eaaa707f93ab3eebc526b73b8908
```
