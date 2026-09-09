# M3A_TRIBULATION_ENGINE

> M3a 灾劫引擎实现文档。CONFIRMED_EXISTING_SCOPE = 恢复自旧设计（以 05/06/08/09 号为主）；
> IMPLIED = 旧设计隐含但未定量；NEW_PROPOSAL = DSH 冻结决定；
> CONFLICT_FOUND = 与 M3a 任务的显式边界冲突及裁决。
> 正式种族/机构/灾劫参数保持未配置；一切数值 TEST_FIXTURE_ONLY。
> TRIBULATION_RANK_INFERENCE 恒 0；禁止将 REGULAR/MAJOR/CENTENNIAL 映射为
> 地灾/天劫/浩劫/万劫或推断任何修炼体系（WS-0905）。

## 1. Scope

世界代谢的灾劫层：排期窗口 → 确定性 Episode → 九阶段生命周期 →
跨域 Impact（五域 Adapter）→ 恢复 → 资源继承候选 → NEW_NORMAL。
目标是真实引擎（非占位符）：确定性、可复现、可崩溃恢复、离线自治。
禁止：LLM/网络/wall-clock 依赖；叙事生成；历史查询服务（M3b）；
正式库自动排期（正式 profile/schedule 恒 0）；Seed 激活；修炼推断。

## 2. Source Recovery

- CONFIRMED_EXISTING_SCOPE（05/08/09 号）：灾劫是「世界代谢」的一部分，
  非纯粹惩罚；事件后残留改变环境；资源继承候选须经观察/稳定/开发
  阶段，由 Resource Engine 最终决定是否物化。
- IMPLIED：排期窗口（10/50/100 年）、高层级替代低层级、离线自治响应、
  恢复跨 Step 推进。
- CONFLICT_FOUND：05 号提及「历史叙事/排行榜」→ 属 M3b（历史查询），
  本阶段只保留最小因果字段（tribulation_causal_links），不做查询服务。

## 3. TRIBULATION = WORLD_METABOLISM

engine_id=TRIBULATION，engine_version=m3a-tribulation-1。
实现 Engine Protocol（simulate(ctx) -> EngineResult），零 commit/LLM/网络/
wall-clock。灾劫作为世界的代谢事件参与管线：破坏 → 域响应 → 残留改变 →
恢复 → 资源继承候选 → 新常态。世界从不重置。

## 4. Canon/Lore Boundary

TRIBULATION_RANK_INFERENCE=0：不推断修炼等级、不生成宗门/修士叙事。
TIER 只是调度强度档位（REGULAR/MAJOR/CENTENNIAL），与世界观文献中的
任何特定灾劫名称解耦。事件 effect 只含结构化字段（tier/intensity/
theme 标记），无叙事文本。

## 5. Ownership

TRIBULATION 只 propose：tribulation_episodes / tribulation_decisions /
tribulation_impact_plans / tribulation_recovery_states /
tribulation_residual_changes / resource_succession_candidates /
tribulation_causal_links（ENGINE_OWNERSHIP["TRIBULATION"]）。
跨域影响不自写他域表：由 Coordinator 依方案 B 调用 Domain-owned
Impact Adapters（见 §16），所有权经 StagedWorld.propose 强制。

## 6. Nine-stage Lifecycle

LIFECYCLE = (PRECURSOR, PREPARATION, IMPACT, RESPONSE, STABILIZATION,
RESIDUAL_CHANGE, RECOVERY, RESOURCE_SUCCESSION, NEW_NORMAL)。
每 Step 至多一次转移；转移 tick 为整数 blessed tick
（transition_tick = 当前年末 + 阶段步数 × 1e6）。episode 创建时处于
PRECURSOR，其 entered_tick 是创建时刻不变量，绝不覆写。

## 7. Schedule & Tier Replacement

TEST_SCHEDULE = [(REGULAR,10),(MAJOR,50),(CENTENNIAL,100)]，
schedule_id=TEST_TRIBULATION_SCHEDULE_001（TEST_FIXTURE_ONLY）。
窗口判定 _tier_at_tick：同年多档命中时取最高层级（max by TIER_ORDER），
不叠加成多场；REGULAR 每 10 年、MAJOR 每 50 年、CENTENNIAL 每 100 年，
50 年处 MAJOR 替代 REGULAR，100 年处 CENTENNIAL 替代 MAJOR/REGULAR。

## 8. Deterministic Episode Identity

episode_id = deterministic_hex_id([world_id, simulation_version,
schedule_id, tier, scheduled_tick], bits=128,
schema=TRIBULATION_EPISODE_ID_SCHEMA_VERSION="tribulation-episode-id-v1")。
无 UUID4；同一窗口重放（catch-up 重试/ack-lost）得到同一 id →
exactly-once 创建。

