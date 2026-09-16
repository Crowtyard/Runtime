# M6C.0 — BOOTSTRAP CANON AUDIT 报告（M6C_BOOTSTRAP_CANON_AUDIT_REPORT）

- 阶段：`M6C.0 BOOTSTRAP CANON AUDIT`（owner `OWNER_DECISION = OPTION_1`；**第一轮只授权到 STOP A**）
- 前置：`M6A_ACTIVATION_CONTRACT = PASS`、`M6B_EPOCH_WIRING = PASS`、
  `EMPTY_WORLD_CAN_BOOTSTRAP = FALSE`、`WORLD_SEED_BOOTSTRAP_SPEC_STATUS = ABSENT`、
  `M6_DESIGN_GAP_INITIAL_WORLD_STATE = BLOCKING`、`M6B_READY = FALSE`
- 详细审计：`docs/m6c_minimal_bootstrap_canon_audit.md`
- 分支：`m5-query-companion`（development branch；未创建 M6 frozen tag、未 amend/rebase/force）

> **本阶段没有激活正式世界，也没有实现 materializer。** 正式库仍 0 行 /
> `NOT_ACTIVATED` / tick NULL / seed 未消费；live 未更新。

## 0. 一句话结论

**缺的不是"数字多少"，而是"谁有权定这些数字"。**

七根**全部**是冻结引擎的硬前置（IS_REQUIRED = TRUE），其**结构**基本都有 canon；
但**实例初值**只有三条粗粒度设计基线（人口≈12,000、聚落≈4 主+6~10 卫星、
灾劫层级≈10/50/100 福地年），全部附"约值/激活前不得表述为事实/待 SNAPSHOT 裁决"限定；
引擎真正需要的**分解结构**（年龄 cohort、每聚落分配、启用集合、节点数/储量、
库存/产能、生态区数/初值、社会阈值、正式灾劫周期）**全部 UNDEFINED**，且
Seed 包既不提供这些值也不定义派生算法（其角色 = B），并明令禁止 Runtime 补全（A9）。

关键正面发现：canon **已经定义了解决机制**——
`WORLD_CREATION_REVIEW →（S-1..S-10 逐项批准）→ SNAPSHOT_V1`，且明文
"模拟启动前必须 SNAPSHOT_V1 就绪"。该机制**尚未执行**（十项全 PENDING_APPROVAL、
无已批准快照）。因此本阶段结论为 **STOP A**：返回最小 owner 决策列表，**不写 materializer**。

## 1. 审计方法与来源分级

```
LOCAL_CANON（world_bible v1.0 FROZEN + v0.1.0 chunks）
  > APPROVED_LOCAL_DESIGN（已批准设计/引擎契约 M2/M3）
  > LOCAL_COMPATIBILITY > SOURCE_LORE_GENERAL_RULE
  > PLANNING_ONLY（PROPOSAL / PENDING_APPROVAL / PROVISIONAL / UNDECIDED）
  > TEST_FIXTURE（TEST_* / mini_world / synthetic —— 严禁提升）
```

只读取证，覆盖：world_seed 21 文件（MANIFEST 20/20 复算匹配）、world_bible 全量、
runtime_design 全量（含 M2A/M2B/M2C/M2D/M3 契约）、design/phase1_8 全量、
v0.1.0 chunks、以及本仓库冻结实现的 ORM/引擎代码。

## 2. 逐根结果（详见审计文档 §2）

| 根 | IS_REQUIRED | STRUCTURE_CANON | INSTANCE_VALUE_CANON | VALUE_STATUS |
| --- | --- | --- | --- | --- |
| SETTLEMENT_ROOT | TRUE | ✔（WS-0406 槽位/类型） | 部分（量级有基线，启用集合/命名未定） | APPROVED_LOCAL_DESIGN（量级）+ UNDEFINED（启用集合）+ **canon 冲突**（S-3 vs WS-0406） |
| POPULATION_ROOT | TRUE | ✔（宏观群体模型，无个体 agent） | 部分（总量有基线；年龄结构/每聚落分配/职业组无 canon） | APPROVED_LOCAL_DESIGN（总量量级）+ UNDEFINED（结构分解） |
| RESOURCE_NODE_ROOT | TRUE | ✔（节点类型 + 八态机） | ✘ | UNDEFINED |
| ECONOMY_STATE_ROOT | TRUE | ✔（产业类别 + 使用≠制造 + 生产链） | ✘ | UNDEFINED |
| ECOLOGY_STATE_ROOT | TRUE | ✔（11 类生态区 + 状态字段名） | ✘ | UNDEFINED |
| SOCIAL_STATE_ROOT | TRUE | ✔（四层模型 + 自治原则） | ✘ | UNDEFINED |
| TRIBULATION_CONFIG_ROOT | TRUE | partial（层级/代谢机制/边界） | 部分（层级有基线；正式周期/首个前兆未裁决） | APPROVED_LOCAL_DESIGN（层级量级）+ UNDEFINED（正式周期） |

