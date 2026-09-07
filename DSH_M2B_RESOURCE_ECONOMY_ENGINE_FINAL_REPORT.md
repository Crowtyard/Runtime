# DSH_M2B_RESOURCE_ECONOMY_ENGINE_FINAL_REPORT

> 执行方：DSH。阶段：M2B_RESOURCE_ECONOMY_ENGINE（RESOURCE Engine +
> ECONOMY Engine，两个独立 Pipeline Stage，不得合并）。
> 基线：M2A_POPULATION_ENGINE_READY（3971252，tag m2a-population-ready，
> 198/198 PASS）。
> 完成后 STOP：不进入 M2c/M2d/M3/M4/M5/M6，不激活 World Seed。

## 1. Baseline
M2a accepted：commit 3971252（tag m2a-population-ready 已打）。回归
198/198 全保留；M2a 120y 基线产物逐字节复现（v2 冻结表集/字段集保证）。

## 2. Source Design Recovery
重新审计 runtime_design 06/07/08/09 + Preflight Contract：
- 06（人口）：M2a 已恢复（cohort 行模型）。
- 08（资源经济）：生产链 RESOURCE_NODE → EXTRACTION → … → STORAGE →
  CONSUMPTION/RESERVE；节点八态（WS-0703，CAUSE_BASED）；无无限资源；
  市场简化模型（WS-0706）。
- 07（社会）/09（生态）：本次只做边界审计，不实装。
- Preflight Contract：ENGINE_ORDER 冻结、所有权表、staged feed-forward、
  双层 checkpoint 均沿用。

## 3. Conflicts Found
- C1：08 号 §4 市场简化模型（价格=基准价×调节因子）与 M2b 禁价列表冲突
  → 裁决：市场/价格推迟，M2b 只建实物 stock-flow 层。
- C2：08 号生产链 PROCESSING/TRANSPORT/MARKET 环节 > M2b 范围 →
  本阶段实装 EXTRACTION/STORAGE/CONSUMPTION/RESERVE。
- C3：08 号节点八态全量状态机 > M2b 范围 → 收敛为 STABLE→EXHAUSTED
  （储量耗尽，原因驱动），其余状态属后续里程碑。

## 4. New Proposals
整数 minor units 数量模型（scale=1_000_000）；离散效率表（08 号 risk 的
aggregate 化，{100%,95%,90%,85%}）；生产配方结构 + labor 代理
（aggregate 人口折算，绝不生成职业 NPC）；m2b-transfer-v1 转移策略
（单趟贪心，非市场）；EconomicPressureSignal committed 表；
feedback.py 适配器（TEST_FIXTURE_ONLY）；world_state_hash v3；
resource_stocks 7 个 ledger 计数器字段。全部标注于
M2B_RESOURCE_ECONOMY_ENGINE.md §32。

## 5. Resource Schema
migration b7d2f4e9c1a5：resource_nodes 扩展 9 列（resource_profile_ref /
settlement_relation / remaining_reserve / extraction_capacity /
extraction_carry / last_extracted_minor / engine_version / state_version /
updated_blessed_tick）+ 新表 resource_profiles。

## 6. Economy Schema
新表 resource_stocks（quantity + consumption_carry + 7 个 cum ledger
计数器 + 版本/刻度）/ production_recipes / production_state /
economic_pressure_state。全部 BigInteger minor units；唯一约束显式命名
（uq_*）。

## 7. Quantity / Fixed-Point Model
权威数量 = 整数 minor units；1 canonical unit = quantity_scale minor
units（TEST=1_000_000）。生产/消费/开采/转移的 DB 真值全整数；流率
Fraction/整数有理；不整除部分经持久化 carry（extraction_carry /
consumption_carry / production_carry）跨 step 存续。禁止 float 权威量
（RE_INV_08/09，RB6/RB44/RB45 实测）。

