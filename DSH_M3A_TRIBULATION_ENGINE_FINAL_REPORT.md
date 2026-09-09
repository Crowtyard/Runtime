# DSH_M3A_TRIBULATION_ENGINE_FINAL_REPORT

> 执行方：DSH。阶段：M3A_TRIBULATION_ENGINE（真实灾劫引擎 / 确定性生命周期 /
> 跨域影响 / 离线自治 / 恢复与资源继承基础）。
> 基线：tag m2-engine-set-frozen @ 973cad5（455/455）+ M3 Preflight @ 7669b06。
> 交付后立即 STOP：不进入 M3b/M3c/M4/M5/M6，不激活世界，不推进正式时钟，
> 等待主人明确批准。

## 1. Verdict Summary

M3A_TRIBULATION_ENGINE 全部验收项达成：
- 全量测试 519/519 PASS（fast 506 + long 13；M2 冻结基线逐字节复现）；
- 300y 合成基线生成并二次运行复现（final_world_state_hash /
  final_event_stream_hash 全同）；
- 正式权威库 pre-m3a 备份 → 迁移 → FORMAL_AUDIT_M3A PASS（NOT_ACTIVATED、
  9 张灾劫表 0 行）；
- TRIBULATION_RANK_INFERENCE = 0；M2_SIMULATION_SEMANTICS_MANIFEST.json
  零修改；LLM/网络/wall-clock = 0。

## 2. Baseline

M3a 开工前：HEAD=7669b06（M3 Preflight），tag m2-engine-set-frozen @
973cad5，455/455 PASS，正式库 head=e8a1c5d7f2b4（sha256
648dc9c5736334ba19a5a7880f280ed02c4d30ff9a13e4426af5b186425213f9）。
M3a 新增 migration f1b3c5d7e9a2（down_revision=e8a1c5d7f2b4，只 ADD 不
改旧 migration）。

## 3. Scope

TRIBULATION = WORLD_METABOLISM：排期窗口 → 确定性 Episode → 九阶段
生命周期 → 跨域 Impact → 恢复 → 资源继承候选 → NEW_NORMAL。真实引擎
（非占位符）。禁止：LLM/网络/wall-clock；叙事生成；M3b 历史查询服务；
正式库自动排期；Seed 激活；修炼推断。

## 4. Source Recovery

CONFIRMED_EXISTING_SCOPE（05/06/08/09）：灾劫为世界代谢、残留改变环境、
资源继承候选需观察/稳定/开发且由 Resource Engine 最终决定。
IMPLIED：10/50/100 年窗口、高层级替代低层级、离线自治、恢复跨 Step。
CONFLICT_FOUND：历史叙事/排行榜 → 属 M3b，本阶段仅最小因果字段。

## 5. Canon/Lore Boundary

TRIBULATION_RANK_INFERENCE=0（冻结常量，TA1 断言）。TIER 仅为调度强度档
（REGULAR/MAJOR/CENTENNIAL），与世界观任何特定灾劫名称解耦；事件 effect
只含结构化字段，无叙事文本（WS-0905）。

## 6. Engine Protocol

TribulationEngine：engine_id=TRIBULATION、engine_version=m3a-tribulation-1、
simulate(ctx) -> EngineResult（可返回 tribulation_plan 触发跨域应用）。
零 commit/LLM/网络/wall-clock；RNG 全部经 RngService 子流。

## 7. Ownership

ENGINE_OWNERSHIP["TRIBULATION"] = 7 张灾劫表（episodes/decisions/
impact_plans/recovery_states/residual_changes/succession_candidates/
causal_links）。跨域影响不自写他域表——方案 B：Coordinator 在
TribulationEngine 返回 plan 后依 sorted(DOMAIN_ADAPTERS) 调用各
Domain-owned Adapter（同一 WorldMutationContext 原子应用）。

## 8. Nine-stage Lifecycle

LIFECYCLE = (PRECURSOR, PREPARATION, IMPACT, RESPONSE, STABILIZATION,
RESIDUAL_CHANGE, RECOVERY, RESOURCE_SUCCESSION, NEW_NORMAL)（TA2 断言
元组全等）。每 Step 至多一次转移；转移 tick 恒为整数 blessed tick。
entered_tick 为创建时刻不变量（修复：_advance 曾覆写 entered_tick →
阶段推进污染窗口年份；修复后 tier 替代在 50/100 年正确）。

## 9. Schedule & Tier Replacement

