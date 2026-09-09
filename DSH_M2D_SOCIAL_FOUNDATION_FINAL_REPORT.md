# DSH_M2D_SOCIAL_FOUNDATION_FINAL_REPORT

> 执行方：DSH。阶段：M2D_SOCIAL_FOUNDATION（SOCIAL Engine Foundation）。
> 禁止：LLM NPC/大规模 Persistent Person/政治完整版/国家朝廷/战争/犯罪/
> 宗教完整版/阶级斗争/Tribulation/历史叙事/Scheduler/Companion/Seed 激活。
> 基线：M2a/b/c ACCEPTED + M2b Commit Ambiguity Hardening = 325/325，
> tag m2c-ecology-ready @ 09f2907。
> 完成后 STOP：不进入 M3/M4/M5/M6，不自行开展
> M2_INTEGRATED_COMPLETION_REVIEW。

## 1. Baseline
tag m2c-ecology-ready @ 09f2907；325/325 全保留；M2a/b/c 120y 基线
逐字节复现（v2/v3/v4 冻结表集字段集，回归实测）。

## 2. Source Design Recovery
只读审计 runtime_design 06/07/08/09 + M2 Preflight/M2A/M2B/M2C 文档：
- CONFIRMED_EXISTING_SCOPE（07 号）：households（统计级+锚点级）、
  lineages（PERSISTENT_LINEAGE）、institutions（PERSISTENT_
  INSTITUTION）、population_groups 劳动力池、后台社会事件清单、
  CAUSE_BASED、事件 scope 分级。
- IMPLIED：形成/消亡率与涌现阈值的定量化。
- CONFLICT_FOUND：见 §3。

## 3. Conflicts
- C1：07 号 婚姻/职业流动/争执仲裁/文化扩散（MEDIUM_DIFFUSION）>
  M2d 范围 → 延后。
- C2：07 号「RNG 决定谁遇到机会或不幸」vs M2d 确定性规则优先 →
  裁决：M2d 零 RNG；机会性选择属后续里程碑。

## 4. New Proposals
full-coverage 对账契约（m2d-coverage-v1）；round-robin 分配/拆分/
形成/溶解规则（m2d-formation-v1）；lineage 涌现（gen≥3 且 size≥6）/
分化（household_count≥12）阈值；institution 生命周期阈值与成立门槛
（pop≥80）；四压力加权公式（economy 4/8、ecology 3/8、mobility 1/8）；
社会反馈映射（migration +1/2·s、fertility −1/4·s、support −1/2·s）；
确定性 ID（social-v1）；StateChange INSERT 语义扩展（coordinator 统一
写入、引擎零 commit）；world_state_hash v5（v2/v3/v4 冻结）。全部标注
于 M2D_SOCIAL_FOUNDATION.md §34。

## 5. Social Schema
migration e8a1c5d7f2b4：lineages/institutions（M0 表）扩展聚合连续性
列；新表 households / settlement_social_state（含 stress min/max
见证值）/ social_feedback_state。全部 BigInteger；确定性 id 字符串；
唯一约束显式命名。

## 6. Household Model
households = 聚合家庭（非个人模拟）：represented_population /
generation / lineage_ref / anchor_group_ref / state（ACTIVE/
DISSOLVED）/ formation_version。12,000 居民 ≠ 12,000 agent。

## 7. Population Reconciliation
m2d-coverage-v1（full）：每 (settlement, species) ACTIVE household
represented 之和 == population 总量；增长 round-robin（id 序）、衰减
规模大者先扣、无户则形成、size>6 拆分、归零溶解；unallocated 恒 0。
SD5-9 实测 60/120y 全程守恒。

## 8. Household Lifecycle
形成（无户且有人口 → size≤5 户）/ 拆分（size>6 → 对半，generation+1，
lineage 继承）/ 溶解（size=0 → DISSOLVED）。事件 HOUSEHOLD_FORMED/
SPLIT/DISSOLVED。基线：30 splits、2 dissolved、0 formed（初始全覆盖）。