## 8. Resource Node Model
节点 = 可用性载体（非 NPC/非地理叙事实体/非 Ecology）。M2b 字段含
profile 引用、归属聚落、剩余储量、名义开采容量、开采进位、本步开采量
（staged feed-forward 给 ECONOMY）、引擎版本、状态版本、更新刻度。
储量 NULL = 未定级 → 不可开采（正式安全）。

## 9. Extraction Algorithm
`attempt = (carry + effective_capacity × Δticks) // TICKS_PER_YEAR`；
`effective_capacity = nominal × efficiency`（离散抽样，只降不升）；
`extracted = min(attempt, remaining_reserve)`；
`reserve_end = reserve_start − extracted + regeneration(0)`。
耗尽 → EXHAUSTED + RESOURCE_DEPLETED（state_version+1）。RE_INV_03/04
恒成立（RB9/RB10/RB11 实测：极小储量耗尽恰为 0，绝不负）。

## 10. Inventory Model
resource_stocks 每 (settlement, resource) 行：quantity + 7 个累计计数器
（extracted/produced/input/imported/exported/consumed/lost）+
consumption_carry。库存恒 ≥ 0；需求超库存 → fulfilled/unmet 分账，绝不
写负库存（RB19）。

## 11. Production Algorithm
`batches = min(容量进位, 输入库存//input_qty, labor_pool//
labor_per_batch)`；input/output/loss 全整数显式；cum_produced 记 GROSS
、loss 单独计 —— §18 ledger 公式逐项可解释（RB13/RB14/RB23 实测）。

## 12. Consumption Algorithm
`demand = Σ_species(per_capita_demand[resource] × pop × interval)`；
per_capita_demand 为 Fraction（TEST：食物 7/6 canonical unit/人/年），
经 quantity_scale 转 minor；亚年余数入 consumption_carry 持久化
（RB7/RB45 实测 carry 有界：< 6×10⁶）。

## 13. Demand / Fulfillment
demand ≥ 0；fulfilled ≤ demand；fulfilled ≤ 可用库存；unmet = demand −
fulfilled。三者入事件与压力状态（RB16/RB17/RB18 实测）。

## 14. Transfer Algorithm
TRANSFER_POLICY_VERSION="m2b-transfer-v1"：每资源单趟贪心，donor
surplus（stock_after_production − demand）→ receiver need；X =
min(need, surplus)；source_delta=−X、destination_delta=+X；全局净 0；
无双花/重复导入（内存 surplus 逐次扣减；RB20/RB21/RB22 实测）。

## 15. Stock-Flow Ledger
`ending = starting + extraction + production_output + imports −
production_input − consumption − exports − losses`（RB23 逐
(settlement, resource) 实测对账；RB20 全局对账）。

## 16. Shortage / Surplus
economic_pressure_state：demand/fulfilled/unmet/shortage_ratio（num/den
约分）/sustained_shortage_steps/stress_level（NONE/LOW/HIGH）。纯机器
经济状态，零饥荒/战争/瘟疫/富裕叙事（RB24 确定性实测）。

## 17. EconomicPressureSignal
committed authoritative state（economic_pressure_state 表），随
WORLD_COMMITTED 同事务提交；restart 后由 committed 状态完全重建
（RB25 实测 15+15 restart == 30 continuous，压力行逐字段相等）。

## 18. Cross-Engine Feedback
ECONOMY → DEMOGRAPHY 经 feedback.py 适配器：DEMOGRAPHY 读
start-of-step snapshot 的压力行 → external_mortality_modifier（仅
TEST-SPECIES-001：NONE=0 / LOW=1/1000 / HIGH=1/100）。正式种族
UNCONFIGURED：任何压力映射一律 0（RB28）。

## 19. Feedback Lag Verification
CROSS_ENGINE_FEEDBACK_LATENCY = NEXT_COMMITTED_STEP。RB26 实测：第 1
步整合运行与纯人口运行 DEMOGRAPHY metrics/population 全等（同 step
经济不影响人口）。RB27 实测：step1 max_pressure_level=0；step2+ 压力
非 0（上一步 B 聚落短缺进入 committed 后，下一步 DEMOGRAPHY 才读取）；
两环境逐 step 复现一致。