## 9. Deterministic Target Selection

目标聚落选择：settlements 按 working_name stable 排序 →
TARGET RNG 子流抽下标。行序无关（逆序重插不变）；同 seed 同结果。

## 10. RNG Six Substreams

SCHEDULE / PROFILE / TARGET / IMPACT / RECOVERY / SUCCESSION 六子流，
各自独立 seed（entity_scope）。增加任一子流抽样（如 IMPACT 多抽）不
改变其他子流历史：TA8（schedule/target 不受 extra_draws 影响）、
TA36（intensity 变 → 事件流哈希变）实测。

## 11. OwnerDecisionInput

显式机器级 API submit_owner_decision（不接聊天/UI/Companion）：
- action 白名单 STRATEGY/PRIORITIZE/EVACUATE/REBUILD；
- episode 必须存在；过期（effective_before_tick <= 当前 tick）拒绝；
- 错误 episode 拒绝；
- 修改必须 supersede：旧决策 status → SUPERSEDED，内容不可变，新增 ACTIVE；
- 重试（同 decision_id）幂等返回 idempotent=True；
- 提交即写 immutable 行 + OWNER_DECISION_COMMITTED 事件（确定性 uid）。

## 12. DEFAULT_AUTONOMOUS_RESPONSE_POLICY

离线无决策 → DEFAULT_AUTONOMOUS_RESPONSE_POLICY（常量），
发出 AUTONOMOUS_RESPONSE_SELECTED 事件。离线永不阻塞 catch-up：
引擎不等待任何外部输入，PREPARATION 阶段检查 staged decisions 后
直接选定策略（OWNER_PLAN 或 AUTONOMOUS）。

## 13. Mitigation Cost

PREPARATION 阶段声明 MITIGATION_COMMITTED（cost_basis=intensity_min）；
实际成本在 IMPACT 应用时由 Economy Adapter 按 inventory_damage 扣减
resource_stocks。不存在免费完美减灾：自主响应下仍有真实损失（TA17）。

## 14. TribulationImpactPlan

plan_id = deterministic_hex_id([world_id, episode_id, "PLAN"], bits=128,
schema=IMPACT_PLAN_SCHEMA_VERSION="impact-plan-v2")。
六类 risk 以整数 fixed-point 分子/分母存储（population/resource/
inventory/production/social/institution）；intensity 0..100；
ecology_pressure 0..1_000_000；mitigation_applied / residual_changes /
recovery_requirements / succession_candidates 结构化 JSON。

## 15. Domain Impact Adapters（方案 B）

Coordinator 在 TribulationEngine 返回 tribulation_plan 后，依
sorted(DOMAIN_ADAPTERS) 依次调用各 Domain-owned Adapter.apply(session,
plan)；每个 Adapter 返回 (domain_events, state_changes,
affected_entity_ids)。所有权归属：Demography 写 population_groups、
Resource 写 resource_nodes、Economy 写 resource_stocks、Ecology 写
ecology_state、Social 写 households + settlement_social_state。
Adapter 只写本域表（TA19-23 源码断言）。

## 16. Demography Adapter

population_risk × intensity 比例损失，作用于目标聚落 population_groups
的 count（clamp >= 0）。返回 state_changes 供 Coordinator 记入
world_state_changes 账本。

## 17. Resource Adapter

resource_damage × intensity 比例削减目标区域 resource_nodes 的
remaining_reserve（clamp >= 0）。节点不销毁（留待恢复/继承叙事）。

## 18. Economy Adapter

inventory_damage × intensity 扣减 resource_stocks.quantity
（clamp >= 0）；同时按 production_disruption 记录扰动。成本即
§13 的 mitigation 实际扣减路径。

## 19. Ecology Adapter

habitat_quality -= ecology_pressure（clamp 0..1_000_000），
写入 ecology_state。灾劫是生态压力源而非生态重置。

## 20. Social Adapter

social_displacement × intensity 使目标聚落 households 位移
（state → DISPLACED 或解散）并抬升 settlement_social_state.social_stress
（clamp 0..1_000_000）。institution_disruption 影响 institutions 状态。

## 21. Atomic Cross-domain Application

全部 Adapter 在同一个 WorldMutationContext 内、同一 run_step 中应用；
任一 Adapter 崩溃（crash_after=adapter:DOMAIN）→ 整个事务回滚，
时钟/事件/计划零写入（TA24 实测 rollback 到 12M、plan 0 行）。