TEST_TRIBULATION_SCHEDULE_001：(REGULAR,10) / (MAJOR,50) /
(CENTENNIAL,100)。_tier_at_tick 用 max by TIER_ORDER：同年多档命中取
最高层级，不叠加成多场。TA4 实测：50y=MAJOR、100y=CENTENNIAL、
60y=REGULAR。

## 10. Deterministic Episode Identity

episode_id = deterministic_hex_id([world_id, simulation_version,
schedule_id, tier, scheduled_tick], bits=128,
schema=TRIBULATION_EPISODE_ID_SCHEMA_VERSION="tribulation-episode-id-v1")。
无 UUID4；同一窗口重放（catch-up 重试/ack-lost）得同 id → exactly-once。

## 11. Deterministic Target Selection

目标聚落：settlements 按 working_name stable 排序 + TARGET RNG 子流抽
下标。TA7 实测：逆序重插行序不变 → 目标集相同；TA6 跨库同 seed 同结果。

## 12. RNG Six Substreams

SCHEDULE/PROFILE/TARGET/IMPACT/RECOVERY/SUCCESSION 六子流（entity_scope
隔离）。TA8：extra_draws=5 多抽 IMPACT 不影响 schedule/target；TA36：
intensity 抽样不同 → event_stream_hash 不同（payload 入哈希）。

## 13. OwnerDecisionInput

submit_owner_decision（显式 API，不接聊天/UI/Companion）：action 白名单
STRATEGY/PRIORITIZE/EVACUATE/REBUILD；episode 必须存在；过期拒绝；错误
episode 拒绝；修改必 supersede（旧决策 SUPERSEDED 且内容不可变）；同
decision_id 重试幂等。六种场景：有效提交（TA12）、过期拒绝（TA13）、错误
episode 拒绝（TA14）、supersede 不可变（TA15）、幂等重试（TA12）、自主
回退（TA11）。

## 14. DEFAULT_AUTONOMOUS_RESPONSE_POLICY

离线无决策 → 常量 DEFAULT_AUTONOMOUS_RESPONSE_POLICY +
AUTONOMOUS_RESPONSE_SELECTED 事件。离线永不阻塞 catch-up：PREPARATION
阶段检查 staged decisions 后直接选定（OWNER_PLAN 或 AUTONOMOUS）。
300y 基线：29 次自治响应、0 Owner 决策。

## 15. Mitigation Cost

PREPARATION 声明 MITIGATION_COMMITTED（cost_basis=intensity_min）；
实际成本在 IMPACT 应用时由 Economy Adapter 按 inventory_damage 扣减
resource_stocks。无免费完美减灾（TA17：自主响应下仍真实损失）。

## 16. TribulationImpactPlan

plan_id = deterministic_hex_id([world_id, episode_id, "PLAN"],
bits=128, schema=IMPACT_PLAN_SCHEMA_VERSION="impact-plan-v2")。六类
risk 整数 fixed-point num/den；intensity 0..100；ecology_pressure
0..1_000_000；结构化 JSON 载荷（TA18 校验）。

## 17. Five Domain Adapters

Demography（population_groups.count 损失）、Resource（resource_nodes.
remaining_reserve 削减）、Economy（resource_stocks.quantity 扣减）、
Ecology（habitat_quality 降）、Social（households 位移 +
settlement_social_state.stress 升）。全部 clamp 下界；只写本域表
（TA19-23 源码断言：本域模型出现、他域模型名不出现）。

## 18. Atomic Cross-domain Application

全部 Adapter 同一 WorldMutationContext 原子应用；任一崩溃 → 全回滚。
TA24 实测：adapter:ECOLOGY 崩溃 → 时钟回滚到 12y、plan 0 行；重试后
plan 恰 1 行。TA48 T6/T8/T9（adapter:DEMOGRAPHY/ECOLOGY/SOCIAL）同证。

## 19. Causal Links（最小字段）

TRIBULATION_IMPACT_APPLIED 后写 TribulationCausalLink：episode_id /
correlation_id / cause_event_ids / trigger_event_id /
decision_event_ids / impact_plan_id / result_event_ids /
affected_entity_ids / state_change_ids。TA34：全部事件引用闭合（引用
uid 均存在于世界事件流）。M3b 查询/叙事不做。

## 20. Recovery across Steps

tribulation_recovery_states 整数 fixed-point（need/progress num/den）+
四需求字段。恢复非单步：progress 逐步递增（step=100//recovery_steps），
跨 catch-up 持久化。TA30：progress 含中间值且终达 100。

