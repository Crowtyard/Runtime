# M2B_RESOURCE_ECONOMY_ENGINE

> M2b 交付文档。CONFIRMED = 恢复自 runtime_design/08（及 07/09 边界）；
> NEW_PROPOSAL = DSH 冻结决定（明确标注，不冒充旧 Canon）；
> CONFLICT_FOUND = 旧设计与本阶段任务的显式冲突及裁决。
> 正式种族/资源参数保持 UNKNOWN/UNCONFIGURED；一切数值 TEST_FIXTURE_ONLY。

## 1. Scope
RESOURCE FLOW + PHYSICAL STOCK-FLOW ECONOMY：资源节点 → 采集/开采 →
生产 → 库存 → 需求 → 消费 → 短缺/剩余 → 聚落间转移 → 经济压力状态。
M2b 不解决：货币/价格/市场出清/商人/企业/工资/利润/税/银行/信贷/债务/
利息/财产权/阶级/拍卖/金融市场（全部禁止，未来另立设计）。

## 2. Resource Engine（engine_id=RESOURCE, engine_version=m2b-resource-1）
`services/simulation/resource.py`。只负责 Resource Node / 可用性 /
开采容量 / 储量 / 开采量 / 资源侧约束。不写人口/生态/社会/库存；影响
其他系统只经 modifier / domain event。Pipeline 位置：DEMOGRAPHY 之后、
ECONOMY 之前（Preflight 冻结顺序不变）。

## 3. Economy Engine（engine_id=ECONOMY, engine_version=m2b-economy-1）
`services/simulation/economy.py`。只负责 Settlement Inventory / 生产
输入输出 / 消费需求与满足 / 短缺剩余 / 聚落转移 / 经济压力指标。
只写 resource_stocks / production_state / economic_pressure_state。
不写人口/资源节点/生态/社会。

## 4. Engine Ownership（冻结）
- DEMOGRAPHY → population_groups
- RESOURCE → resource_nodes
- ECONOMY → resource_stocks, production_state, economic_pressure_state
- resource_profiles / production_recipes = 只读配置表（不入任何引擎
  ownership；由 fixture/未来激活流程写入）
- RESOURCE/ECONOMY 都禁止修改人口/生态/社会；同 Step 内禁止
  RESOURCE→ECONOMY→RESOURCE 循环（单趟 feed-forward，无二次迭代）。

## 5. Resource Profile
`ResourceProfile`（resource.py）：resource_id / unit / quantity_scale /
renewability / extractability / consumption_category /
production_usability / semantic_version。注册表
`RESOURCE_PROFILES={"TEST-RESOURCE-001": …}`（TEST_FIXTURE_ONLY）。
正式资源（人/毛民/石人/鲛人/菇人的真实资源）保持 UNCONFIGURED：
查询/节点引用未知 profile → `ResourceProfileUnconfigured`
（code RESOURCE_UNCONFIGURED），绝不静默套用测试参数。

## 6. Quantity Model（NEW_PROPOSAL 冻结）
权威数量 = **整数 minor units**：1 canonical unit = profile.quantity_scale
minor units（TEST scale=1_000_000）。所有生产/消费/开采/转移的 DB 真值
均为整数（SQLite INTEGER 64-bit / PostgreSQL BIGINT）；禁止 float 权威
量（RE_INV_08/09）。流率允许 Fraction/整数有理数；不整除部分经持久化
carry（整数余数）跨 step 存续 —— chunk/restart 不丢、不漂移。

## 7. Resource Node（CONFIRMED 08 号 WS-0703 + M2b 字段）
resource_nodes 扩展：resource_profile_ref / settlement_relation /
remaining_reserve / extraction_capacity / extraction_carry /
last_extracted_minor / engine_version / state_version /
updated_blessed_tick。节点不是 NPC、不是地理叙事实体、不是 Ecology
Engine —— M2b 只关心资源可用性。八态状态机（08 号 WS-0703：GROWING/
STABLE/DECLINING/EXHAUSTED/DAMAGED/MUTATED/NEWLY_FORMED/RECOVERING）
本阶段只实现 STABLE → EXHAUSTED（CAUSE_BASED：储量耗尽），完整状态机
属后续里程碑（NEW_PROPOSAL 收敛）。

