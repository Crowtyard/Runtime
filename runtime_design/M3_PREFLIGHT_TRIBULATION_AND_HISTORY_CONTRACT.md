# M3_PREFLIGHT_TRIBULATION_AND_HISTORY_CONTRACT

> M3 Preflight 契约文档。分类：CONFIRMED_EXISTING_SCOPE（Bible/旧设计
> 已明确）、APPROVED_LOCAL_DESIGN、SOURCE_LORE_GENERAL_RULE（母世界机制
> 参照，非本地事实）、LOCAL_OVERRIDE、IMPLIED、NEW_PROPOSAL、
> CONFLICT_FOUND、UNKNOWN。禁止把 Source Lore 一般机制升格为本地事实。
> 本阶段只做契约与测试夹具：不实现正式引擎/公式/内容/排期。

## 1. Source Recovery
只读核对 World Bible 09/11/13 + Source Lore Rules（tribulation.jsonl
STR-001~008 等）+ compatibility + runtime_design 10/11 + M2 manifest。
关键条目：WS-0901~0910（TRIBULATION_AND_METABOLISM）、WS-1101~1106
（HISTORY_AND_WORLD_EVOLUTION）、13 号 KNOWN_UNKNOWNS、
SOURCE_LORE_NON_AUTOINHERIT（§六/§七/§八）。

## 2. Local/Source Boundary
- SOURCE_LORE_GENERAL_RULE（仅机制参照，LOCAL_OVERRIDE 覆盖）：
  STR-001 天意/天道平衡（本地无天意叙事）；STR-002 灾劫频率按窍内时间
  计（本地 T-3M 为 LOCAL_SIMULATION_TIERS，非转数节律）；STR-003
  道痕收益「威力越大收益越高」的一般关系（数值 250/750/… 禁止套用，
  NON_AUTOINHERIT §七）；STR-004 威力与底蕴相关（本地无量化）。
- LOCAL_OVERRIDE：TRIBULATION_RANK_INFERENCE=0；不映射六转地灾/七转
  天劫/浩劫/万劫；灾劫=代谢而非 Boss/Loot（WS-0901）。
- 禁止：原作人物渡劫经历/战力改写为本地经历（NON_AUTOINHERIT §八）；
  排劫设局/硬抗等人物手段自动成为小光能力（SOURCE_CASE_AS_GENERAL_
  RULE=0，WS-0910）。

## 3. Tribulation Scope
CONFIRMED_EXISTING_SCOPE：WORLD_METABOLISM_MODEL（WS-0901）；
影响多样性、不保证正收益（WS-0903）；纯损失允许。M3a 只实现
Tribulation；普通 disturbance（虫害/水位/生产事故/道路损坏/一般洪涝/
局部资源问题）不入灾劫窗口（WS-0906），是否另设 Disturbance Engine
仅调研（NEW_PROPOSAL 记录）。

## 4. Lifecycle
CONFIRMED_EXISTING_SCOPE（WS-0902）：PRECURSOR → PREPARATION →
IMPACT → RESPONSE → STABILIZATION → RESIDUAL_CHANGE → RECOVERY →
RESOURCE_SUCCESSION → NEW_NORMAL。灾后世界不 Reset。契约：
- PRECURSOR→PREPARATION 之间为 Owner Decision Window（§12）；
- IMPACT/STABILIZATION 的域影响经 Domain Impact Adapters 同 Step
  原子应用（§9）；
- RESIDUAL_CHANGE/RECOVERY/SUCCESSION 跨 committed Step 推进。

## 5. Schedule
WS-0905 = APPROVED_WORLD_SEED_DESIGN · LOCAL_SIMULATION_TIERS：
REGULAR≈10 福地年 / MAJOR≈50 / CENTENNIAL≈100。**非已启动倒计时**
（13 号：灾劫日历/具体周期数值 未裁决；首个前兆时间 PENDING）。
正式世界：schedule=NOT_ACTIVATED，next_tribulation=UNKNOWN，
tribulation_history=EMPTY。测试仅 TEST_TRIBULATION_SCHEDULE_001
（config 驱动，非硬编码；10 号 §1）。