## 3. 正式 Profile Registry 状态（owner §4）

```
FORMAL_POPULATION_PROFILE_REGISTRY  = ABSENT（仅 TEST_SPECIES_PROFILE / SPECIES_PROFILES）
FORMAL_RESOURCE_PROFILE_REGISTRY    = ABSENT（仅 TEST_RESOURCE_PROFILE_001..003）
FORMAL_ECONOMY_PROFILE_REGISTRY     = ABSENT（仅 TEST_ECONOMY_PROFILE / TEST-SPECIES-001）
FORMAL_ECOLOGY_PROFILE_REGISTRY     = ABSENT（仅 TEST_ECOLOGY_PROFILE）
FORMAL_SOCIAL_PROFILE_REGISTRY      = ABSENT（仅 TEST_SOCIAL_PROFILE）
FORMAL_TRIBULATION_PROFILE_REGISTRY = ABSENT（仅 TEST_PROFILES / TEST_SCHEDULE）
FORMAL_PROFILE_REGISTRY_GAP         = TRUE
M6C_BLOCKER_TRIBULATION_PROFILE     = TRUE
  （引擎侧 `self._profiles = profiles or TEST_PROFILES`（tribulation.py:308）为**静默回落**：
    传空 dict 也会回落测试档；且 DB 的 tribulation_profiles 行不参与 profile lookup。
    本阶段**未**改（owner §18 禁止"改名当正式"）。）
```

六域的 registry 均**自声明** `TEST_FIXTURE_ONLY`（"不得作为正式种族/资源/生态/社会 Canon"），
缺 profile 时 fail-closed（`DEMOGRAPHY_UNCONFIGURED` / `RESOURCE_UNCONFIGURED` /
`ECONOMY_UNCONFIGURED` / `ECOLOGY_UNCONFIGURED` / `SOCIAL_UNCONFIGURED`）。

## 4. World Seed 角色（owner §6）

```
WORLD_SEED_BOOTSTRAP_ROLE = B
  （仅规则 / 类型 / slot / constraints；**不含**可物化的 bootstrap instance values，
    也**不含** seed → instance 的确定性派生算法）
```

- A：直接包含实例值 → **NO**（11 域全部为 null/0/EMPTY/UNDECIDED）；
- B：仅规则/类型/槽位/约束 → **YES**（11 域）；
- C：确定性派生算法 → **NO**（全包无 hash/PRNG/分布/分配/公式；`02:10` 明令禁止自造公式）；
- D：混合 → 是"规格种类"的混合（canon 规则/已批准结构/规划值/UNKNOWN 占位/禁止项/包外候补），
  **不存在实例层**。

包自述的激活事务载荷（A4）＝ seed、activation epoch、initial tick、real cursor、
initial static world state —— **其中没有任何域实例载荷**；实例值被外推给包**未定义**的
"SNAPSHOT / 激活后由 Runtime 生成 / 历史自然演化"，其 U-01..U-15 的 owner 是
"主人裁决 / SNAPSHOT 批准"。

## 5. 结构依赖图与完整性（owner §12/§13/§14）

- **业务表之间没有任何 DB 级外键**：全库 45 张表只有 7 条 FK，且全部是
  `*.world_id -> world_runtime`（自动提取验证）。表间关系全部是**软引用字符串**
  （`settlement_ref` / `resource_profile_ref` / `zone_ref` / `recipe_ref` / `species`）。