## 8. Extraction（NEW_PROPOSAL 公式 + 08 号 risk 的 aggregate 化）
- `attempt = (extraction_carry + effective_capacity × interval_ticks)
  // TICKS_PER_YEAR`；`extraction_carry` 持久化整数进位。
- `effective_capacity = nominal_capacity × efficiency_num/den`；
  每 step 每节点一次离散抽样 idx=rng.randint(0,3) →
  效率 ∈ {100%, 95%, 90%, 85%}（08 号 risk 参数；只降不升，
  extracted ≤ capacity×years 恒成立）。
- finite：`extracted = min(attempt, remaining_reserve)`；
  `reserve_end = reserve_start − extracted + explicit_external_regeneration`
  （M2b regeneration=0）。不得负储量；耗尽 → EXHAUSTED +
  RESOURCE_DEPLETED。
- 储量 NULL = 未定级 → 不可开采（正式安全；不静默推断）。

## 9. Inventory（NEW_PROPOSAL）
resource_stocks：settlement × resource 行。quantity（minor units）+ 7 个
累计 ledger 计数器（cum_extracted/produced/input/imported/exported/
consumed/lost）+ consumption_carry。库存恒 ≥ 0；需求超库存 → 形成
fulfilled/unmet，绝不写负库存。

## 10. Production Recipe（NEW_PROPOSAL 结构）
production_recipes：recipe_id / input_resource_ref + input_qty_minor /
output_resource_ref + output_qty_minor / capacity_batches_per_year /
labor_per_batch / loss_num / loss_den / semantic_version。
`batches = min(容量进位, 输入库存//input_qty, labor_pool//labor_per_batch)`
（labor 是 aggregate 人口代理，NEW_PROPOSAL；绝不生成职业 NPC/工人
名单/劳动阶级）。input/output/loss 全部显式整数 —— 生产公式不隐藏
凭空创造（§15）。mini_world 只用 1 条合成配方。

## 11. Consumption（NEW_PROPOSAL）
`demand = Σ_species(per_capita_demand[resource] × pop × interval)`；
per_capita_demand 为 Fraction（canonical units/人/福地年），经
quantity_scale 转 minor units；亚年余数入 resource_stocks.
consumption_carry（持久化）。正式种族消费参数 UNCONFIGURED：
mini_world 用 TEST_ECONOMY_PROFILE_001；正式 Human/Hairy Men/Rockmen/
Mermen/Mushroommen 出现即 `EconomyProfileUnconfigured`
（code ECONOMY_UNCONFIGURED）。

## 12. Demand / Fulfillment（冻结）
demand ≥ 0；fulfilled ≤ demand；fulfilled ≤ 可用库存；unmet = demand −
fulfilled。每 (settlement, resource, step) 三者入事件与压力状态。

## 13. Transfer（NEW_PROPOSAL，版本化策略，非市场）
TRANSFER_POLICY_VERSION="m2b-transfer-v1"：每资源单趟贪心 —— 有库存
余量（stock_after_production − demand > 0）的聚落 → 存在缺口（< 0）的
聚落；X = min(need, surplus)；source_delta = −X、destination_delta = +X；
全局净变化 0；禁止双花（surplus 内存视图逐次扣减）/重复导入/重试重复
转移。不称"自由市场"。

## 14. Shortage / Surplus（机器经济状态）
economic_pressure_state 每 (settlement, resource)：demand/fulfilled/
unmet/shortage_ratio(num,den 约分 fixed-point)/sustained_shortage_steps/
stress_level(NONE/LOW/HIGH)。Shortage 是 ECONOMY STATE，不自动叙述为
饥荒/社会崩溃/战争/瘟疫；surplus 只是机器状态（无贸易繁荣/富裕阶级
叙事）。

## 15. Stock-Flow Ledger（RE_INV_14 核心审计）
每 (settlement, resource, interval)：
`ending = starting + extraction + production_output + imports
         − production_input − consumption − exports − losses`
