# DSH_M3_PREFLIGHT_TRIBULATION_AND_CAUSAL_HISTORY_FINAL_REPORT

> 执行方：DSH。阶段：M3_PREFLIGHT（Source Design Recovery / Cross-Domain
> Impact Contract / Tribulation Lifecycle Design / Causal History
> Foundation / Test Harness）。不是 M3 正式实现，不是 Seed Activation，
> 不推进正式福地时间。
> 基线：M2_ENGINE_SET_FROZEN = TRUE（415/415，tag
> m2-engine-set-frozen @ 973cad5）。
> 完成后 STOP：不进入 M3a/M3b/M3c/M4/M5/M6，等待主人明确批准。

## 1. M2 Frozen Baseline
tag m2-engine-set-frozen @ 973cad5（ac64d72 + 973cad5）；415/415 全
保留；M2_SIMULATION_SEMANTICS_MANIFEST.json 未修改（TP1 实测）。

## 2. Source Design Recovery
只读核对：World Bible 09/11/13、source_lore_rules/tribulation.jsonl
（STR-001~008）、SOURCE_LORE_NON_AUTOINHERIT、compatibility 三件、
runtime_design 10/11。关键结论见 §3/§4。

## 3. Local/Source Boundary
- SOURCE_LORE_GENERAL_RULE（机制参照，非本地事实）：STR-001 灾劫源于
  天意/天道平衡（本地无天意叙事）；STR-002 频率按窍内时间计；STR-003
  「威力越大收益越高」一般关系（250/750 等数值禁止套用）；
  STR-004 威力与底蕴相关。
- LOCAL_OVERRIDE：TRIBULATION_RANK_INFERENCE=0（不映射转数阶梯）；
  灾劫=代谢（WS-0901）而非 Boss/Loot；T-3M 为本地 SIMULATION_TIERS。
- 禁止自动继承：排劫设局/硬抗等人物手段（SOURCE_CASE_AS_GENERAL_
  RULE=0）；原作渡劫经历改写为本地经历（NON_AUTOINHERIT §八）；
  具名仙蛊/传承/修为数据。

## 4. Conflicts
无硬冲突。两处裁决：
- 离线不阻塞（任务要求）↔ 10 号 §6（前兆检测独立于叙事、catch-up 中
  正常调度）→ 一致，冻结 DEFAULT_AUTONOMOUS_RESPONSE_POLICY。
- 跨域影响 vs Engine Ownership → 方案 B 不破坏所有权（按域 adapter），
  裁决冻结（§11）。

## 5. New Proposals
ImpactPlan（impact-plan-v1）/Episode（episode-v1）/RecoveryState/
OwnerDecisionInput（owner-decision-v1）结构；方案 B 跨域应用模型；
DOMAIN_ADAPTER_OWNERSHIP；target-selection 语义（stable ordering +
TRIBULATION substream）；XiaoguangResponsePolicy 白名单；
DEFAULT_AUTONOMOUS_RESPONSE_POLICY；mitigation 成本契约；causal
links 字段集；T1–T12 崩溃边界；300y Contract Harness。全部标注于
M3_PREFLIGHT_TRIBULATION_AND_HISTORY_CONTRACT.md §32。

## 6. Tribulation Lifecycle
CONFIRMED（WS-0902）：PRECURSOR → PREPARATION → IMPACT → RESPONSE →
STABILIZATION → RESIDUAL_CHANGE → RECOVERY → RESOURCE_SUCCESSION →
NEW_NORMAL；不 Reset。IMPACT/STABILIZATION 域影响经方案 B 同 Step
原子应用；RESIDUAL/RECOVERY/SUCCESSION 跨 committed Step（TP16 实测
恢复 ≥2 Step）。

## 7. Schedule Contract
WS-0905 = APPROVED_WORLD_SEED_DESIGN · LOCAL_SIMULATION_TIERS
（REGULAR≈10y / MAJOR≈50y / CENTENNIAL≈100y），**非已启动倒计时**
（13 号：正式周期数值未裁决、首个前兆 PENDING）。正式世界：
schedule=NOT_ACTIVATED、next_tribulation=UNKNOWN、history=EMPTY。
测试仅 TEST_TRIBULATION_SCHEDULE_001（TP5 实测确定性；300y 覆盖
24 regular + 3 major + 3 centennial）。