- 因此 `ROOT_DEPENDENCY_GRAPH` 由**引擎前置条件 + 软引用语义**给出（详见审计文档 §4）：
  `world_runtime → time_ratio_history → settlements →{population_groups, resource_nodes →
  resource_stocks/production_state/economic_pressure_state, ecology_zones → ecology_state/
  ecology_feedback_state, settlement_social_state → social_feedback_state}`，
  另加 `tribulation_profiles/tribulation_schedules` 与 genesis `world_events`。
- **无 cycle**；但**软引用完整性不受 DB 保护** → 未来 materializer 必须自行校验并
  fail-closed（M6B 的 `PRAGMA foreign_key_check` 在此无效，因为没有 FK 可查）。
- **只能由 bootstrap 提供**（任何引擎都无权创建，`contracts.py:23-42` + 全目录检索无命中）：
  `settlements`、`ecology_zones`（**无任何 owner**）、`resource_profiles`、
  `production_recipes`、`tribulation_profiles`、`tribulation_schedules`、`industries`、
  `ecological_regions`、`persons`、`tribulations`、`timeline_entries`、`cultural_elements`
  → 这直接构成 §14 的 `MINIMUM_BOOTSTRAP_ENTITY_SET` 证据（引擎不能自我长出这些根）。
- **完整性硬要求**（否则 fail-closed 或**静默丢数据**）：`settlements.working_name` 必须有值；
  `population_groups` 必须覆盖**每个 cohort bucket**（缺行即静默丢人口，违反 P_INV_12）；
  `resource_stocks` 必须是**完整矩阵**（否则中途 KeyError）；
  `economic_pressure_state` 每个 `(聚落 × 消费类资源)` 一行；
  每个生态区必须有 zone+state+feedback 三行；每个聚落必须有 social state+feedback 两行；
  `tribulation_schedules.tier` 必须 ∈ {REGULAR,MAJOR,CENTENNIAL}。
- **两处引擎侧陷阱**（正式世界必须知情）：`TribulationEngine` 对 DB 的 `tribulation_profiles`
  是**死读**（lookup 只用构造注入的 registry；`tribulation_schedules` 才是真杠杆）；
  `SocialEngine` 的 `SocialProfileUnconfigured` **从未 raise**、`SOCIAL_PROFILES` 是**死代码**，
  且空值会静默回落测试档。

## 6. 硬门禁（owner §16，已实现并测试）

`tests/test_m6c_bootstrap_canon_guard.py`（6 项，全绿）：

```
TEST_FIXTURE_REFERENCES_IN_BOOTSTRAP = 0
  （AST 代码级扫描正式 bootstrap/activation 路径：TEST_PROFILES / TEST-SPECIES /
    TEST_*_PROFILE / TEST_SCHEDULE / mini_world / synthetic_world / TEST_FIXTURE_ONLY）
NO_ENGINE_IMPORT_OR_CONSTRUCTION_IN_BOOTSTRAP_PATH = TRUE
KNOWN_CANON_GAPS_PINNED = TRUE（六域 registry 的 TEST_FIXTURE_ONLY 自声明、
    *_UNCONFIGURED 语义、灾劫静默回落、社会 `profile or TEST_SOCIAL_PROFILE` 全部钉住：
    任何"改名当正式/静默接测试档"都会使门禁失败，必须显式授权后连同门禁一起改）
NO_MATERIALIZER_PRESENT = TRUE（§29：AST 定义名判定，未获授权前不得实现）
```

## 7. 结论

```
CANONICAL_BOOTSTRAP_SPEC = INCOMPLETE
M6C_CANON_READY          = FALSE
TEST_FIXTURE_DEPENDENCY  = TRUE（引擎构造默认全部指向测试档 → 必须由正式 registry 取代）
```

按 owner §8/§21/§22：不得写正式 materializer；落入 **STOP A**，返回最小 owner 决策列表。

---

## 返回字段（§30）