（resource_stocks 累计计数器承载；RB20/RB23 实测对账）。

## 16. EconomicPressureSignal（committed state）
压力不是 Python 临时变量：写入 authoritative economic_pressure_state，
随 WORLD_COMMITTED 同事务提交。restart 后由 committed 状态完全重建
（RB25 实测 restart == continuous）。

## 17. Cross-Engine Feedback Lag（冻结）
CROSS_ENGINE_FEEDBACK_LATENCY = NEXT_COMMITTED_STEP。ECONOMY 于 step N
写压力 → DEMOGRAPHY 于 step N+1 经 start-of-step snapshot 读取
（services/simulation/feedback.py）。禁止同 tick 回写重算 DEMOGRAPHY
（RB26 实测：step 1 无前置压力，整合与纯人口运行 DEMOGRAPHY 全等）。

## 18. RNG
- RESOURCE 独立 substream（subsystem="RESOURCE"，derive_seed 含
  blessed_period_tick）：每 step 每节点 1 次离散效率抽样。
- ECONOMY 零 RNG（确定性规则优先，§45；draw_count=0）。
- 增加 RESOURCE/ECONOMY 抽样次数不得改变 DEMOGRAPHY 结果（RB34/RB35
  实测，独立 substream）。

## 19. Events（aggregate domain events）
RESOURCE_EXTRACTED / RESOURCE_DEPLETED（Resource 引擎）；
PRODUCTION_COMPLETED / CONSUMPTION_FULFILLED / RESOURCE_SHORTAGE /
RESOURCE_TRANSFERRED（Economy 引擎）。全整数 payload；绝不逐单位资源
产生事件。EVENT_UID_SCHEMA_VERSION=1（128-bit 确定性 identity）。

## 20. State Hash（WORLD_STATE_HASH_SCHEMA_VERSION 2 → 3）
v3 覆盖 Population + Resource Node/Profile + Inventory + Production
State + Economy Pressure State（全快照状态域）；canonical serialization +
语义键排序（行序无关，RB33）；无 NaN/Inf/rowid/now()。
**v2 语义冻结**：world_state_hash_v2 用 M2a 冻结表集/字段集，快照扩展
不得改变 v2 输出（M2a 120y 基线逐字节复现依赖）。coordinator 按管线
状态域选择：含 RESOURCE/ECONOMY → v3；仅 DEMOGRAPHY（M2a 回归）→ v2。

## 21. Event Hash（EVENT_STREAM_HASH_SCHEMA_VERSION=1，不变）
所有 Resource/Economy 事件进入增量链；canonical payload 全覆盖
（RB31 实测：转移 100 → 70，哈希必不同）。

## 22. Checkpoint（双层原子）
TIME_COMMITTED（M1 层）+ WORLD_COMMITTED（M2 层）同事务原子提交；
世界恢复权威 = latest complete WORLD_COMMITTED；TIME_COMMITTED 不证明
DEMOGRAPHY/RESOURCE/ECONOMY 全部成功（RB42 实测同 tick 同事务，绝无
"Year 50 population / Year 51 inventory" 脱节）。

## 23. Fencing
Writer A 完成 population+resource+economy 后 lease 丢失 → 提交被
FENCING_VIOLATION 拒绝，population/resource/inventory/events/checkpoint/
hash 全部 0 authoritative write（RB36 实测）。

## 24. Crash Recovery（R1–R8）
R1 after DEMOGRAPHY staged（engine:RESOURCE）；R2 mid RESOURCE；
R3 after RESOURCE staged（engine:ECONOMY）；R4 mid ECONOMY；
R5 after ECONOMY staged（after_engines）；R6 during authoritative write
（during_apply）；R7 checkpoint 前（事件已写/世界 checkpoint 未建 ——
原子对，TIME 绝无机会先于 WORLD 存在）；R8 commit ack lost
（after_checkpoint）。任何 crash 后：tick/population/reserve/inventory/
pressure/events/双哈希全一致，干净重试 == 一次成功（参数化矩阵实测）。

## 25. Idempotency
同 interval retry（M1 区间 skip + 确定性 uid 唯一约束）：零重复开采/
生产/消费/转移/shortage 事件/经济压力/人口变化（RB22/RB37-39 实测）。