## 8. Profile Contract
TribulationProfile：tier/theme/intensity_range/population_risk/
resource_damage/inventory_damage/production_disruption/
ecology_pressure/social_displacement/institution_disruption/duration/
recovery/source_refs/status/semantic_version。正式 profile 未创建
（UNKNOWN）；测试 TEST_TRIBULATION_PROFILE_001/002/003（
TEST_FIXTURE_ONLY，TP6 实测确定性选择）。

## 9. Target Selection
稳定语义键排序 + TRIBULATION RNG substream 无放回抽样；与行物理顺序
无关（TP7 实测）；可读取密度/生态/压力/脆弱性/历史/profile rule。

## 10. Impact Plan
TribulationImpactPlan 全字段结构化/有界/确定性/可验证；校验器拒绝
越界 intensity/风险比例/空目标（TP4 实测）；禁止 LLM 自由文本反向
解析数值。

## 11. Cross-Domain Ownership Decision
方案评估：A（N+1 应用）破坏 IMPACT 原子性、反馈延迟 ≥2 Step → 否决；
B（Coordinator 经 Domain-owned Impact Adapter 同 WorldMutationContext
应用）原子/所有权/重放/崩溃/幂等全继承 M2 hardened 机制 → **冻结 B**；
C 不采用。TRIBULATION 引擎只写 tribulation-owned 状态；每域 adapter
只写该域所有权表（TP3 实测越权拒绝）。

## 12. Pipeline Decision
TRIBULATION 保持 NOT_REGISTERED（M2 frozen）；M3a 注册于 SOCIAL 后；
IMPACT 与五引擎同事务；RESIDUAL/RECOVERY/SUCCESSION 跨 Step；
ADAPTIVE_TIME_RESOLUTION（WS-1105）经 SimulationInterval 细分
（M3a 实现，Preflight 不实现）。

## 13. Xiaoguang Response
WS-0907 管理侧白名单（XIAOGUANG_RESPONSE_ACTIONS：感知/预警/调度/
疏散/保护/协调/储备分配）；超凡对抗=UNKNOWN 不启用（TP8 实测策略
可用且仅白名单）。

## 14. Owner Decision
OwnerDecisionInput：STRATEGY/PRIORITIZE/EVACUATE/REBUILD 白名单 +
deadline_tick；提交即 immutable decision event（TP9 实测触发器拒绝
篡改）；同决策 replay 一致（TP10）；过期拒绝（TP11）；聊天随口一句
≠ 决策。

## 15. Offline Fallback
无有效决策 → DEFAULT_AUTONOMOUS_RESPONSE_POLICY（管理权限内自主
处置）；离线绝不阻塞 catch-up、绝不暂停福地（TP12 实测确定性）。

## 16. Mitigation Cost
RESPONSE 消耗库存（结构化成本入 params，TP13 实测扣减 + 相对对照）；
禁止「一句话全区域无损」（TP14 实测真实人口损失入 state change 账本）。

## 17. Residual Change
地貌/环境/资源损毁或增强/危险区/生态位/迁移/道路产业变化/纯损失
（WS-0903）；写入 state_changes 可追溯。

## 18. Recovery
RecoveryState 跨 committed Step：need/progress/resource/population/
ecology/social requirements；下一个 tick 不清零（TP16 实测）。

## 19. Resource Succession
WS-0904（WORLD_RULE）：候选 ≠ 掉落 —— RESIDUAL_CHANGE →
succession_candidate → 多 Step 观察/发现/开发链 → Resource Engine
创建正式资源状态；Tribulation 不直接写库存/节点（TP15 实测：300y 灾劫
完成后资源节点数不变，仅候选记录）。

## 20. New Normal
非零 impact → 终态 ≠ 无灾劫对照（TP17 实测）；永久变化构成世界历史
（WS-1106）。

## 21. History Contract
WS-1101：历史 = EVENT → STATE_TRANSITION → HISTORY；CURRENT_STATE +
IMMUTABLE_EVENT_HISTORY；「why now」= state + 逆序 changes + events，
无记录返回 UNKNOWN（不编造）。

## 22. Causal Chain
cause_event_ids/trigger_event_id/result_event_ids/affected_entity_ids/
state_change_ids/decision_event_ids/episode_id/supersedes/correction/
correlation_id；TP19 实测：state change → event_ref → IMPACT 事件 →
episode 全链可走通。

## 23. Tribulation Episode
每场灾劫一个 episode_id，聚合九阶段事件；原始 Domain Events 不可变
（TP18 实测：阶段事件按 episode_id 无重复阶段关联）。