## 21. Residual Change

RESIDUAL_CHANGE 阶段写 tribulation_residual_changes（persistent=True，
payload.theme）。TA31：全部 persistent。灾劫残留永久改变环境条件。

## 22. Resource Succession Candidate

RESOURCE_SUCCESSION 阶段按 allow_candidate 生成候选（UNOBSERVED/NONE）。
候选 ≠ 节点：绝不自动物化（TA32：60y 后 node 数不变；TR_INV_15）。

## 23. NEW_NORMAL

SUCCESSION 后 status → COMPLETED，发 TRIBULATION_NEW_NORMAL_REACHED
（world_not_reset=True）+ TRIBULATION_EPISODE_COMPLETED。世界不重置。
TA33：非零影响后新常态 ≠ 无灾劫对照（人口总量不同）。

## 24. Adaptive Time Resolution

next_tribulation_boundary 返回 (from,to] 内最早边界（排期窗口命中 tick
或活跃 episode transition_tick），恒整数 tick、禁止浮点年份。
TA42/43：前兆/准备事件无遗漏；TA44（30y→3 REGULAR 窗口）、TA45
（120y→12 窗口，MAJOR/CENTENNIAL 各 1）实测。

## 25. Events & Deterministic UIDs

14 种事件类型（SCHEDULED/PRECURSOR_STARTED/PREPARATION_STARTED/
OWNER_DECISION_COMMITTED/AUTONOMOUS_RESPONSE_SELECTED/
MITIGATION_COMMITTED/IMPACT_STARTED/IMPACT_APPLIED/STABILIZED/
RESIDUAL_CHANGE_CREATED/RECOVERY_PROGRESS/
SUCCESSION_CANDIDATE_CREATED/NEW_NORMAL_REACHED/EPISODE_COMPLETED）。
event_uid = deterministic_event_uid（128-bit）。TA35：跨库重放全同无碰撞。

## 26. World State Hash v6

WORLD_STATE_HASH_SCHEMA_VERSION=6；v6 = v5 全字段 + 9 张灾劫表。
v2/v3/v4/v5 冻结为独立常量与函数；Coordinator 仅注册 TRIBULATION 引擎时
选 v6。TA37：episode 字段变化 → hash 变化。M2 路径（0.2.0-preflight）
逐字节不变（见 §31）。

## 27. Exactly-once / Fencing / Ack-lost / Crash

- TA38/39：重跑 30y 不重复建 episode/plan（幂等）；
- TA40：stale writer（fencing token 篡改）→ FencingViolation 零写入；
- TA41：COMMIT 已持久化但 ACK 丢失 → 重试 skipped=True（durable）；
- TA48 崩溃矩阵 11 例全过：engine:TRIBULATION（T1/T2 型）、
  impact_plan（T5）、adapter:DEMOGRAPHY/ECOLOGY/SOCIAL（T6/T8/T9）、
  recovery（T10）、succession（T13）、new_normal（T14）、
  before_checkpoint（T11）、after_engines（T12）——每例回滚到崩溃年前、
  重试续推进、事件 uid 无碰撞、plan 至多 1 行。

## 28. Crash Year Mapping（TA48）

REGULAR 生命周期逐年实测：10y 建 episode → 11y PRECURSOR → 12y
PREPARATION → 13y IMPACT（plan+adapters）→ 14y RESPONSE → 15y
STABILIZATION → 16y RESIDUAL_CHANGE → 17y RECOVERY 建状态 → 18y 首个
progress → 19y 满 → 20y SUCCESSION → 21y NEW_NORMAL/COMPLETED。
崩溃注入点与年份按此映射，逐年前进到 y-1 再注入。

## 29. Database Schema（9 表）

f1b3c5d7e9a2_m3a_tribulation：tribulation_profiles / schedules /
episodes / decisions / impact_plans / recovery_states /
residual_changes / resource_succession_candidates / causal_links。
规范化结构列 + 六对 risk num/den（_risk_cols）+ uq_* 唯一约束 +
JSON 仅载荷。SQLite+PG 双兼容（BigInteger/Boolean/JSON 标准类型）。

## 30. Formal World Contract

正式权威库迁移后：NOT_ACTIVATED、37 张业务表全部 0 行（含 9 张灾劫表）、
无 TEST profile/schedule。TEST_PROFILES/TEST_SCHEDULE 仅存在于
mini_world 夹具（seed_mini_world(with_tribulation=True)）。