## 20. Engine Ownership
RESOURCE → resource_nodes；ECONOMY → resource_stocks /
production_state / economic_pressure_state；resource_profiles /
production_recipes = 只读配置表。同 Step 单趟 feed-forward，无
RESOURCE→ECONOMY→RESOURCE 循环（RB3 顺序冻结实测）。

## 21. RNG
RESOURCE 独立 substream：每 step 每节点 1 次离散效率抽样；
ECONOMY 零 RNG（draw_count=0，确定性规则优先）。RB34 实测 RESOURCE
多抽 7 次 → DEMOGRAPHY 完全不变；RB35 实测 ECONOMY 多抽 5 次 →
RESOURCE/DEMOGRAPHY/ECONOMY 结果与哈希全不变。

## 22. Event Model
aggregate domain events：RESOURCE_EXTRACTED / RESOURCE_DEPLETED /
PRODUCTION_COMPLETED / CONSUMPTION_FULFILLED / RESOURCE_SHORTAGE /
RESOURCE_TRANSFERRED。全整数 payload；绝不逐单位资源产生事件。
EVENT_UID_SCHEMA_VERSION=1（128-bit，RB30 实测同 replay 同 uid、无
重复、全 hex32）。

## 23. Event Stream Hash
EVENT_STREAM_HASH_SCHEMA_VERSION=1 不变；所有 Resource/Economy 事件
进入增量链（RB31 实测：转移 100→70 → 哈希必不同）。

## 24. World State Hash
WORLD_STATE_HASH_SCHEMA_VERSION 2 → 3：v3 覆盖 population + resource
node/profile + inventory + production state + pressure state；canonical
+ 行序无关（RB32 单库存量变动 → 哈希变；RB33 逆序重插 → 哈希同）。
v2 语义冻结（M2a 表集/字段集显式冻结）——M2a 基线逐字节复现；
coordinator 按管线状态域选择 v2/v3。

## 25. Checkpoint Consistency
TIME_COMMITTED + WORLD_COMMITTED 同事务原子；权威恢复 = latest
complete WORLD_COMMITTED。RB42 实测：R8（ack 丢失）回滚后两层皆无，
重试后 TIME 与 WORLD 同 tick（1,000,000），TIME 绝不新于 WORLD。

## 26. Crash Matrix（R1–R8，参数化实测）
R1 after DEMOGRAPHY staged（engine:RESOURCE）/ R2 mid RESOURCE /
R3 after RESOURCE staged（engine:ECONOMY）/ R4 mid ECONOMY /
R5 after ECONOMY staged（after_engines）/ R6 during authoritative write
（during_apply）/ R7 before WORLD checkpoint（事件已写未提交，原子对）
/ R8（真实语义 = **PRE_COMMIT_AFTER_WORLD_CHECKPOINT_STAGED**，
注入点 after_checkpoint，位于 DB commit 之前；真正的 COMMIT ACK LOST
由追加任务 M2B_COMMIT_AMBIGUITY_HARDENING 的 CA1–CA13 覆盖）。每个注入点：tick=0、储量
未动、无 M2 checkpoint、事件零残留；干净重试 == 参考一次成功（终态
哈希相等）。

## 27. Fencing
RB36 实测：stale writer（lease 被窃）提交 → FENCING_VIOLATION；
population/resource/inventory/events/checkpoint/hash 全部 0 authoritative
write。

## 28. Idempotency
同 interval retry：零重复开采（RB37：reserve 恰减 1 次）、零重复生产/
消费/压力（RB38）、零重复事件（RB39：uid 集合不变）、零重复转移
（RB22：库存与事件不变）。

