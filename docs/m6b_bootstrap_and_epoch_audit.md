# M6B — ACTIVATION BOOTSTRAP & EPOCH CLOSURE（设计 / 审计）

- 阶段：`M6B`（owner 裁决：M6A 已接受；**未**授权 live staging；仍禁止正式激活与消费正式 Seed）
- 代码提交：见本阶段 commit（`feat:` epoch wiring / `test:` M6B 套件 / `docs:` 本文件与报告）
- 正式世界：保持 `NOT_ACTIVATED`（0 行 / tick NULL / seed 未消费）

---

## 1. Owner canon 决策的落地

| 决策 | 落地位置 | 语义 |
| --- | --- | --- |
| `OWNER_CANON_DECISION_1`：`INITIAL_BLESSED_TICK = 0` | `domain/constants.py::WorldActivationPolicy.INITIAL_BLESSED_TICK` | Runtime 内部正式时间原点；**NULL ≠ 0**（未激活仍为 NULL）。契约拒绝任何非 0 取值 |
| `OWNER_CANON_DECISION_2`：`ACTIVATION_ANCHOR = 显式激活操作的 canonical UTC instant` | `ActivationRequest.activation_anchor_us` + genesis `effect.activation_anchor_us` | durable authoritative fact，与 activation operation 一起持久化；tick=0 ⇒ `cursor = anchor` ⇒ **PRE_ACTIVATION_BACKLOG = 0** |
| `WAIT_FOR_2027_01_01_ACTIVATION` | 本节 + 报告 | **REJECTED**：Runtime correctness 不再依赖任何"等特定现实日期"，年锚由 activation 显式确立并持久化 |

`activation_anchor_us` 由 owner 控制面**显式**给出（`--activation-anchor-utc` /
`--activation-anchor-us`）；CLI 拒绝隐式 `now()`。一次 activation operation 只确定一次
anchor：ACK lost / crash 后重试**必须复用同一个值**，换值一律拒绝（`_already_committed_outcome`
的 anchor 一致性检查）。

## 2. Runtime Epoch Wiring（OPTION A）

```
RuntimeScheduler.epoch0_us = None  →  动态模式（生产路径：main.py 不传 epoch0）
  ┌ 世界未激活 → DEFAULT_OPERATIONAL_EPOCH0_US（既有 operational 默认，DORMANT 路径）
  └ 世界已激活 → durable_truth.read_world_epoch_anchor()   ← 唯一来源
                 读不到 → self._fail(...)（FAILED，零写入，绝不按 now() 重建）
```

- 生效年锚**每 cycle** 从 durable truth 解析（planner 按 anchor 值缓存；内存里不留 anchor 真值）；
- 规划阶段异常（年锚/时钟不自洽）→ **FAILED**（fail-closed），**绝不偷偷 repair**；
- 显式传入 `epoch0_us`（既有 M4 测试路径）→ 行为与 M6B 之前逐字一致（不改变 M4 语义）；
- 执行批次时把**同一个**生效年锚传给 `run_blessed_year`（年锚对齐不变量）。

## 3. Bootstrap Viability Audit（§6–§8，经验证据）

**方法**：synthetic activation world（M6 activation 服务激活，tick=0，anchor 显式）→
业务实体表全空 → 冻结生产管线
`SimulationCoordinator([PopulationGroupEngine, ResourceEngine, EconomyEngine, EcologyEngine,
SocialEngine], tribulation_engine=TribulationEngine, tribulation_adapters=DOMAIN_ADAPTERS)`
+ `HistoryLinkBuilder`，经生产适配器 `services/scheduler/adapter.run_blessed_year` 逐年推进 4 年。

**观测结果**：

```
NO_EXCEPTION              = TRUE      （4/4 年，零异常；含零 divide-by-zero）
DETERMINISTIC             = TRUE      （两次独立运行：digest/tick/cursor/events/
                                       runs/checkpoints/history/business 全部一致）
NO_INVALID_REFS           = TRUE      （孤儿事件 0 / 悬空 state_change 0 / 自环 0 /
                                       PRAGMA foreign_key_check 空）
NO_M2M3_INVARIANT_VIOLATION = TRUE
CLOCK_ADVANCE             = tick 4,000,000；cursor = anchor + 4×YEAR_US（年锚对齐）
EVENTS                    = WORLD_SEED_ACTIVATED ×1 + TIME_ADVANCE ×4（**零域事件**）
BUSINESS/HISTORY ENTITIES = 全部 0（settlements/population/resources/economy/ecology/
                            social/tribulation/history 实体与因果链接皆为 0）
HISTORY_INDEX_WATERMARK   = 随世界时钟推进（4,000,000），但无任何历史被建立
```

**结论**：空世界**不会崩**，但**永远不会形成任何域状态** —— 是一个永久空世界。