## 31. M2 Frozen Compatibility

M2_SIMULATION_SEMANTICS_MANIFEST.json 零修改（git diff 空；TA58 断言
tribulation_slot=NOT_REGISTERED、world_state_hash_schema_version=5）。
MR4 更新为对照冻结常量 WORLD_STATE_HASH_SCHEMA_VERSION_V5=5。
M2a/b/c/d 120y 基线 + M2 integrated 1000y 5-seed 基线在 M3a 代码上
逐字节复现（suite 通过后经 git checkout 还原冻结文件，工作树零漂移）。
TRIBULATION_SLOT_STATE="NOT_REGISTERED" 模块常量与 run_step 守卫不变。

## 32. Test Suite（TA1–TA60）

tests/test_m3a_tribulation.py：64 个测试项（TA1–TA60 验收要求 +
300y 基线产物；TA19-23 五域 5 参数化、TA48 崩溃矩阵 11 参数化、
TA52-55 源码扫描合并）。全部 PASS。fast 套件 442 → 506。

## 33. 300y Synthetic Baseline

tests/baselines/m3a_tribulation_synthetic_300y_v1/：summary /
episode_index / schedule / profiles / decisions / final_state 六文件。
关键数字：30 窗口（24 REGULAR / 3 MAJOR / 3 CENTENNIAL）、29 完成、
29 自治响应、0 Owner 决策、29 继承候选、68 恢复步、4779 事件、
final_population=449、final_world_state_hash=0fc6ece0…、
final_event_stream_hash=8b117097…。基线测试二次运行 300y 复现两哈希
（TA49/50/51 + artifact 断言）。

## 34. Continuous == Chunked == Restart

TA46：120y 连续 vs 每 40y 重启 → 两哈希全同；TA47：60y + start_year=60
续跑 vs 连续 120y → 两哈希全同。RNG 按 (subsystem, blessed_period_tick,
entity_scope) 子流 → 与分段方式无关。

## 35. Owner Decision Scenarios

有效提交 + 幂等重试（TA12）、过期拒绝（TA13）、错误 episode 拒绝
（TA14）、supersede 不可变（TA15）、自主回退（TA11）——六场景全过。
决策提交经显式 API（runner owner_decisions 参数），离线不阻塞。

## 36. Invariants

TR_INV_01（episode_id 唯一）、TR_INV_02/03（stage ∈ LIFECYCLE）、
TR_INV_07（intensity ∈ [0,100]）、TR_INV_09/10/11（人口/库存/储量 ≥ 0）、
TR_INV_14（progress 有界）、TR_INV_15（候选不物化）——TA51 在 300y
全量断言通过。

## 37. Zero LLM / Network / Wall-clock

TA52-55 源码扫描：tribulation.py / tribulation_adapters.py /
m3a_runner.py 无 openai/anthropic/requests/httpx、无 datetime.now/
time.*/perf_counter。引擎零 commit/零网络/零 I/O 随机性。

## 38. PostgreSQL Compatibility

TA59：无 json_extract / rowid / INSERT OR REPLACE；JSON 一律 ORM 赋新
dict（SQLAlchemy 变更追踪）；fixed-point 整数列跨库一致。
PRE_ACTIVATION_PG_GATE / PRE_ACTIVATION_PG_COMMIT_AMBIGUITY_GATE 保持
REQUIRED（激活前 PG 实测门禁）。

## 39. Plugin Load Path Guard

TA60：main.py / plugin_shell 不含 TribulationEngine /
next_tribulation_boundary / run_m3a_world / submit_owner_decision /
with_tribulation 引用——插件启动绝不调度正式灾劫。

## 40. World Seed Freeze

TA57：world_seed/ MANIFEST.sha256.txt 全文件校验通过——世界种子字节
冻结，零写入。

## 41. Formal DB Backup & Migration

pre-m3a 备份 blessed_land.sqlite.pre-m3a-backup（sha256
648dc9c5736334ba19a5a7880f280ed02c4d30ff9a13e4426af5b186425213f9，
与 pre-m3a 原库一致）→ scripts/init_db.py 迁移 e8a1c5d7f2b4 →
f1b3c5d7e9a2 → seed NOT_ACTIVATED。旧备份 pre-m2a/2b/2c/2d 保留。

## 42. Formal DB Audit（M3A）