## 9. Lineage Model
lineages（M0 表扩展）：lineage_id/origin_settlement/represented_
population/household_count/generation/status/founded_tick/
parent_lineage_ref。Lineage ≠ Household；跨聚落结构支持（SD16）。

## 10. Lineage Lifecycle
涌现（gen≥3、size≥6、无 lineage → FOUNDED，每聚落每步≤1）；分化
（household_count≥12 → 最大成员户立子 lineage）；灭绝（represented=0
且 household_count=0 → EXTINCT，identity 永久保留）。基线：3 founded、
2 子 lineage（parent 非空）、最大 generation 6；灭绝由 SD14 构造
场景覆盖（B 人口归零 → EXTINCT 且 lineage_id 保留）。

## 11. Persistent Person Boundary
晋升接口冻结（未来仅：长期叙事意义/关键机构职务/重大事件参与者/主人
关注）；M2d 默认 0 —— SD33 实测 120y persons=0。

## 12. Institution Model
institutions（M0 表扩展）：institution_id/kind（结构类型）/
settlement_ref/state/founded_tick/profile_ref。TEST fixture 仅
COMMUNITY_BODY；正式机构 profile UNKNOWN。

## 13. Institution Lifecycle
ACTIVE → DECLINING（cohesion<500k）→ DORMANT（<300k）→ DISSOLVED
（pop<50）；恢复 ACTIVE（cohesion≥600k）；DISSOLVED 终态。成立：
pop≥80 且无存续机构。基线：B 机构 → DECLINING（1 次状态转移）；
机构不产生 active modifier（SD19）。

## 14. Settlement Social State
stress/cohesion/household_stability/mobility_pressure/unallocated +
stress_min/max 见证值；整数 fixed-point 0..1,000,000（m2d-scale-1）。

## 15. Economic Inputs
只经 staged economic_pressure_state（unmet/demand 比值）；不读
resource_nodes/resource_stocks/production_state（SD21 源级实测）；
shortage≠骚乱（版本化压力公式，非直接映射）。

## 16. Ecological Inputs
只经 staged ecology_feedback_state（environmental_stress）；不读
ecology_state（SD22 源级实测）。

## 17. Social Feedback
social_feedback_state（committed）：migration_modifier / fertility_
context / social_support / social_stress（全 num/den fixed-point）。

## 18. Next-Step Feedback
SOCIAL_FEEDBACK_LATENCY = NEXT_COMMITTED_STEP。SD23 实测：第 1 步
DEMOGRAPHY 与无社会夹具全等；SD24 实测：预置迁移压力 3/2 → 次年迁出
上升且确定性复现。DEMOGRAPHY 保持人口唯一 owner（只经 clamp
[1/2,2] modifier，不直接改 births/deaths）。

## 19. Event Model
HOUSEHOLD_FORMED/SPLIT/DISSOLVED、LINEAGE_FOUNDED/EXTINCT、
INSTITUTION_FOUNDED/STATE_CHANGED/DISSOLVED、
SOCIAL_STRESS_THRESHOLD_CROSSED —— Domain Events，非自然语言故事。

## 20. Event Volume Control
只在形成/溶解/显著转移/阈值跨越发事件；普通计数变化留在 State/
metrics（120y 事件流实测规模合理）。

## 21. Entity Identity
IDENTITY_SCHEMA_VERSION="social-v1"：sha256(social-v1|world|kind|
settlement|species|founded_tick|seq)[:16]；seq 含本步已插入数 ——
retry 不生成第二 identity（SD12/17/34-36 实测）；无 UUID4/rowid。

## 22. RNG
SOCIAL 独立 substream；算法零 RNG（SD32 实测：extra_draws=11 →
五引擎结果与哈希全不变）。

## 23. World Hash
WORLD_STATE_HASH_SCHEMA_VERSION 4 → 5：v5 覆盖全部社会状态域；
canonical 行序无关（SD31）、restart 稳定；v2/v3/v4 显式冻结。

## 24. Event Hash
EVENT_STREAM_HASH_SCHEMA_VERSION=1；社会事件 payload 全覆盖
（SD29 实测）；uid v1 128-bit（SD28 实测）。