## 24. Hash Semantics
契约（M3a 执行）：event_stream_hash 覆盖 impact payload/decisions/
domain effects/recovery transitions；world_state_hash 覆盖 active
tribulation/recovery/residual/history 语义；升级必须版本化。
Preflight 不升级（TP1 实测 manifest 不变；TP29 实测 episode tick ≤
权威 checkpoint tick 的原子语义）。

## 25. RNG
TRIBULATION 独立 substream（已在 RngService SUBSYSTEMS）；分离
schedule/profile/target/impact/recovery 维度；不改其他 substream
历史；禁全局 random。

## 26. Fencing
ImpactPlan 已算但 lease 丢失 → FENCING_VIOLATION、零 authoritative
impact（TP27 实测）。

## 27. Idempotency
同 Step/同灾劫 retry：零重复 episode/impact/事件/时间推进（TP25/TP26
实测）。

## 28. Crash Matrix
T1–T12（T3 owner decision commit / T10 fence recheck / T11 ack lost
由既有机制覆盖）：参数化实测恢复后一个世界、一条事件流、无重复
episode、uid 无碰撞；TP28 实测 ack lost → ALREADY_COMMITTED。

## 29. 300y Contract Harness
synthetic mini-world + Contract Tribulation Driver（Fake/Contract，
非正式算法）：300 福地年、30 场灾劫（24R+3M+3C）、九阶段生命周期、
impact plan、domain adapters、history causality、checkpoint/hash、
crash recovery 全链路验证（TP8–TP19 + 崩溃矩阵实测）。

## 30. Regression
TOTAL_TESTS / TOTAL_PASS 见报告末（402 既有 + 40 新 TP 项 = 442 快套
全绿；long-horizon 13 项自 M2 Review 起 M2 代码零变更，保持有效 →
总计 455）。

## 31. Formal DB Audit
正式库 sha256 不变（无 schema 迁移）；NOT_ACTIVATED；seed/tick=NULL；
全表 0；tribulations=0、无 episode、无 history（TP30 实测）。

## 32. World Seed Freeze
world_seed/ 逐字节冻结（TP31 实测 sha256 == MANIFEST.sha256.txt）；
未读取正式人口/聚落/资源/生态/种族生成任何测试灾劫。

## 33. PostgreSQL Gates
PRE_ACTIVATION_PG_GATE = REQUIRED、
PRE_ACTIVATION_PG_COMMIT_AMBIGUITY_GATE = REQUIRED 继续登记；
契约不锁死 SQLite（结构化列 + 显式约束；递归 CTE 双库兼容路径）。

## 34. M3a/M3b/M3c Recommendation
建议（只建议，不执行）：
- M3a Tribulation Engine：注册 TRIBULATION 槽位 + schedule/profile/
  targeting/ImpactPlan/adapters/RecoveryState/ADAPTIVE_TIME_RESOLUTION。
- M3b Causal World History Service：Episode 索引 + causal links +
  CAUSAL_HISTORY_CHAIN + state change 追踪（零 LLM）。
- M3c（可选）Tribulation + M2 Long-Horizon Integration Review（复刻
  M2 Review 模式）。

## 35. Git/Tag
tag m2-engine-set-frozen @ 973cad5；Preflight 独立 commit；工作区
clean。

## 36. Workspace
`git status` clean；M2a/b/c/d 基线产物未动。

## 37. Known Risks
- T-3M 周期为 LOCAL_SIMULATION_TIERS（正式数值未裁决）。
- 契约驱动器的 intensity 抽样仅契约演示（非正式算法）。
- 灾劫对地灵福地的母世界规则 UNDECIDED（SLS-011 型缺口）。
- CROW_CULTIVATION_REQUIRED：超凡响应路径全部 UNKNOWN。
- ADAPTIVE_TIME_RESOLUTION 的 Step 细分未在 Preflight 实跑。

---

```
M3_PREFLIGHT_READY
```

```
TOTAL_TESTS = 455
TOTAL_PASS = 455
（本阶段快套 442/442：402 既有 + TP1–TP32 及参数化共 40；
 long-horizon 13/13 自 M2 Review 保持有效 —— M2 代码零变更）

M2_ENGINE_SET_FROZEN = TRUE
WORLD_RUNTIME_STATUS = NOT_ACTIVATED
seed = NULL
current_blessed_tick = NULL
official_world_events = 0
formal_tribulations = 0
formal_history_episodes = 0
formal_db_sha256 = 648dc9c5736334ba19a5a7880f280ed02c4d30ff9a13e4426af5b186425213f9
```