## 6. Profile
TribulationProfile（m3-preflight-contract-v1 契约）：
profile_id/tier/theme/intensity_range/targeting_rules/precursor_rules/
impact_weights/duration_rules/mitigation_rules/residual_change_rules/
recovery_rules/succession_rules/source_refs/status/semantic_version。
正式 profile 未创建（UNKNOWN）；测试 TEST_TRIBULATION_PROFILE_001/
002/003（TEST_FIXTURE_ONLY）。全部结构化有界数值，LLM 不篡改
（10 号 §3）。

## 7. Target Selection
CONFIRMED：因果驱动（不无因落点）。NEW_PROPOSAL 冻结：stable
ordering（语义键排序）+ TRIBULATION RNG substream 确定性抽样（无放回）
+ versioned target-selection semantics；可读取资源密度/人口密度/生态
状态/福地压力/区域脆弱性/既有灾劫历史/profile targeting rule；禁止
因 SQL 行顺序不同而选中不同目标（TP7 实测）。

## 8. Impact Plan
TribulationImpactPlan（impact-plan-v1）：plan_id/episode_id/
profile_id/tier/theme/affected_regions/affected_settlements/intensity/
duration/recovery/population_risk/resource_damage/inventory_damage/
production_disruption/ecology_pressure/social_displacement/
institution_disruption/recovery_requirements/residual_changes/
source_profile/domain_effects/schema。全部结构化/有界/确定性/可验证；
禁止 LLM 自由描述后反向解析数值（TP4 实测校验器拒绝越界/非法 plan）。

## 9. Cross-Domain Ownership（唯一模型冻结）
方案评估：
- 方案 A（Year N committed PendingImpact → Year N+1 各引擎应用）：
  域应用跨 Step 散布，IMPACT 步失去原子性，崩溃恢复需处理半应用状态，
  反馈延迟 ≥2 Step，重放复杂 —— 否决。
- 方案 B（TribulationImpactPlan + Coordinator 经 Domain-owned Impact
  Adapter 在同一 WorldMutationContext 应用）：IMPACT 与全部域影响同一
  原子世界语义 Step（TIME+WORLD 双 checkpoint 全覆盖）；所有权不破坏
  （每域 adapter 只写该域所有权表，contracts.DOMAIN_ADAPTER_OWNERSHIP
  强制）；事件经 coordinator 进同一事件流与哈希；重放/崩溃/幂等/fencing
  全继承 M2 hardened 机制；Owner Decision 在 PREPARATION 边界以
  committed decision event 进入 —— **冻结方案 B**。
- 方案 C（其他）不采用。
TRIBULATION Engine 只写 tribulation-owned 状态（tribulations 表 +
episode/恢复状态）；跨域影响一律经 adapters。Preflight 以 Contract
Driver 复现该形状（同 session 内 adapter 应用，TP3 实测越权拒绝）。

## 10. Pipeline Integration
CONFIRMED（Preflight 契约）：TRIBULATION 在 SOCIAL 之后（
ENGINE_ORDER 既有槽位语义）；M2 中 TRIBULATION=NOT_REGISTERED
（M2 frozen 不变）。M3a 注册后：Impact 步 = 五引擎 + Tribulation
计划与 adapter 应用同事务；RESIDUAL/RECOVERY/SUCCESSION 在后续
committed Step 推进（跨 Step 契约，TP16 实测）。ADAPTIVE_TIME_
RESOLUTION（WS-1105）：灾劫活跃期允许季度/月度 Step —— M3a 必须经
SimulationInterval 细分实现（引擎已 interval-safe），Preflight 不实现。

## 11. Xiaoguang Response
WS-0907：管理侧 —— 感知异常/预警/调度资源/疏散居民/保护重要区域/
协调恢复/选择重点保护区域。XiaoguangResponsePolicy 白名单
（XIAOGUANG_RESPONSE_ACTIONS，仅管理协调型）；超凡对抗/排劫/移劫 =
UNKNOWN 不启用（TP8 实测策略可用且限于白名单）。