_m3a_final_audit.py：head=f1b3c5d7e9a2 ✓、NOT_ACTIVATED ✓、
37 表全 0 行（含 9 灾劫表）✓、TIME_ADVANCE=0 ✓、M2_PREFLIGHT
checkpoint=0 ✓、integrity=ok ✓ → FORMAL_AUDIT_M3A: PASS。
迁移后 sha256=2df1531c1b6a1418938cf9affe18389fd0c5e5a78d2d8f0044e9e60e2d99ff0b。

## 43. Simulation Semantics Manifest（M3A）

M3A_SIMULATION_SEMANTICS_MANIFEST.json：manifest_version=m3a-semantics-v1、
simulation_version=0.3.0-m3a、tribulation_engine_version=m3a-tribulation-1、
pipeline_order 含 TRIBULATION、九阶段、方案 B、hash schema 6（v5 frozen）、
test_only 排期/profile、formal_world 全 0、TRIBULATION_RANK_INFERENCE=0。
M2 清单零修改。

## 44. Known Issues Fixed This Stage

- _advance 覆写 entered_tick（创建不变量）→ 窗口年份漂移、tier 替代
  断言失败 → 移除覆写；
- submit_owner_decision 事件 uid seq 用 len(COUNT scalar) → TypeError →
  改为 int(scalar)；
- TA24/TA48 单区间 catch-up 跨窗口错过（引擎仅年末判定）→ 改逐年
  catch-up 推进并校准崩溃年份映射（11/12/13/18/20/21）；
- MR4 对照活常量 6 vs M2 冻结 5 → 改为对照 WORLD_STATE_HASH_SCHEMA_
  VERSION_V5；
- TA12/15 决策测试缺前置 episode → 补 10y 运行；TA10 窗口不足 → 30y；
- TA60 子串扫描误伤注释/展示名 → 改为引擎引用白名单扫描。

## 45. Files Delivered

- services/simulation/tribulation.py（引擎/决策/边界/常量）
- services/simulation/tribulation_adapters.py（五域 Adapter）
- services/simulation/m3a_runner.py（Adaptive Runner + M3aReport）
- services/simulation/coordinator.py（方案 B 编排 + v6 路由 + 因果链接）
- services/simulation/contracts.py（EngineResult.tribulation_plan +
  ENGINE_OWNERSHIP）
- services/simulation/snapshot.py / state_hash.py（v6；v2-v5 冻结）
- services/simulation/mini_world.py（with_tribulation 夹具）
- database/models_world.py（9 模型）+ alembic f1b3c5d7e9a2
- M3A_SIMULATION_SEMANTICS_MANIFEST.json
- runtime_design/M3A_TRIBULATION_ENGINE.md（44 节）
- tests/test_m3a_tribulation.py（TA1–TA60 + 基线产物）
- tests/baselines/m3a_tribulation_synthetic_300y_v1/（六文件）
- head 常量：conftest / runtime_host / migrate_db_to_plugin_data /
  test_database（31→40）

## 46. Test Totals

FAST：506/506 PASS（M2 442 + M3a 64）；LONG：13/13 PASS；
TOTAL：519/519。BLR_FORMAL_DB_PATH 全称设置（formal_db_guard 校验
正式库 hash 在套件期间不变）。

## 47. Git / Tag

独立 M3a 提交（不并入 M3 Preflight）：源码 + migration + manifest +
文档 + 报告 + 测试 + 基线；M2 冻结基线文件经 checkout 还原（工作树
零漂移）。旧 tag（m1-golden-baseline … m2-engine-set-frozen）全部保留。

## 48. STOP Conditions（After Delivery）

立即停止：不进入 M3b/M3c/M4/M5/M6；不激活世界（runtime_status 保持
NOT_ACTIVATED）；不注册 TRIBULATION 槽位；不推进正式时钟；不写正式
profile/schedule。等待主人明确批准后再行激活。

## 49. Known Risks / Follow-ups

- 正式激活前必须通过 PG 实测双门禁（PRE_ACTIVATION_PG_GATE /
  PRE_ACTIVATION_PG_COMMIT_AMBIGUITY_GATE）；
- 资源继承候选的物化决策属 Resource Engine 后续阶段（M3c+）；
- M3b 历史查询/叙事/展示服务按后续指令实施；
- 正式灾劫 profile/schedule 参数需主人配置（当前恒 0）。

## 50. Final Verdict

M3A_TRIBULATION_ENGINE_READY