```
M6C_BOOTSTRAP_CANON_AUDIT_REPORT

MINIMUM_REQUIRED_BOOTSTRAP_STATE =
  SETTLEMENT_ROOT + POPULATION_ROOT + RESOURCE_NODE_ROOT + ECONOMY_STATE_ROOT
  + ECOLOGY_STATE_ROOT + SOCIAL_STATE_ROOT + TRIBULATION_CONFIG_ROOT
  （七根全部 IS_REQUIRED = TRUE；详见 docs/m6c_minimal_bootstrap_canon_audit.md §2）
  完整性硬要求（否则 fail-closed 或静默丢数据）：
    · settlements.working_name 必须有值（四域以其为键）
    · population_groups 必须覆盖**每个 cohort bucket 0..N-1**（缺行即静默丢人口，违反 P_INV_12）
    · resource_stocks 必须是**完整矩阵**（否则经济引擎中途 KeyError）
    · economic_pressure_state 每个 (聚落 × 消费类资源) 一行
    · 每个生态区必须有 ecology_zones + ecology_state + ecology_feedback_state 三行
    · 每个聚落必须有 settlement_social_state + social_feedback_state 两行
    · tribulation_schedules.tier ∈ {REGULAR,MAJOR,CENTENNIAL} 且 period_years 非空
  MINIMUM_BOOTSTRAP_ENTITY_SET 的最小性已逐项验证（详见审计文档 §2.3）：
    households/lineages/institutions（SOCIAL 自建）、tribulation_episodes/decisions/
    impact_plans/recovery_states/residual_changes/succession_candidates（引擎/API/协调器自建）、
    tribulation_profiles（死读）、ecological_regions/industries/persons/tribulations/
    timeline_entries/cultural_elements（无引擎读写）**均不属于**最小集。

SETTLEMENT_ROOT_REQUIRED       = TRUE
SETTLEMENT_CANON_STATUS        = STRUCTURE_CANON ✔（WS-0406 ≈4 主 + 6~10 卫星，APPROVED_WORLD_SEED_DESIGN）
                                 / INSTANCE_VALUE_CANON ✘（实际启用集合与命名待 SNAPSHOT）
SETTLEMENT_UNDEFINED_FIELDS    = enabled slot set（MAIN/SAT 各启用哪些）、每聚落 settlement_type、
                                 working_name 策略（WORKING_NAME 占位与否）；
                                 + canon 冲突：S-3 草案（2~6 聚落）vs WS-0406（4 主 + 6~10 卫星）

POPULATION_ROOT_REQUIRED       = TRUE
POPULATION_CANON_STATUS        = STRUCTURE_CANON ✔（宏观群体模型，无个体 agent）
                                 / INSTANCE_VALUE_CANON 部分（仅"约 12,000"总量基线）
POPULATION_UNDEFINED_FIELDS    = 年龄结构（cohort 划分与占比）、每聚落分配、职业组划分、
                                 户统计口径、四族精确名额（候选 4k/3k/2.5k/2.5k 待批）

RESOURCE_ROOT_REQUIRED         = TRUE
RESOURCE_CANON_STATUS          = STRUCTURE_CANON ✔（节点类型 + 八态状态机）
                                 / INSTANCE_VALUE_CANON ✘
RESOURCE_UNDEFINED_FIELDS      = 节点数、每节点 kind、正式 resource_profile_ref、
                                 remaining_reserve、extraction_capacity、坐标/归属

ECONOMY_ROOT_REQUIRED          = TRUE
ECONOMY_CANON_STATUS           = STRUCTURE_CANON ✔（产业类别 + USE≠MANUFACTURE + 生产链）
                                 / INSTANCE_VALUE_CANON ✘
ECONOMY_UNDEFINED_FIELDS       = 初始库存（每 聚落×资源）、production_recipes 清单与产能、
                                 是否需要初始 production_state / economic_pressure_state 行、货币形态

ECOLOGY_ROOT_REQUIRED          = TRUE
ECOLOGY_CANON_STATUS           = STRUCTURE_CANON ✔（11 类生态区类型 + 状态字段名）
                                 / INSTANCE_VALUE_CANON ✘
ECOLOGY_UNDEFINED_FIELDS       = 生态区数量、位置/边界、每区 profile_ref、
                                 ecology_state / ecology_feedback_state 初值语义、carrying_capacity

SOCIAL_ROOT_REQUIRED           = TRUE
SOCIAL_CANON_STATUS            = STRUCTURE_CANON ✔（四层模型 + 自治原则）
                                 / INSTANCE_VALUE_CANON ✘
SOCIAL_UNDEFINED_FIELDS        = 每聚落 social state/feedback 行（结构已定、值未定）、
                                 正式阈值参数（formation_size / split_threshold /
                                 institution_found_pop 等）的取值来源、
                                 Persistent NPC 锚点（设计带 8~12/≤20~40，实例未创建）

TRIBULATION_ROOT_REQUIRED      = TRUE
TRIBULATION_CANON_STATUS       = STRUCTURE_CANON partial（T-3M 层级 + 代谢机制 + 边界）
                                 / INSTANCE_VALUE_CANON 部分（层级≈10/50/100 福地年）
TRIBULATION_UNDEFINED_FIELDS   = 正式周期数值终裁（是否落定 10/50/100）、首个前兆时间、
                                 tribulation_profiles 正式参数、tribulation_schedules 排期行；
                                 （存在未批竞争草案 20~40/80~120 年）

FORMAL_PROFILE_REGISTRY_STATUS = ABSENT_FOR_ALL_SIX_DOMAINS
                                 （FORMAL_PROFILE_REGISTRY_GAP = TRUE；
                                  M6C_BLOCKER_TRIBULATION_PROFILE = TRUE —— 引擎静默回落测试档）

WORLD_SEED_BOOTSTRAP_ROLE      = B（仅规则/类型/slot/约束；无实例值、无派生算法）

CANONICAL_BOOTSTRAP_SPEC       = INCOMPLETE

TEST_FIXTURE_DEPENDENCY        = TRUE
                                 （六域引擎构造默认指向 TEST_* registry；正式路径已由
                                  M6C-G01/G01b/G02/G02b 门禁隔离，实测
                                  TEST_FIXTURE_REFERENCES_IN_BOOTSTRAP = 0）

MINIMUM_OWNER_DECISIONS_REQUIRED =
  D-A  批准 S-1..S-10 形成 SNAPSHOT_V1（canon 已定义机制与清单；当前十项全 PENDING_APPROVAL）
       + 裁决 canon 冲突：S-3（2~6 聚落）vs WS-0406（4 主 + 6~10 卫星）
  D-B1 人口：年龄结构（cohort 划分与占比）
  D-B2 人口：每聚落分配（含物种×聚落交叉）
  D-B3 人口：职业组划分与户统计口径
  D-B4 人口：四族精确名额（候选值待裁决）
  D-B5 聚落：启用槽位集合与 settlement_type、命名策略
  D-B6 资源：节点数、kind、正式 profile_ref、剩余储量与开采容量初值/口径
  D-B7 经济：初始库存、配方清单与产能、初始 state 行策略
  D-B8 生态：生态区数量、正式 profile_ref、状态/反馈初值语义
  D-B9 社会：正式阈值参数来源（或明确"正式世界不使用阈值"）
  D-B10 灾劫：正式周期数值终裁 + 首个前兆时间
  D-C  授权五域正式 profile registry（bootstrap configuration 层；owner §17）
       —— 并决定是否授权去除 TribulationEngine 的测试档静默回落（owner §18）
  D-D  是否授权"由 seed/规则确定性派生实例值"（需先批准 derivation rule；M6C 不得自行发明）

M6C_CANON_READY = FALSE

FORMAL_WORLD_RUNTIME_ROWS  = 0
FORMAL_WORLD_STATUS        = NOT_ACTIVATED
FORMAL_WORLD_SEED_CONSUMED = FALSE

NEXT_ACTION = AWAIT_OWNER_BOOTSTRAP_CANON_DECISIONS
              （批准 SNAPSHOT_V1（S-1..S-10）+ 裁决 D-B1..D-B10 / D-C / D-D；
                裁决后另立独立 sub-stage 实现 materializer —— 本阶段未实现）
```

## 本阶段未做的事（§29）

- **未实现 materializer**（硬门禁 `M6C-G03` 已钉住"未授权前不得出现"）；
- 未修改任何冻结 M2/M3 语义、未新增任何世界规律、未改动 Golden Baseline；
- 未把测试 profile 改名当正式 profile、未把任何测试档接进正式路径；
- 未激活正式世界、未消费正式 Seed、未读正式 Seed 原值、未写正式库、未部署 live。

**STOP** — 等待主人对 bootstrap canon 的裁决。