## 22. Causal Links（最小字段）

TRIBULATION_IMPACT_APPLIED 事件后，Coordinator 写
TribulationCausalLink：episode_id / correlation_id=plan_id /
cause_event_ids / trigger_event_id / decision_event_ids /
impact_plan_id / result_event_ids / affected_entity_ids /
state_change_ids。仅因果指针，无叙事（M3b 才做查询/展示）。

## 23. Recovery State across Steps

tribulation_recovery_states：recovery_need_num/den、
progress_num/den（整数 fixed-point）、resource/population/ecology/
social requirement、status。恢复非单步完成：每 Step progress 递增
（step = 100 // recovery_steps，cap 100），跨 catch-up 持久化推进。

## 24. Residual Change

RESIDUAL_CHANGE 阶段写 tribulation_residual_changes
（change_kind=environment_condition，persistent=True，payload.theme）。
灾劫残留永久改变环境条件，为后续生态/资源演化提供依据。

## 25. Resource Succession Candidate

RESOURCE_SUCCESSION 阶段按 succession_rules.allow_candidate 生成
resource_succession_candidates（discovery_status=UNOBSERVED、
development_status=NONE）。候选 ≠ 资源节点：绝不自动物化新节点
（TA32/TR_INV_15：node 数不变），最终由 Resource Engine 决定。

## 26. NEW_NORMAL

SUCCESSION 后进入 NEW_NORMAL：episode status → COMPLETED，
发 TRIBULATION_NEW_NORMAL_REACHED（world_not_reset=True）与
TRIBULATION_EPISODE_COMPLETED。世界不重置；受影响域在新常态继续演化。

## 27. Adaptive Time Resolution

next_tribulation_boundary(session, world_id, from_tick, to_tick) 返回
(from, to] 内最早的边界：排期窗口命中 tick 或活跃 episode 的
transition_tick。Runner 逐 Sub-interval catch_up，绝不静默跳过
PRECURSOR/PREPARATION/RESPONSE（TA42/43/44/45）。边界恒为整数
blessed tick（禁止浮点年份）。

## 28. Events & Deterministic UIDs

事件类型：TRIBULATION_SCHEDULED / _PRECURSOR_STARTED /
_PREPARATION_STARTED / OWNER_DECISION_COMMITTED /
AUTONOMOUS_RESPONSE_SELECTED / MITIGATION_COMMITTED /
TRIBULATION_IMPACT_STARTED / TRIBULATION_IMPACT_APPLIED /
TRIBULATION_STABILIZED / TRIBULATION_RESIDUAL_CHANGE_CREATED /
TRIBULATION_RECOVERY_PROGRESS / RESOURCE_SUCCESSION_CANDIDATE_CREATED /
TRIBULATION_NEW_NORMAL_REACHED / TRIBULATION_EPISODE_COMPLETED。
event_uid = deterministic_event_uid（128-bit，seq 按步骤序）。
TA35：跨库重放 uid 全同且无碰撞。

## 29. World State Hash v6

WORLD_STATE_HASH_SCHEMA_VERSION=6。v6 = v5 全部字段 + 9 张灾劫表。
v5（M2d）冻结为独立函数；Coordinator 仅当注册 TRIBULATION 引擎时
选 v6，M2 路径（0.2.0-preflight）逐字节不变（TA37 实测 episode
字段变化 → hash 变化；M2a/b/c/d/1000y 基线全复现）。

## 30. Exactly-once / Fencing / Ack-lost / Crash（T1–T14）

- T1/T2：engine:TRIBULATION 前/内崩溃 → 回滚；
- T5：impact_plan 崩溃 → 计划零写入；
- T6/T8/T9：adapter:DEMOGRAPHY/ECOLOGY/SOCIAL 崩溃 → 跨域原子回滚；
- T10/T13/T14：recovery/succession/new_normal 阶段崩溃 → 重放续推进；
- T11/T12：before_checkpoint / after_engines 崩溃 → 回滚后重试；
- TA41 ack-lost：COMMIT 已持久化但 ACK 丢失 → 重试 skipped（幂等）；
- TA40 stale writer：fencing token 篡改 → FencingViolation，零写入。
全部经 M1 catch_up（fencing/幂等/ack-lost 继承），TA48 矩阵实测。

## 31. M2 Frozen Compatibility

TRIBULATION 未注册时：ENGINE_ORDER 不变、hash 走 v2-v5、M2 语义清单
（M2_SIMULATION_SEMANTICS_MANIFEST.json）零修改、M2 基线逐字节复现。
TRIBULATION_SLOT_STATE="NOT_REGISTERED" 模块常量保持并被
run_step 守卫强制（未激活前不得注册）。