## 29. 120-Year Integrated Baseline
mini_world_v1（M2b integrated：2 settlements + TEST-SPECIES-001 +
TEST-RESOURCE-001/002 + TEST 配方 + TEST 经济 profile），120 福地年，
管线 DEMOGRAPHY→RESOURCE→ECONOMY 真实全部执行。数值见报告末
TOTAL 段。全数字 TEST_FIXTURE_ONLY，非 Canon。

## 30. Continuous / Chunked / Restart
RB46：120y continuous == 30y×4 chunked（终态哈希/人口/资源/经济/
全部引擎 metrics 全等）。RB47：120y == 60+60 restart（终态哈希/人口
end/储量/库存 + 分片 metrics 合计全等）。RB7：carry 在 1+1 重启下
无损（终态哈希/库存全等）。

## 31. Performance
120y integrated wall = 8.828s（M2a 纯人口 7.358s；+RESOURCE+ECONOMY
仅 +1.5s）。aggregate：每步 O(nodes + settlements×(recipes+resources))
整数运算，无 per-unit/per-person agent。wall 仅为性能字段，不进哈希。

## 32. LLM=0
resource.py/economy.py/feedback.py 零 LLM 符号/调用（RB48 源码扫描
实测）；完整 DEMOGRAPHY→RESOURCE→ECONOMY 路径 LLM calls=0。

## 33. Network=0
RB49 实测：monkeypatch socket/urllib/http.client 为必炸 → 5 年整合
运行正常完成。核心零网络读取。

## 34. Wall Clock Isolation
RB50 源码扫描实测：resource.py/economy.py 无 datetime.now/time.time/
perf_counter/time_ns/date.today。引擎只认 SimulationInterval。

## 35. PostgreSQL Compatibility
BigInteger 全整数权威列（SQLite INTEGER 64-bit ↔ PG BIGINT）；核心
算法不依赖 json_extract/隐式类型/rowid/INSERT OR REPLACE；唯一约束
显式命名。未实跑 PG —— 如实标注风险（代码级审计结论）。
**PRE_ACTIVATION_PG_COMMIT_AMBIGUITY_GATE = REQUIRED**（追加任务
M2B_COMMIT_AMBIGUITY_HARDENING 登记）：真实 COMMIT ACK ambiguity 为
数据库事务层问题，PG 部署的 Pre-Activation Gate 必须重跑同类场景，
SQLite 实测不得声称 PG 已验证。

## 36. Formal DB Audit
迁移前 pre-m2b 备份（blessed_land.sqlite.pre-m2b-backup，与
.pre-m2a-backup 并存，均保留；备份 sha256 与迁移前一致
5a379a6169ab47537…b1658a）；迁移后 FORMAL_AUDIT_M2B=PASS：alembic
head=b7d2f4e9c1a5；NOT_ACTIVATED；seed=NULL；tick=NULL；全部业务/基建
表 0（16 旧表 + 5 新表）；TIME_ADVANCE=0；M2 checkpoint=0；PRAGMA
integrity_check=ok。迁移后新 sha256 =
`23561030e5ad0765ce988158fa4d95a56c97b763f6678fe2092ce05133d9c71d`。

## 37. World Seed Freeze Audit
RB51 实测：SIM 目录全部 .py 零 world_seed / 零 04_population_baseline
引用；正式库 resource_nodes=0、resource_stocks=0（Seed 包只读，约
12,000 人/正式资源/聚落 Seed 均未写入 DB）。M6 才激活。

## 38. Alembic Migration
b7d2f4e9c1a5_m2b_resource_economy：只 ADD（9 列 + 5 表），不改旧
migration；历史 11 步完整链（7253f352f69e → … → a7b3e9f1c5d2 →
b7d2f4e9c1a5）。EXPECTED_SCHEMA_HEAD 三处同步（runtime_host /
migrate_db_to_plugin_data / conftest）。

## 39. Regression Results
TOTAL_TESTS / TOTAL_PASS 见报告末。198 旧套件全保留（M2a 基线
逐字节复现）；62 M2b 项 = RB1–RB53 + R1–R8 参数化矩阵 + 120y 基线
产物复现。