## 12. Owner Decision Input
WS-0908：主人战略判断/资源优先级/保护区域/撤离重建决策。
OwnerDecisionInput（owner-decision-v1）：decision_id/episode_id/
action（STRATEGY/PRIORITIZE/EVACUATE/REBUILD 白名单）/parameters/
deadline_tick。External Approved Input：提交即 immutable decision
event 进事件流与 simulation semantics；聊天随口一句 ≠ 灾劫决策
（TP9/TP10/TP11 实测：不可变/可重放/过期拒绝）。

## 13. Offline Autonomous Response
10 号 §6 IMPLIED（「前兆检测独立于叙事，即使主人不在线 catch-up 中
正常调度」）+ 本契约冻结：DEFAULT_AUTONOMOUS_RESPONSE_POLICY ——
小光在已确认管理权限内自主处置（疏散/储备/保护优先级按 profile 默认
规则）；主人在 PREPARATION 窗口在线可经 OwnerDecisionInput 改变策略；
未响应则 deadline 后 autonomous fallback。离线绝不暂停福地、绝不阻塞
catch-up（TP12 实测 fallback 确定性）。

## 14. Mitigation Cost
IMPILED→NEW_PROPOSAL 冻结：Preparation/Response 消耗资源库存/生产
能力/社会组织能力/迁移能力/生态缓冲/机构能力；形成结构化成本
（库存扣减/能力占用/机会成本）。禁止「说一句保护起来→全区域无损」
（TP13/TP14 实测：扣减真实发生；最大自主防护下 impact 仍 >0）。

## 15. Residual Change
WS-0903/0904/0909：地貌/环境/道痕环境/资源损毁或增强/新危险区/新
生态位/人口迁移/道路产业改变/纯损失。RESIDUAL_CHANGE 写入
state_changes（可追溯）；不保证正收益；允许纯损失。

## 16. Recovery
NEW_PROPOSAL 冻结：RecoveryState（episode/recovery_need/progress/
resource_requirement/population_requirement/ecology_requirement/
social_requirement/state）跨 committed Step 推进；恢复需求来自 plan.
recovery_requirements；下一个 tick 不清零损失（TP16 实测恢复≥2 Step
且进度单调可审计）。

## 17. Resource Succession
WS-0904（WORLD_RULE）：RESIDUAL_CHANGE → RESOURCE_SUCCESSION_
CANDIDATE → 若干 committed Step 的「观察/稳定/发现/试验/开发」链 →
Resource Engine 创建正式可用资源状态（NEWLY_FORMED 节点）。最终
Owner = Resource Engine；Tribulation 只创建条件/候选/环境变化，不直接
写库存/节点（TP15 实测：灾劫完成不即时生成资源点）。

## 18. New Normal
WS-0902（不 Reset）：NEW_NORMAL 可含永久生态变化/资源状态变化/聚落
人口变化/社会迁移/机构改变/危险区域/新资源条件/道路生产约束。契约：
非零 impact 后终态 ≠ 灾前快照（TP17 实测）。

## 19. World Disturbance Boundary
WS-0906（WORLD_RULE）：普通扰动 ≠ Tribulation，不入窗口统计。
M3a 只实现 Tribulation；Disturbance Engine 仅调研（不实现）。

## 20. History Contract
WS-1101（WORLD_RULE）：历史 = WORLD_EVENT → WORLD_STATE_TRANSITION
→ WORLD_HISTORY；历史不是预写千年。11 号：world_state_changes 账本 +
CURRENT_STATE+IMMUTABLE_EVENT_HISTORY 混合模型；「why now」查询 =
current state + state_changes 逆序 + events 上下文；无记录返回 UNKNOWN
（禁止编造）。

## 21. Causal Links
NEW_PROPOSAL 冻结（11 号 CAUSAL_HISTORY_CHAIN 的结构化落地）：
cause_event_ids / trigger_event_id / result_event_ids /
affected_entity_ids / state_change_ids / decision_event_ids /
episode_id / supersedes / correction / correlation_id。链长度上限配置；
SQL 递归 CTE（SQLite 支持）或应用层图遍历。禁止只存一段自然语言
summary 作为唯一历史依据。

## 22. Tribulation Episode
TribulationEpisode（episode-v1）：每场灾劫一个 episode_id，把九阶段
事件关联（PRECURSOR→…→NEW_NORMAL）；Episode 是聚合索引，原始
Domain Events 仍不可变（TP18 实测：阶段事件携带 episode_id 可聚合）。