| 域 | 判定 | 证据 |
| --- | --- | --- |
| `DEMOGRAPHY_EMPTY_BOOTSTRAP` | **CANNOT_PROGRESS** | `population_groups`=0 → 零 `POPULATION_*` 事件；引擎零行即零产出（`population.py:181-185`），出生需要既有 cohort |
| `RESOURCE_EMPTY_BOOTSTRAP` | **CANNOT_PROGRESS** | `resource_nodes`=0 → 零 `RESOURCE_*` 事件 |
| `ECONOMY_EMPTY_BOOTSTRAP` | **CANNOT_PROGRESS** | `resource_stocks`/`production_state`/`economic_pressure_state`=0 → 零 `PRODUCTION_*`/`CONSUMPTION_*` 事件 |
| `ECOLOGY_EMPTY_BOOTSTRAP` | **CANNOT_PROGRESS** | `ecology_zones`/`ecology_state`=0 → 零 `ECOLOGY_*` 事件 |
| `SOCIAL_EMPTY_BOOTSTRAP` | **CANNOT_PROGRESS** | `settlement_social_state`/`social_feedback_state`=0 → 零 `HOUSEHOLD_*`/`LINEAGE_*`/`INSTITUTION_*` 事件（家庭由人口派生、机构需 pop ≥ 阈值） |
| `TRIBULATION_EMPTY_BOOTSTRAP` | **CANNOT_PROGRESS** | `tribulation_profiles`/`tribulation_schedules`=0 → `next_tribulation_boundary` 恒 None → 零 `TRIBULATION_*` 事件 |

```
EMPTY_WORLD_CAN_BOOTSTRAP = FALSE
M6_DESIGN_GAP_INITIAL_WORLD_STATE = BLOCKING
```

## 4. MINIMUM_REQUIRED_BOOTSTRAP_STATE（结构性，**不含数值**）

以下为"让冻结引擎能形成状态"的**结构最小集**（由反证探针 + 冻结引擎 fail-closed 语义定位）：

| # | 需要的根 | 为什么（冻结依据） |
| --- | --- | --- |
| 1 | **聚落根**（settlements） | 人口/资源/经济/生态/社会各域都以聚落为轴（`population_groups.settlement_ref`、`resource_stocks`/`production_state`/`economic_pressure_state` 的 settlement×resource 维度、`settlement_social_state` 每聚落一行） |
| 2 | **人口根**（population_groups：物种×聚落×年龄组×职业组） | 出生/死亡/迁移都作用于既有 cohort；零行即永久零人口 |
| 3 | **资源节点根**（resource_nodes + 有效 `resource_profile_ref`） | 缺 profile → `ResourceProfileUnconfigured`；`remaining_reserve` NULL 即不可采 |
| 4 | **经济状态根**（resource_stocks / production_recipes+production_state / economic_pressure_state） | 缺 stock 或 pressure 行 → `EconomyStateInconsistent`（fail-closed） |
| 5 | **生态根**（ecology_zones + ecology_state + ecology_feedback_state） | 缺 state → `EcologyZoneMissing`（fail-closed） |
| 6 | **社会状态根**（settlement_social_state + social_feedback_state，每聚落） | 缺行 → `IntegrityError`（fail-closed） |
| 7 | **灾劫配置根**（tribulation_profiles + tribulation_schedules） | 无排期 → 永无灾劫边界（引擎还要求以**正式** registry 构造，见下） |
| 8 | **正式 profile registry（五域）** | 生产引擎目前**不存在**任何正式 registry：`TEST_PROFILES`/`TEST-SPECIES-001`/`TEST-ECONOMY-PROFILE-001` 等皆为测试夹具；`TribulationEngine` 默认用 `TEST_PROFILES`（DB 行不参与 lookup） |

**探针证据**（`tests/test_m6b_bootstrap_viability.py::test_m6bbv05*`）：
在完整 mini world 上逐一删除 —— 缺社会状态 → 引擎 fail-closed；缺 resource stock →
状态不一致；缺 ecology state → 缺状态；缺人口根 / 缺灾劫排期 → 不报错但该域**永不产出**；
而完整的 mini world 基线**会**产生域事件（证明探针有效）。

## 5. World Seed 物化审计（§10/§11，只读）

只读取 seed 包的**状态元数据**（entry `status` 分布 + 取值是否已确定），不据"文件里出现数字"
就写正式 DB。