## 32. Database Schema（9 表 + Migration）

Alembic f1b3c5d7e9a2_m3a_tribulation（down_revision=e8a1c5d7f2b4）：
tribulation_profiles / tribulation_schedules / tribulation_episodes /
tribulation_decisions / tribulation_impact_plans /
tribulation_recovery_states / tribulation_residual_changes /
resource_succession_candidates / tribulation_causal_links。
全部规范化结构 + 整数 fixed-point（_risk_cols 六对 num/den），
SQLite/PG 兼容，uq_* 显式唯一约束，JSON 列赋值必用新 dict。

## 33. Formal World Contract

正式权威库：NOT_ACTIVATED、9 张灾劫表全部 0 行、无 TEST profile/
schedule。TEST_PROFILES/TEST_SCHEDULE 只存在于 mini_world 夹具；
插件启动路径绝不导入/调度灾劫引擎（TA60）。

## 34. Test-Only Fixtures

seed_mini_world(with_tribulation=True) 注入 TEST profiles 001/002/003
（REGULAR/MAJOR/CENTENNIAL）+ TEST_TRIBULATION_SCHEDULE_001。
正式库永不写入这些行。

## 35. 300y Synthetic Baseline

tests/baselines/m3a_tribulation_synthetic_300y_v1/：
summary.json / episode_index.json / schedule.json / profiles.json /
decisions.json / final_state.json。300 年 → 30 窗口（24 REGULAR /
3 MAJOR / 3 CENTENNIAL）、29 完成、29 自治响应、29 继承候选、
68 恢复步、0 Owner 决策、0 LLM/网络/wall-clock 依赖。

## 36. Continuous == Chunked == Restart

TA46（120y 连续 vs 每 40y 重启）、TA47（60y + 60y start_year=60 vs
连续 120y）：final_world_state_hash 与 final_event_stream_hash 全同。
RNG 按 (subsystem, blessed_period_tick, entity_scope) 子流 → 与
分段无关。

## 37. Owner Decision Scenarios

六种场景覆盖：有效提交（TA12）、过期拒绝（TA13）、错误 episode 拒绝
（TA14）、supersede 不可变（TA15）、幂等重试（TA12）、自主回退（TA11）。
决策在 runner 指定年份推进前显式提交（外部输入路径）。

## 38. Invariants（TR_INV_*）

- TR_INV_01 episode_id 唯一；TR_INV_02/03 stage ∈ LIFECYCLE；
- TR_INV_07 intensity ∈ [0,100]；TR_INV_09..11 人口/库存/储量 >= 0；
- TR_INV_14 progress_num <= progress_den×100；TR_INV_15 候选不物化。
TA51 在 300y 全量断言。

## 39. Zero LLM / Network / Wall-clock

tribulation.py / tribulation_adapters.py / m3a_runner.py 源码扫描：
无 openai/anthropic/requests/httpx、无 datetime.now/time.*/
perf_counter（TA52-55）。引擎零 commit/零网络/零 I/O 随机性。

## 40. PostgreSQL Compatibility

无 json_extract / rowid / INSERT OR REPLACE（TA59）；
JSON 一律 ORM 赋值新 dict；固定点整数列跨库一致。

## 41. Out of Scope（M3b 及以后）

历史查询服务、灾劫叙事生成、排行榜、Owner 决策 UI/聊天接入、
资源继承的物化决策（Resource Engine 后续）、正式排期激活
（等主人批准并配置 profile/schedule）。

## 42. Rollout & Activation Gate

M3a 交付后 STOP：不激活世界、不推进正式时钟、不注册 TRIBULATION 槽位。
激活需主人明确批准（配置正式 profile/schedule + 槽位注册）。

## 43. Verification

TA1–TA60 + 300y 基线产物 + 崩溃矩阵 + 全量 455/455 回归 +
正式库 pre-m3a 备份/迁移/终检（FORMAL_AUDIT_M3A PASS）。

## 44. Files

- services/simulation/tribulation.py（引擎 + 决策 API + 边界）
- services/simulation/tribulation_adapters.py（五域 Adapter）
- services/simulation/m3a_runner.py（Adaptive Runner）
- services/simulation/coordinator.py（方案 B 编排 + v6 路由）
- services/simulation/snapshot.py / state_hash.py（v6）
- database/models_world.py + alembic f1b3c5d7e9a2
- M3A_SIMULATION_SEMANTICS_MANIFEST.json（simulation_version=0.3.0-m3a）
- tests/test_m3a_tribulation.py（TA1–TA60）