## 23. State Change Trace
每次灾劫 State Mutation 可追溯至：impact plan / mitigation decision /
tribulation episode / domain engine adapter / committed simulation run
（TP19 实测：状态变化 → trigger 事件 → plan 的因果链可走通）。

## 24. Event/State Hash
契约（M3a 执行）：event_stream_hash 覆盖完整 impact payload / response
decisions / domain effects / recovery transitions；world_state_hash 覆盖
active tribulation state / recovery state / residual changes / history
cursors —— 需升级 hash schema 时**必须版本化**（不静默改变 v5）。
Preflight 不升级（TP1 实测 manifest 不变；TP29 以「episode 行 updated_
tick == 同事务 checkpoint tick」验证原子语义）。

## 25. RNG
TRIBULATION 独立 substream（TRIBULATION 已在 RngService SUBSYSTEMS）；
至少分离 schedule/profile selection/target selection/impact
realization/recovery uncertainty；任一抽样增加不改其他 substream 历史
（M2 机制已有）；禁止全局 random。

## 26. Fencing
ImpactPlan 已计算但 lease 丢失 → commit 被 FENCING_VIOLATION 拒绝，
零 authoritative impact（TP27 实测；M2 hardened 机制继承）。

## 27. Idempotency
同一灾劫/同一 Step retry：零重复死亡/资源损毁/库存扣除/生态退化/
迁移/历史事件/Episode/checkpoint/时间推进（TP25/TP26 实测）。

## 28. Crash Matrix
T1 precursor creation / T2 preparation state / T3 owner decision
commit / T4 impact plan generated / T5 population adapter staged /
T6 resource-economy staged / T7 ecology staged / T8 social staged /
T9 history links staged / T10 before fence recheck / T11 durable commit
ack lost / T12 recovery transition。恢复后：一个世界、一条事件流、
一个 Episode（TP28 + T1-T12 契约 harness 实测）。

## 29. Test Harness
synthetic mini-world（with_ecology+with_social）+ Contract Tribulation
Driver（Fake/Contract，非正式算法）：300 福地年，覆盖多个 regular/
major/centennial 窗口（TEST_TRIBULATION_SCHEDULE_001）；验证
schedule/episode lifecycle/impact plan contract/domain adapters/
history causality/checkpoint/hash/crash recovery。测试文件
tests/test_m3_preflight.py（TP1–TP32）。

## 30. M3a/M3b Split
建议（只建议，不执行）：
- M3a Tribulation Engine：注册 TRIBULATION 槽位、schedule/profile/
targeting/impact adapters、RecoveryState、ADAPTIVE_TIME_RESOLUTION。
- M3b Causal World History Service：episode 索引、causal links、
CAUSAL_HISTORY_CHAIN 查询、state change 追踪（无 LLM）。
- M3c（可选）：Tribulation + M2 Long-Horizon Integration Review
（如 M2 Review 模式的 1000y 级联压）。

## 31. Known Unknowns
灾劫是否正式启用及首个前兆时间 PENDING；正式周期数值未裁决；
CROW_CULTIVATION_REQUIRED（无超凡响应）；道痕环境数值 UNKNOWN；
灾劫对地灵福地的母世界规则 UNDECIDED（SLS-011 型缺口）；正式
profile/内容库未创建。

## 32. New Proposals
ImpactPlan/Episode/RecoveryState/OwnerDecisionInput 结构；方案 B
跨域应用模型；Domain Impact Adapter 所有权表；target-selection
语义；DEFAULT_AUTONOMOUS_RESPONSE_POLICY；mitigation 成本契约；
causal links 字段集；T1–T12 崩溃边界；300y Contract Harness。

## 33. Conflicts Found
无硬冲突。两点裁决记录：
- 任务 §14 离线不阻塞 vs 10 号（前兆检测在 catch-up 中正常调度）——
  一致，据此冻结 autonomous fallback。
- 任务 §7 方案评估 vs 现有 Engine Ownership —— 方案 B 不破坏所有权
  （adapter 按域声明），裁决冻结。