| 域 | seed 文件 | entry 状态分布（摘） | 明确可物化的 initial state spec？ | 判定 |
| --- | --- | --- | --- | --- |
| 身份/时间规则 | 01/02 | CONFIRMED_STATIC_CANON 多数；tick/纪年/anchor = NOT_ACTIVATED | 规则可物化为**规则**，但"初始值"由 activation 确立（已裁决） | `CANONICAL`（规则）/ activation 决定初值 |
| 地理 | 03 | CONFIRMED_STATIC_CANON 3 + APPROVED_WORLD_SEED 1 + NOT_ACTIVATED 1（分带槽名称 UNDECIDED） | 神社等静态 canon 有；8 个规划分带槽**无名称** | `CANONICAL`（静态）+ `PLANNING_ONLY`（槽位） |
| 人口 | 04 | PROVISIONAL_APPROVED_SEED 2 + APPROVED_WORLD_SEED 1 + NOT_ACTIVATED 3 | **无**（总人口为规划值；无 cohort/年龄组/职业组分解） | `PLANNING_ONLY` |
| 物种 | 05 | APPROVED_WORLD_SEED_DESIGN 5 + CONFIRMED_STATIC_CANON 1；`population_share` 未定 | 候选身份是设计；**比例未定** | `APPROVED_LOCAL_DESIGN` + `UNDEFINED`（比例） |
| 聚落 | 06 | PROVISIONAL_APPROVED_SEED 3 + APPROVED_WORLD_SEED 1 | 槽位数量级是规划；**NAME=UNDECIDED** | `PLANNING_ONLY` |
| 社会结构 | 07 | CONFIRMED_STATIC_CANON 2 + PROVISIONAL_DESIGN 1；实例 0 | 四层模型/自治原则可物化为**结构**，实例数为 0 | `APPROVED_LOCAL_DESIGN` + `UNDEFINED`（实例） |
| 经济 | 08 | CONFIRMED_STATIC_CANON 3 + APPROVED_WORLD_SEED 1 + UNKNOWN 1 | 产业类别与 USE≠MANUFACTURE 是规则；**无初始库存/产能数据** | `APPROVED_LOCAL_DESIGN` + `UNDEFINED`（初值） |
| 资源 | 09 | CONFIRMED_STATIC_CANON 2 + APPROVED_WORLD_SEED 1 + UNKNOWN 1；实例 0 | 节点类型/八态机是设计；实例 0 | `APPROVED_LOCAL_DESIGN` + `UNDEFINED`（实例） |
| 生态 | 10 | CONFIRMED_STATIC_CANON 3 + APPROVED_WORLD_SEED 1 | 静态生态区类型是设计；无初值 | `APPROVED_LOCAL_DESIGN` + `UNDEFINED`（初值） |
| 机构 | 11 | PROVISIONAL_DESIGN 1 + CONFIRMED_STATIC_CANON 1；实例 0 | 候选类型；实例 0 | `PLANNING_ONLY`/`UNDEFINED` |
| 初始事件边界 | 12 | APPROVED_WORLD_SEED 1（`WORLD_SEED_ACTIVATED`）+ CONFIRMED_STATIC_CANON 1 + NOT_ACTIVATED 3 | **是**（canon 明确） | `CANONICAL` |
| UNKNOWN 注册表 | 13 | `rule` + `unknown_fields` | 按 A9 **必须保持 UNKNOWN** | `UNDEFINED`（不得补全） |
| 激活不变量 | 14 | A1–A10 CONFIRMED_STATIC_CANON | 是 | `CANONICAL` |

```
WORLD_SEED_BOOTSTRAP_SPEC_STATUS = ABSENT
  （seed 包提供了**规则/边界/类型/槽位**与 UNKNOWN 注册表，
    但没有任何"可直接物化为正式世界初始实体"的 canonical bootstrap state；
    已知规划总人口是 PLANNING_ONLY，按 00 号 §3 严禁升级为 canonical state）
```

## 6. 结论与所需主人决定

```
EPOCH_WIRING = PASS（OPTION A 已实现并测试；restart/进程替换/wall-clock 均不改变 anchor）
EMPTY_WORLD_CAN_BOOTSTRAP = FALSE
M6_DESIGN_GAP_INITIAL_WORLD_STATE = BLOCKING
CANONICAL_BOOTSTRAP_SPEC = ABSENT
M6B_READY = FALSE
M6_ACTIVATION = BLOCKED_DESIGN      ← 不是代码失败
```

主人需要在**新的 canon 决定**中给出其中之一（本阶段**不**实现 materializer）：

1. **授权设计最小 bootstrap 规范**：明确"正式世界出生时必须存在哪些根实体、由谁在哪个
   sub-stage 物化、其 canonical 来源是什么"（例如：种子基线 + 明确的物化规则），
   并同时授权**正式 profile registry**（五域）；之后另立 sub-stage 实现 materializer。
2. 或者**修改 M2 语义**（例如允许引擎从空世界自发生成初始实体）—— 但这属于修改冻结语义，
   需要主人显式授权，本阶段明确不做。
3. 或者**接受"空世界出生"**并把世界内容推迟到未来（当前证据显示：世界将永久为空，
   `TIME_ADVANCE` 空转；不建议，且与 "no permanent dead world" 判定冲突）。

> 记录：`WAIT_FOR_2027_01_01_ACTIVATION = REJECTED`（§23）；年锚已由 activation 显式确立，
> Runtime 不再依赖任何特定现实日期。