## 25. Fencing
SD38/S9 实测：stale writer → FENCING_VIOLATION，Social 0
authoritative write。

## 26. Idempotency
SD34-37 实测：同区间 retry → 零重复 household/lineage/institution/
事件/checkpoint/时间推进。

## 27. Crash Matrix（S1–S10）
S1 before Social / S2 mid household / S3 after household / S4 mid
lineage / S5 after lineage / S6 mid institution / S7 after Social
staged / S8 during DB write / S9 fencing recheck / S10 ACK lost。
恢复后全状态域一致（S1–S8 参数化 + SD39-42 + S9 + SD43 实测）。

## 28. Commit Ack Lost
SD43 实测（post-durable-commit 注入）：durable 已提交 → restart →
ALREADY_COMMITTED；household/lineage/institution/事件/反馈零重复。

## 29. Checkpoint
TIME_COMMITTED + WORLD_COMMITTED 双层原子；SD44 实测 checkpoint
hash == v5 且 engine_versions 含 SOCIAL —— 社会状态与人口/资源/经济/
生态/时间同一 committed world semantic step。

## 30. 120-Year Integrated Baseline
mini_world_v1（M2d integrated：2 settlements + 5 引擎 + 80 聚合家庭
+ B 1 lineage（3 户）+ 2 COMMUNITY_BODY + TEST_SOCIAL_PROFILE_001），
120 福地年。数值见报告末 TOTAL 段。场景：A/B 家庭拆分（30）、B 家系
延续扩张至 gen 5 并分化出子家系、B 机构 DECLINING、压力阈值跨越、
社会反馈 240 次跨 Step 存续。灭绝路径由 SD14 构造覆盖（如实记录：
emergent 120y lineages_extinct=0 —— B 家系在 M2a 冻结迁移参数下持续
扩张；全部参数透明记录，无隐藏调参）。

## 31. Continuous/Chunked/Restart
SD47：120y == 30y×4（哈希/人口/资源/经济/生态/社会/metrics 全等）；
SD48：120y == 60+60（终态哈希/人口/压力 + 分片 metrics 合计全等）。

## 32. Performance
120y 五引擎 wall time 记录于基线 performance 字段（不进哈希）；
aggregate 无 per-person agent。

## 33. LLM=0
social.py 零 LLM 符号（SD49 源级实测）。

## 34. Network=0
SD50 实测：socket/urllib/http.client 全炸 → 5 年运行正常。

## 35. Wall Clock=0
SD51 实测：social.py 无 datetime.now/time.time/perf_counter/
time_ns/date.today。

## 36. PostgreSQL Compatibility
BigInteger + 确定性 id + 显式唯一约束；无 json_extract/rowid 依赖。
NOT LIVE VERIFIED；PRE_ACTIVATION_PG_GATE / PRE_ACTIVATION_PG_
COMMIT_AMBIGUITY_GATE = REQUIRED 继续登记。

## 37. Formal DB Audit
pre-m2d 备份（blessed_land.sqlite.pre-m2d-backup，与 pre-m2a/b/c 并存
保留；备份 sha256 与迁移前一致 97e98965…b8908）；迁移后
FORMAL_AUDIT_M2D=PASS：head=e8a1c5d7f2b4；NOT_ACTIVATED；seed=NULL；
tick=NULL；27 张业务/基建表全 0（含 households/lineages/institutions/
settlement_social_state/social_feedback_state）；TIME_ADVANCE=0；M2
checkpoint=0；integrity ok。迁移后新 sha256 =
`648dc9c5736334ba19a5a7880f280ed02c4d30ff9a13e4426af5b186425213f9`。

## 38. World Seed Freeze
SD53 实测：SIM 目录零 world_seed/零 04_population_baseline 引用；
population/species/settlements/institutions 正式值未消费；M6 才创建。

## 39. Alembic Migration
e8a1c5d7f2b4_m2d_social：lineages/institutions 只 ADD 列；新表 3 张；
历史 13 步完整链；EXPECTED_SCHEMA_HEAD 三处同步；表数 28 → 31。