## 26. 120y Baseline（TEST BASELINE，非 Canon）
mini_world_v1（M2b integrated：2 settlements + TEST-SPECIES-001 +
TEST-RESOURCE-001/002 + TEST 配方 + TEST 经济 profile）跑 120 福地年，
管线 DEMOGRAPHY→RESOURCE→ECONOMY 真实全部执行；
`tests/baselines/m2b_resource_economy_miniworld_120y_v1.json`。
全部数字 TEST_FIXTURE_ONLY，不得写入 World Bible/Local Canon/World
Seed，不得据以推断正式福地产量/消费量/生产力。

## 27. Performance
aggregate：每步 O(nodes + settlements × (recipes + resources)) 整数
运算；无 per-unit object / per-consumption agent / per-person economy
agent。120y wall time 记录于基线 performance 字段（不进哈希）。

## 28. PostgreSQL Compatibility
- 权威数量：SQLite INTEGER ↔ PostgreSQL BIGINT（BigInteger 列）；
  Python 侧无界 int，列写入前断言无负值；溢出风险如实标注（未实测 PG，
  见 Known Limitations）。
- 核心算法不依赖 SQLite json_extract / 隐式类型 / rowid /
  INSERT OR REPLACE；唯一约束全部显式命名（uq_*）。
- 生产代码不执行 SQLite-only 语法（测试内 json_extract 仅用于断言）。

## 29. Ecology Boundary（M2c）
禁止实现：资源再生生态/承载力生态/污染/土壤肥力/森林生命周期/水循环/
野生动物动态。只预留 EcologyModifier（regeneration_delta/yield_modifier/
degradation_modifier），当前 neutral/0。测试用足够大的 finite reserve，
不创造无限自然再生 Canon。

## 30. Social Boundary（M2d 或以后）
禁止：阶级/职业个人化/企业/政治/制度/家庭经济/社会冲突/文化偏好/
消费文化。labor 只作为 aggregate 人口代理参与生产容量，不产生任何
社会实体。

## 31. Known Limitations
- mini_world 每资源 1 配方、固定 settlement 序；多配方同输入的累计
  counter 语义已按 delta-ledger 设计（每行每字段 1 条 propose），但
  多配方并行的输入优先级尚未定义（未来 profile 化）。
- 转移策略 v1 为 NEW_PROPOSAL 简单贪心；不做跨资源等价/优先级。
- capacity_batches_per_year=NULL 的"无限产能"路径未在集成基线覆盖。
- 正式种族/资源的 Economy/Resource profile 全部 UNCONFIGURED：出现即
  报错（RB28/RB29 实测），不静默套用测试参数。
- PG 兼容为代码级审计结论，未经真实 PostgreSQL 实例运行验证。

## 32. NEW_PROPOSAL / CONFLICT_FOUND 汇总
- CONFLICT_FOUND：08 号 §4「市场简化模型（价格=基准价×调节因子）」与
  M2b 任务 §2 禁价列表冲突 → 裁决：市场/价格推迟，M2b 只建实物层；
  08 号 §1 生产链的 PROCESSING/TRANSPORT/MARKET 环节不在 M2b
  （EXTRACTION/STORAGE/CONSUMPTION/RESERVE 实装）。
- CONFLICT_FOUND：08 号节点八态全量状态机 > M2b 范围 → 收敛为
  STABLE→EXHAUSTED（原因驱动），其余状态属后续里程碑。
- NEW_PROPOSAL：整数 minor units 数量模型（scale=1_000_000）、
  离散效率表（risk aggregate 化）、生产配方结构、labor 代理、
  m2b-transfer-v1 转移策略、EconomicPressureSignal committed 表、
  feedback.py 适配器（TEST_FIXTURE_ONLY）、world_state_hash v3、
  7 个 ledger 计数器字段。
- 07/09 号（Social/Ecology）本次只做边界审计：不实装任何生态再生/
  社会结构；DEPRECATED_RUNTIME_TIME_MODEL 相关换算不涉及（全程
  blessed tick 整数）。