## 40. New Test Matrix
RB1/RB2 协议；RB3 管线顺序；RB4/RB5 零 commit；RB6 整数 fixed-point；
RB7 carry 重启；RB8 开采确定性；RB9/10/11 容量/储量/非负；RB12–14
生产确定性/输入不超支/配方比率；RB15–18 消费与需求满足；RB19 库存
非负；RB20–22 转移守恒/无双花/幂等；RB23 ledger 对账；RB24 短缺确定
性；RB25 压力重启持久；RB26/27 反馈延迟与通道；RB28/29 正式 profile
UNCONFIGURED；RB30/31 uid/事件流哈希；RB32/33 v3 覆盖与行序无关；
RB34/35 RNG 独立；RB36 fencing；RB37–39 重试幂等；RB40/41/R1–R8 崩溃
矩阵；RB42 双 checkpoint 一致性；RB43–45 120y 完成+全不变量；RB46/47
chunk/restart 等价；RB48–50 LLM/网络/wall-clock=0；RB51–53 Seed 冻结/
正式库空/完整性。

## 41. Git Commit / Tag
独立 M2b commit（不 squash，不混 M2c/M2d/M3）；tag
m2a-population-ready 指向 3971252 保留；既有 tag
m1-golden-baseline / m1.1-live-verified / m2-preflight-hardened 保留。

## 42. Workspace Clean
`git status` clean（world.db*、backups/*.db 由 .gitignore 排除；M2a
基线产物在测试重写后已还原为冻结版本）。

## 43. Known Risks
- PG 兼容未实跑真实 PostgreSQL（代码级审计）。
- 转移策略 v1 为 NEW_PROPOSAL 简单贪心；多配方同输入优先级未定义。
- 正式种族/资源 profile 全 UNCONFIGURED：出现即报错。
- 120y 基线为 TEST_FIXTURE_ONLY（含 B 聚落长期短缺的压力场景），
  不构成任何正式世界推断。

---

```
M2B_RESOURCE_ECONOMY_ENGINE_READY
```

```
TOTAL_TESTS = 260
TOTAL_PASS = 260

WORLD_RUNTIME_STATUS = NOT_ACTIVATED
seed = NULL
current_blessed_tick = NULL
formal_population = 0
formal_resource_nodes = 0
formal_resource_stocks = 0
official_world_events = 0

120y baseline（TEST_FIXTURE_ONLY）：
initial_population = 400
final_population = 455
births = 923
deaths = 868
immigration = 528
emigration = 528

initial_resource_reserve = 400,000,000,000 minor（400,000 units）
final_resource_reserve = 265,120,000,000 minor（265,120 units）
total_extracted = 134,880,000,000 minor（134,880 units）

initial_stock = {ORE: 1,000,000,000, FOOD: 100,000,000} minor
final_stock = {ORE: 49,480,000,000, FOOD: 0} minor

total_demand = 61,974,500,068 minor
fulfilled_demand = 42,868,000,000 minor
unmet_demand = 19,106,500,068 minor

total_production_input = 86,400,000,000 minor
total_production_output = 42,768,000,000 minor（net；gross 43,200,000,000，loss 432,000,000）

imports = 112,100,001 minor
exports = 112,100,001 minor
transfer_total = 112,100,001 minor
shortage_steps = 231（B 120 + A 111）

final_world_state_hash = 0c6dbb58c5028522f3778b9a02c574e90adbf502df4b2c7dff0a1ceb8ff1341c
final_event_stream_hash = 5c9a375fe52e877f068d4a05464a40f6d8cb1d908b764c66cc75139873ca8254

runs = 120
steps = 120
checkpoints = 240
domain_events = 1557（extracted 120 / production 120 / consumption 240 /
transferred 9 / shortage 231 / + demography & TIME_ADVANCE）
wall_seconds = 8.828（仅性能字段）

formal_db_sha256_after_migration = 23561030e5ad0765ce988158fa4d95a56c97b763f6678fe2092ce05133d9c71d
```