## 40. Regression Results
TOTAL_TESTS / TOTAL_PASS 见报告末（325 旧 + 65 新：SD1–SD55 +
S1–S8 参数化 + S9 + 120y 基线复现）。

## 41. New Test Matrix
SD1/2 协议与管线；SD3 零 commit；SD4 整数计数；SD5/6 守恒与无重复
占用；SD7-9 出生/死亡/迁移对账；SD10/11 形成/溶解确定性；SD12/13/14
lineage 身份/跨代/灭绝；SD15 无环；SD16 跨聚落；SD17-19 机构；SD20
有界；SD21/22 声明输入；SD23/24 反馈延迟；SD25-27 所有权；SD28/29
uid/事件哈希；SD30/31 v5/行序；SD32 RNG；SD33 零 Person；SD34-37
幂等；SD38 fencing；SD39-42/S1-S8 崩溃矩阵；SD43 ack lost；SD44
checkpoint；SD45/46 120y 完成+全不变量；SD47/48 chunk/restart；
SD49-51 LLM/网络/wallclock；SD52 正式 profile；SD53-55 Seed/正式库。

## 42. Git/Tag
独立 M2d commit（不混 M3/M4/M5/M6）；tag m2c-ecology-ready @ 09f2907
保留；既有 tag m1-golden-baseline / m1.1-live-verified /
m2-preflight-hardened / m2a-population-ready /
m2b-resource-economy-ready 保留。

## 43. Workspace
`git status` clean；M2a/b/c 基线产物在测试重写后已还原为冻结版本。

## 44. Known Risks
- emergent 120y 无 lineage 灭绝（B 家系扩张并分化）—— 灭绝由 SD14
  构造场景覆盖；正式世界灭绝动力学待 Canon 参数。
- household 合并未实现；DORMANT lineage 无进入规则。
- 社会压力公式/阈值全为 m2d 版本化 NEW_PROPOSAL。
- PG 兼容 NOT LIVE VERIFIED。
- 120y 基线全 TEST_FIXTURE_ONLY，不构成任何正式世界推断。

---

```
M2D_SOCIAL_FOUNDATION_READY
```

```
TOTAL_TESTS = 390
TOTAL_PASS = 390

WORLD_RUNTIME_STATUS = NOT_ACTIVATED
seed = NULL
current_blessed_tick = NULL
formal_population = 0
formal_persons = 0
formal_households = 0
formal_lineages = 0
formal_institutions = 0
official_world_events = 0

120y baseline（TEST_FIXTURE_ONLY）：
initial_population = 400
final_population = 442
births = 868
deaths = 826
immigration = 602
emigration = 602

initial_households = 80
final_households = 108（active；总计 110 行）
households_formed = 0
households_split = 30
households_dissolved = 2
mean_household_size = 4.093

initial_lineages = 1
final_lineages = 4（含 2 条子 lineage，parent_lineage_ref 非空）
lineages_founded = 3
lineages_extinct = 0（emergent；灭绝路径由 SD14 构造场景覆盖）
max_lineage_generation = 6

initial_institutions = 2
final_institutions = 2（A=ACTIVE，B=DECLINING）
institutions_founded = 0
institutions_dissolved = 0
institution_state_transitions = 1

initial_social_stress = {A: 0, B: 0}
final_social_stress = {A: 245,645, B: 642,943}
min_social_stress = {A: 0, B: 0}
max_social_stress = {A: 280,126, B: 651,584}
stress_threshold_crossings = 1
social_feedback_applications = 240

runs = 120
steps = 120
checkpoints = 240
events = 1713（split 30 / dissolved 2 / lineage_founded 3 /
institution_state_changed 1 / stress_threshold 1）
wall_seconds = 10.881（仅性能字段）

final_world_state_hash = 16a6020ea9f16ff83698e1e08f52c4f82286c8841de25a18fa722e6ed8e4eac2
final_event_stream_hash = bda4c7c7b3dd4a5564bb347a4ec227feb81002e4a421a396e21f4397e419f64c

formal_db_sha256_after_migration = 648dc9c5736334ba19a5a7880f280ed02c4d30ff9a13e4426af5b186425213f9
```
