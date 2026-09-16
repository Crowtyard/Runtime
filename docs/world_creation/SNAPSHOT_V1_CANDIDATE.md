# SNAPSHOT_V1_CANDIDATE — 正式世界初始快照候选（M6C.1）

```
STATUS                    = CANDIDATE_NOT_APPROVED
MATERIALIZATION_ALLOWED   = FALSE
FORMAL_ACTIVATION_ALLOWED = FALSE
WORLD_SEED_CONSUMED       = FALSE
AGENT_MAY_PROMOTE_TO_SNAPSHOT_V1 = FALSE
PRODUCED_BY               = M6C.1 — SNAPSHOT_V1 CANDIDATE CONSTRUCTION
MACHINE_READABLE          = docs/world_creation/SNAPSHOT_V1_CANDIDATE.json
```

> 本文件是**候选**，不是 SNAPSHOT_V1。它没有被批准，也不能被物化。Agent 无权把它升级为
> SNAPSHOT_V1 —— 升级只能由主人在 `WORLD_CREATION_REVIEW` 中逐项批准（owner §25）。

---

## 0. 这是什么 / 这不是什么

| 是 | 不是 |
| --- | --- |
| 把**主人已批准**的输入展开成结构化的、每个数字都可归属来源的候选 | 不是正式世界数据；不含任何未批准数值 |
| 把**冻结引擎**的完整性要求（fail-closed 行、完整性矩阵）登记为 bootstrap 义务 | 不是 materializer（本阶段禁止实现，owner §26） |
| 声明并实现**确定性、可独立复算**的派生规则（RA-*），使派生数字可重算 | 不使用 RNG、不使用 `hash(seed) % N`、不使用测试夹具数值 |
| 把仍缺来源的数值收敛成**最少 owner 决策项**（OD-1..OD-10） | 不替主人发明人口结构、产业、资源、阈值、灾劫数值 |

**判定**：候选本身构造成功；但**存在 REQUIRED root 的 blocking field**（§9 OD-1..OD-10），
因此按 owner §26 —— **停止**：不得进入 materializer、不得激活、不得消费 Seed。

---

## 1. 现况与证据（红线，逐字不变）

```
FORMAL_WORLD_RUNTIME_ROWS        = 0
FORMAL_WORLD_STATUS              = NOT_ACTIVATED
CURRENT_BLESSED_TICK             = NULL
FORMAL_WORLD_SEED_CONSUMED       = FALSE
FORMAL_WORLD_SEED_STATUS         = PREPARED_NOT_ACTIVATED
alembic head                     = a9d4f2b7c1e8（无新迁移）
formal DB SHA256                 = 7754b1d4658ea94ce509ae7fb7c06c33c44f98782021b3708e6f29ce69102837
seed manifest SHA256             = cc0e4c0e16c7e2ec8cecb4ba871afc3af1a402e94732e645fceb4b1aca73771d
```

以上由独立校验器 `scripts/validate_snapshot_candidate.py` 每次校验（红线漂移即 INVALID）。

**M6C.1 结束时只读实测（live launcher 实例库，`sqlite3 mode=ro`，不写、不建 sidecar）**：

```
path            = ...\.astrbot_launcher\instances\<instance-id>\core\data\plugin_data\
                  astrbot_plugin_blessed_land_runtime\blessed_land.sqlite
size            = 544768 B      sidecars = -wal 0 B / -shm 32768 B
sha256          = 7754b1d4658ea94ce509ae7fb7c06c33c44f98782021b3708e6f29ce69102837
                  → 与 M6.0–M6C 基线**一致**
world_runtime   = 0 行（canonical：0 行 == 世界未激活，`tests/formal_db.py:4-13`）
其它业务表      = 全部 0 行（唯一非空表 alembic_version = a9d4f2b7c1e8）
```

> ⚠ **诱饵警告（M6C.1 新发现）**：`D:\MY SELF\AstrBot\data\plugin_data\astrbot_plugin_blessed_land_runtime\blessed_land.sqlite`
> 是**非权威副本**（mtime 2026-09-10、sha256 `e0c5d32f…8203`、`world_runtime = 1 行`）。
> live 实例库在 **launcher instance 路径**下。任何红线检查都必须指向 launcher 路径，
> 否则会读到过期副本并**误判**（该副本的 1 行 `world_runtime` 会让"未激活"断言看起来失败）。

**World Seed 只读实测（同一轮）**：

```
seed_dir        = <KB>\world_seed（default_seed_dir）
seed_id/version = XIAOGUANG_BLESSED_LAND_WORLD_SEED_v1.0 / 1.0
declared_status = PREPARED_NOT_ACTIVATED      consumed = FALSE
fingerprint     = cc0e4c0e16c7e2ec8cecb4ba871afc3af1a402e94732e645fceb4b1aca73771d
                  → 与 M6 基线一致；MANIFEST 20 条目
```

工具：`services.activation.seed_package.load_seed_package`（只读装载校验；**未消费、未改写、未激活**）。

---

## 2. S-1..S-10 逐项状态（canon 真实结构：`design/phase1_8/11`）

| # | canon 待批项 | canon 建议 | 候选状态 | 候选内容 / 阻塞原因 |
| --- | --- | --- | --- | --- |
| S-1 | 大致总人口 | 小型/中型/较大 | **APPROVED_BY_OWNER** | `12000` |
| S-2 | 异人种族组合 | OPTION_A/B/C | **BLOCKED** | `species` 是 NOT NULL 且必须命中正式 profile registry；名额已批准但**族身份**未批准（OD-1） |
| S-3 | 主要聚落数量 | 核心神社区 + 2~6 聚落（草案） | **APPROVED_BY_OWNER** | `12 = MAIN 4 + SATELLITE 8`（WS-0406 胜出；旧草案标 `SUPERSEDED_FOR_FORMAL_BOOTSTRAP`，保留历史记录） |
| S-4 | 主要产业 | 农业/药园/林产/水产/工坊/贸易 | **BLOCKED** | 只能由 `production_recipes`/`industries` 表达；无批准清单（OD-5） |
| S-5 | 主要资源区 | 灵田/药园/果园/林区/湖区/矿脉 | **BLOCKED** | `resource_profiles`/`resource_nodes` 无批准集合；`resource_stocks` 必须完整矩阵（OD-6） |
| S-6 | 荒兽/异兽层级 | 维持 BL-011 语义 | **UNRESOLVED（不阻塞）** | 冻结引擎无此实体/规则（NOT_FOUND）；只影响叙事层 |
| S-7 | 社会组织 | 神社核心 + 村落自治 | **BLOCKED** | 组织形态只能由正式 `SocialProfile` 阈值表达，而阈值仅存在于测试档（OD-9） |
| S-8 | 基础设施 | 道路/水渠/仓/集市 | **UNRESOLVED（不阻塞）** | 引擎无基础设施表；如需表达可复用 `institutions`（SOCIAL 自建） |
| S-9 | 发展水平 | 安居传统小社会基调 | **DERIVED** | 不设独立字段：由 S-4/S-5/S-8 的具体集合共同表达（本候选不新增口径） |
| S-10 | 灾劫状态 | mode=UNDECIDED | **PARTIAL / BLOCKED** | 周期已批准；**首个前兆时间已派生**（10 福地年）；`mode` 与正式 profile 数值待 OD-10 |

---

## 3. 已批准输入（本轮 owner 决定，逐字记录）

```
D-A   SNAPSHOT 流程：WORLD_CREATION_REVIEW → S-1..S-10 → CANDIDATE → OWNER APPROVAL
      → SNAPSHOT_V1 → Materializer → Activation                = APPROVED
D-B1  canon 冲突：WS-0406 胜出；旧 S-3 = SUPERSEDED_FOR_FORMAL_BOOTSTRAP  = APPROVED
D-B2  INITIAL_SETTLEMENT_COUNT = 12 = MAIN 4 + SATELLITE 8               = APPROVED
D-B3  工作名 MAIN-01..04 / SAT-01..08 = WORKING_NAME_ONLY                = APPROVED
D-B4  INITIAL_TOTAL_POPULATION = 12000（设计基线 → bootstrap canon）     = APPROVED
D-B5  GROUP_1..4 = 4000 / 3000 / 2500 / 2500（沿用既有槽位，不重命名）    = APPROVED
D-B6  MAIN 2000×4 + SATELLITE 500×8 = 12000                             = APPROVED
D-B7  确定性最大余额分配；固定顺序 + 固定 tie-break；无 RNG / 无 hash(seed) = APPROVED
D-C   六个 FORMAL_*_PROFILE_REGISTRY = BOOTSTRAP CONFIGURATION（非 engine law）= APPROVED
D-C2  PRODUCTION_TEST_PROFILE_FALLBACK = FORBIDDEN（缺失即 FAIL CLOSED）  = APPROVED
D-D   确定性派生：显式输入/输出、版本化、可独立复算、记入 SNAPSHOT_V1、
      不得用测试夹具、不得改 M2/M3 语义；禁止随机/未批准 RNG/hash-mod   = APPROVED_WITH_CONSTRAINTS
D-E   灾劫周期 REGULAR=10 / MAJOR=50 / CENTENNIAL=100 福地年             = APPROVED
D-F   首个前兆时间：**由冻结引擎派生**（不再是 owner 选择题）             = APPROVED_AS_DERIVED
```

`WORKING_NAME_ONLY`：`MAIN-01..04` / `SAT-01..08` 是槽位标签，**不是**世界内最终名称；
未来改名**不得**重建聚落 identity。

---

## 3b. 逐域问答（owner 逐域提问的逐项回答）

| 域 | 问题 | 候选回答 | 状态 | 依据 / 决策 |
| --- | --- | --- | --- | --- |
| **年龄结构** | cohort 划分与占比？ | 结构由引擎定义（bucket 宽固定 1 福地年、`[i, i+1)`、末位开区间、出生入 bucket 0、cohort == 一行 `population_groups`）；占比由 `RA-COHORT-001` 从**存活曲线**确定性派生 | **结构 = DERIVED / 数值 = BLOCKED** | `population.py:9,63-97,140-146,289-292,339,344-346`；OD-3 |
| **职业** | 职业组划分与户统计口径？ | **无需决策**：`occupation_group` 无任何引擎读取（WRITE_ONLY，仅影响 snapshot 行序 + 世界状态哈希）；`household_stats` 零读零写且不在投影内；经济劳动力 = 聚落总人口 // `labor_per_batch` | **NOT_REQUIRED** | `snapshot.py:88-91,263-264`；`economy.py:133-136,188-211` |
| **户** | 初始户结构是否预置？ | **不预置**：SOCIAL 首步自建（`formation_size` 确定性 id，自愈）；fail-closed 只针对 `settlement_social_state` / `social_feedback_state` | **DERIVED_BY_ENGINE** | `social.py:267-299,568-575` |
| **资源** | 资源集合 / 节点 / 正式 profile？ | 结构已派生（`resource_stocks` = 12 × R 完整矩阵）；R、节点集合与 profile 数值无来源 | **BLOCKED** | `economy.py:297-305`；OD-6 |
| **经济** | 初始库存 / 配方 / pressure 行？ | 结构已派生（`economic_pressure_state` = 12 × C；无 `production_state` 行 = 不生产，不报错）；数值无来源。引擎**已定义**中性初始行（全 0 + `shortage_ratio 0/1` + `stress_level=NONE`） | **BLOCKED** | `economy.py:164-170,359-362`；`models_world.py:262-287`；OD-7 |
| **生态** | 初始生态区与正式 profile？ | 区数**已派生 = 12**（每聚落 1 区，`settlement_relation = working_name`；每区 3 行）；`EcologyProfile` 数值无来源 | **基数 DERIVED / 数值 BLOCKED** | `ecology.py:156-169,189-199`；OD-8 |
| **社会** | 组织形态与正式阈值？ | 形态只能由正式 `SocialProfile` 阈值表达；阈值仅在测试档且构造回落是静默的 | **BLOCKED** | `social.py:70-107,142,568-575`；OD-9 |
| **灾劫 profile** | 正式 profile 字段与来源？ | 字段已分类：引擎必需 3（`profile_id/tier/theme`）、世界法则 11、仅进 plan 无 adapter 消费 2（`production_disruption`/`institution_disruption`）、引擎不读 2（`targeting_rules`/`source_refs`）；数值无来源 | **字段已分类 / 数值 BLOCKED** | `tribulation.py:87-107,308,736-744`；OD-10 |
| **首个前兆时间** | = ？ | **tick 10_000_000（10 福地年，REGULAR 首个窗口）**，由引擎窗口语义派生；引擎**不存在**"窗口前导期"概念 | **DERIVED** | `tribulation.py:170-177,356,385-388,420-425` |

机读版：候选 JSON `per_domain_answers`（逐域 `answer_state` / `engine_evidence` / 规则或 OD）。

---

## 4. 派生规则（版本化、可独立复算）

| 规则 | 版本 | 输入 | 输出 | 舍入 / tie-break | RNG |
| --- | --- | --- | --- | --- | --- |
| `RA-ALLOC-001` | 1.0 | 群体人数、聚落目标人口 | (群体 × 聚落) 名额矩阵 | 列内最大余额 + 行边际最小偏离修复；余额降序→行下标升序；同代价→列下标升序 | 无 |
| `RA-COHORT-001` | 1.0 | `cohort_buckets`、`mortality_by_bucket`、人口总数 | 每 bucket 整数人数 | 存活曲线 `Π(1-q_k)` 归一后最大余额；下标升序 | 无 |
| `RA-MORTALITY-001` | 1.0（**待主人批准**） | owner 年龄带边界 + 每带年死亡概率 | 逐 bucket `mortality_by_bucket` | 分段常量展开 | 无 |
| `RA-TRIB-001` | 1.0 | 已批准周期 + 引擎窗口谓词 + max-tier | 首个 omen tick 与每 tier 首个窗口 | 精确整数倍 | 无 |
| `RA-STRUCT-001` | 1.0 | 已启用聚落集合 + 引擎 fail-closed 要求 | 必须提供的行集合基数 | 精确基数 | 无 |

`RA-COHORT-001` 的**输入**（正式 population profile）尚未批准 → 其输出保持 `BLOCKED`；
本候选只提供规则实现，不提供任何正式数值。
所有规则：无浮点（`Fraction`/整数）、无随机、无时间戳 → 输入相同即**逐字节相同**。

### 灾劫首个前兆（owner §20 → 已解决）

冻结引擎**没有**"窗口前导期 / 预警窗口"概念：`PRECURSOR`（前兆）阶段**始于**窗口 tick T，
`entered_tick = T`，`transition_tick = T + precursor_steps × 1e6`（向后延伸）。
因此"首个前兆时间"是**可派生**的，而不是需要主人拍一个年份：

```
REGULAR   首个窗口 = 10 福地年 → episode @ tick  10_000_000（PRECURSOR）
MAJOR     首个窗口 = 50 福地年 → episode @ tick  50_000_000（max-tier 压制 REGULAR）
CENTENNIAL首个窗口 = 100 福地年 → episode @ tick 100_000_000（max-tier 压制其余）
首个前兆（PRECURSOR_STARTED） = tick 10_000_000 = 10 福地年
tick 0 不存在任何 ACTIVE episode（冻结 driver 从不已 blessed_end_tick=0 调用）
```

**不存在的量**：任何"窗口前的静默前导期/预警提前量"。若主人想要 ≠10 福地年的首个前兆，
那不是数值裁决，而是**新的引擎能力**（当前 NOT_FOUND）。
仍需主人批准的是 `precursor_steps`（前兆持续时长，T 之后）等 profile 世界法则值。

---

## 5. 群体 × 聚落分配矩阵（双边际严格精确）

`RA-ALLOC-001 v1.0` 输出（`matrix_sha256 = 8dfe3471c1ff9d9c93646df18e4f55335cb93ca634c4afc96a17c86b5b28c457`）：

```
group,   MAIN-01,MAIN-02,MAIN-03,MAIN-04,SAT-01,SAT-02,SAT-03,SAT-04,SAT-05,SAT-06,SAT-07,SAT-08
GROUP_1,     666,    666,    666,    666,   167,   167,   167,   167,   167,   167,   167,   167
GROUP_2,     500,    500,    500,    500,   125,   125,   125,   125,   125,   125,   125,   125
GROUP_3,     417,    417,    417,    417,   104,   104,   104,   104,   104,   104,   104,   104
GROUP_4,     417,    417,    417,    417,   104,   104,   104,   104,   104,   104,   104,   104
```

```
行合计 = [4000, 3000, 2500, 2500]  （= 主人已批准群体名额）
列合计 = [2000,2000,2000,2000, 500,500,500,500,500,500,500,500]  （= 主人已批准每聚落人口）
总人口 = 12000
```

> **为什么规则是两阶段的**：一维最大余额（只锁行或只锁列）**无法**同时满足主人已批准的两组
> 约束 —— 例如"按容量比例逐行分配"会得到 `MAIN = 2001`（≠2000）。因此 `RA-ALLOC-001`
> 先用列内最大余额锁定列和，再用"列内搬运、最小偏离代价"修复行和；列内搬运不改变列和，
> 故双边际同时精确。这是**规则设计事实**，不是偏好。

---

## 6. bootstrap 实体计划与行基数

### 6.1 必需（引擎 fail-closed / 静默丢数据要求）

| 表 | 行数 | 来源 | 缺失后果 |
| --- | --- | --- | --- |
| `settlements` | 12 | owner（D-B2） | 四域全部无轴 |
| `population_groups` | `48 × cohort_buckets` | RA-STRUCT-001 + RA-COHORT-001（**基数 BLOCKED**） | 缺 bucket 行 = 静默丢人口（违 P_INV_12）；同 bucket 两行 = 重复计数 |
| `ecology_zones` / `ecology_state` / `ecology_feedback_state` | 12 / 12 / 12 | RA-STRUCT-001（每聚落 1 区，`settlement_relation = working_name`） | `EcologyZoneMissing`（fail-closed） |
| `settlement_social_state` / `social_feedback_state` | 12 / 12 | RA-STRUCT-001 | `IntegrityError`（与人口是否为 0 无关） |
| `tribulation_schedules` | 3 | 已批准 tier（10/50/100） | 无排期 → 灾劫永不触发 |
| `tribulation_profiles`（正式定义） | 3 | 每 tier 一套（**数值 BLOCKED**） | 内存 registry 才是引擎通道；DB 行为死读 |
| `resource_stocks` | `12 × R` | RA-STRUCT-001（**R BLOCKED**） | 不完整矩阵 → 经济引擎 `KeyError` |
| `economic_pressure_state` | `12 × C` | RA-STRUCT-001（**C BLOCKED**） | `EconomyStateInconsistent`（fail-closed） |
| `production_recipes` / `resource_nodes` | BLOCKED（可为 0 = 合法空转） | OD-5 / OD-6 | 无配方/无节点 = 无产出（不报错） |

### 6.2 **不需要**在 tick 0 物化（最小性，owner §14）

```
households / lineages / institutions      → SOCIAL 是唯一会自建根行的引擎（自愈）
tribulation_episodes / decisions / impact_plans / recovery_states /
  residual_changes / resource_succession_candidates → 运行中由引擎/协调器创建
ecological_regions · industries · persons · tribulations ·
  timeline_entries · cultural_elements    → 无任何 M2/M3 引擎读或写
production_state                          → 无行 = 该聚落×配方不生产（不报错）
tribulation_profiles（DB 行）              → 死读，仅影响 state hash 与展示
```

`households` **不预置**是**确定性后果**（非失败）：首个 SOCIAL step 会在
`tick = ctx.blessed_end_tick` 自建 household，因此 `household_id` / `updated_blessed_tick`
与"预置快照"不同，会改变后续 `world_state_hash`。此差异已登记为知情项。

`REGION_REF_NULL_EVERYWHERE`：生态区/聚落/资源节点的 `region_ref` 全部为 NULL，
**不创建** `ecological_regions` 行（该表无业务键，见 §10 U-3）。

---

## 7. 引擎硬约束（正式世界必须知情；只登记不改）

| # | 约束 | 依据 |
| --- | --- | --- |
| EC-1 | `precursor_steps >= 1`（=0 会触发同一步 `ep["id"]` KeyError） | `tribulation.py:426-433,439-441,472-475` |
| EC-2 | tick 0 不得存在 ACTIVE episode（`_tier_at_tick(...,0)` 会命中所有排期并取 CENTENNIAL） | `tribulation.py:170-177,356` |
| EC-3 | `migration_weights` 长度 ≥ 2：`_settlement_order` 对正式聚落名一律返回 1（12 聚落共享 index 1） | `population.py:149-150,370-371` |
| EC-4 | 每 `(species, settlement_ref)` 的 cohort 行必须**恰好**覆盖 `0..N-1` 各一行（DB 无唯一约束） | `population.py:140-146,289-292,344-346` |
| EC-5 | `population_capacity` 若为数值必须 **> 该聚落初始人口**，否则出生恒为 0（人口冻结） | `population.py:187-189,329-332` |
| EC-6 | `species_profile_ref` 不得使用 `DEMOGRAPHY_PROFILE_REF`（`"TEST_PROFILE_001"` 不是 registry key） | `population.py:40,116,241-252` |

EC-4/EC-5 是**bootstrap 义务**：DB 层没有约束兜底，物化器必须自行保证（本阶段只登记）。

---

## 8. 六个正式 profile registry（BOOTSTRAP CONFIGURATION）

现状：六个 registry **全部是引擎自声明的测试夹具**，且 `TribulationEngine` / `SocialEngine`
存在**静默回落**（`profiles or TEST_PROFILES` / `profile or TEST_SOCIAL_PROFILE`）。
主人已批准（D-C/D-C2）建立正式 registry 且**禁止生产路径回落**；本阶段只给出**字段级分类**。

| registry（替代对象） | 结构字段 | 世界法则字段（当前 BLOCKED） | 引擎强制 |
| --- | --- | --- | --- |
| `FORMAL_POPULATION_PROFILE_REGISTRY`（← `SPECIES_PROFILES`） | `species_id` | `cohort_buckets`、fertile 区间、`birth_rate`、`mortality_by_bucket`、`emigration_rate`、`migration_weights` | 无字段默认值；`mortality` 长度 == buckets；`migration_weights` 和 == 1 且长度 ≥ 2 |
| `FORMAL_RESOURCE_PROFILE_REGISTRY`（← `RESOURCE_PROFILES`） | `resource_id`、`semantic_version` | `quantity_scale`、`renewability`、`extractability`、`consumption_category`、`production_usability` | `quantity_scale > 0` |
| `FORMAL_ECONOMY_PROFILE_REGISTRY`（← `SPECIES_ECONOMY_PROFILES`） | `profile_id`、`semantic_version` | `per_capita_demand` | 键必须是资源 profile id |
| `FORMAL_ECOLOGY_PROFILE_REGISTRY`（← `ECOLOGY_PROFILES`） | `profile_id` | `recovery_rate/ceiling`、`sensitivity`、`pressure_weights`、`pop_pressure_per_person`、`renewable_regen_minor_per_full_quality`、`thresholds` | 权重键固定且和 == 1；`thresholds` 长度 3 严格递减；`0 < ceiling <= ECOLOGY_STATE_SCALE` |
| `FORMAL_SOCIAL_PROFILE_REGISTRY`（← `SOCIAL_PROFILES`，死代码） | `profile_id` | `formation_size`、`split_threshold`、`lineage_*`、`institution_*`、凝聚力三阈值、`pressure_weights`、`stress_thresholds`、三个 k | 权重键固定且和 == 1；`stress_thresholds` 长度 2 严格递增 |
| `FORMAL_TRIBULATION_PROFILE_REGISTRY`（← `TEST_PROFILES`） | `profile_id`、`tier`、`theme` | `intensity_min/max`、三类 steps、五个有 adapter 的风险项、`ecology_pressure`、`recovery_steps`、`succession_rules` | `tier` 必须命中 REGULAR/MAJOR/CENTENNIAL；`precursor_steps ≥ 1` |

附注（知情项，不改冻结语义）：
* `production_disruption` / `institution_disruption` 进入 plan 与 hash，但**无 adapter 消费**（今日零领域效果）。
* `targeting_rules` / `source_refs` 引擎不读（实际目标为 RNG 抽聚落 working_name）。

---

## 9. MINIMUM_REMAINING_OWNER_DECISIONS（收敛后的最小集）

> 目标（owner §27）：不给主人一百多个字段。以下 **10 项** 是"无法从现有资料推出、
> 且确实阻塞正式物化"的**全部**剩余决策；其余数值一律由规则派生或为引擎中性常量。

| # | 决策 | 阻塞什么 | 为什么阻塞 | 可选项 |
| --- | --- | --- | --- | --- |
| OD-1 | **S-2 异人种族组合** | `population_groups.species`、正式 population registry 键集合 | 名额已批准但族**身份**未批准；`species` NOT NULL 且未知即 fail-closed | 批准 OPTION_A/B/C 之一；或直接给 4 个 species id |
| OD-2 | **S-4/S-5/S-6/S-7/S-8/S-9 世界层内容** | S-4..S-9 | canon 11 号文档中除 S-1/S-3/S-10 外全部仍 PENDING_APPROVAL | 逐项批准/变更/否决；对不存在的机制明确"本轮不表达" |
| OD-3 | **人口世界法则数值** | `cohort_buckets`、fertile 区间、`birth_rate`、`mortality_by_bucket`、`emigration_rate`、`migration_weights` | 引擎无默认值，缺则 fail-closed；本候选提供压缩机制 `RA-MORTALITY-001`（按年龄带，而非 40 个逐 bucket 值） | 每族 6 组数（可比逐 bucket 少一个数量级）；或一个 baseline + 每族偏差 |
| OD-4 | **每聚落人口容量法则** | `settlements.population_capacity` | 数值 == 初始人口 → 出生恒为 0（冻结陷阱，EC-5） | (a) NULL = 无容量法则（中性）；(b) 容量数值（须 > 初始人口） |
| OD-5 | **S-4 产业** | `production_recipes` / `production_state` | 无批准清单即不得代填 | 批准草案骨架 + 配方数值；或本轮不设产业 |
| OD-6 | **资源集合与正式资源 profile** | `FORMAL_RESOURCE_PROFILE_REGISTRY`、`resource_nodes`、`resource_stocks`、`consumption_category` | S-5 未批准；库存矩阵不完整 → KeyError | 批准资源清单 + profile 数值；或本轮不设资源 |
| OD-7 | **初始经济状态** | 初始库存、`per_capita_demand`、`economic_pressure_state` 行 | 缺行 → fail-closed | 给出初始库存与人均需求；或以 0 库存 + 中性 pressure 行起步（会立即进入短缺路径） |
| OD-8 | **生态世界法则数值** | 正式 `EcologyProfile` 全部数值 | 区数已派生为 12；profile 数值无来源 | 批准数值（全局或每区）；或明确不启用生态派生 |
| OD-9 | **社会世界法则数值** | 正式 `SocialProfile` 全部阈值 | 阈值仅存在于测试档，且构造回落是静默的 | 批准正式阈值；或明确不启用社会派生 |
| OD-10 | **灾劫正式 profile + 静默回落授权** | `FORMAL_TRIBULATION_PROFILE_REGISTRY`、S-10 `mode` | 周期与首个前兆已解决；profile 数值与 `profiles or TEST_PROFILES` 仍待裁决 | 批准每 tier 一套数值 + 授权去除静默回落 |

> **中性值需主人知悉（`NEUTRAL_REQUIRES_OWNER_ACK`，31 处）**：候选把一批"引擎尺度边界 /
> 无退化初始态"的值标为 `ENGINE_NEUTRAL_CONSTANT`，并逐条写明 `neutrality_basis`
> （例如 `settlements.state = ACTIVE`、`region_ref = NULL`、`working_name = <slot>-WORKING`）。
> 它们不是世界法则发明，但仍是主人的可改项。

---

## 10. UNRESOLVED（**不阻塞**物化，登记备查）

| # | 项 | 结论 |
| --- | --- | --- |
| U-1 | S-6 荒兽/异兽层级 | 冻结引擎无对应实体/规则（NOT_FOUND）；只影响叙事层 |
| U-2 | S-8 基础设施 | 引擎无基础设施表；如需表达，可复用 `institutions`（SOCIAL 自建） |
| U-3 | `ecological_regions` 无业务键 | 该表只有自增 `id`，无 `region_id`；而 `settlements.region_ref` / `ecology_zones.region_ref` 是软字符串引用 → 确定性 `region_ref` 无法以 insert-only 表达。本候选以 `REGION_REF_NULL_EVERYWHERE` 规避（不创建该表行），故不阻塞；若主人将来要区域层，需先裁决业务键（或新增迁移） |
| U-4 | 迁移权重无法按聚落区分 | `_settlement_order` 对正式聚落名一律返回 1（EC-3），12 聚落共享 index 1 —— 冻结引擎既有耦合，本阶段只登记不改 |

---

## 11. 审计更正（M6C.0 → M6C.1）

| 目标 | 原文 | 更正 | 证据 |
| --- | --- | --- | --- |
| `docs/m6c_minimal_bootstrap_canon_audit.md:338`（D-B3） | `occupation_group`/`household_stats`"参与社会派生" | **不成立**：`occupation_group` 无任何引擎读取（WRITE_ONLY，只影响 snapshot 行序与 `world_state_hash`）；`household_stats` 零读零写且不在 snapshot 投影内 → 二者**不构成阻塞项** | `snapshot.py:88-91,263-264`；`state_hash.py:40,66`；`economy.py:133-136,188-211`；`social.py:157-200` |

该更正的直接收益：**主人不需要为职业结构与户统计口径做任何裁决**（原 D-B3 阻塞项取消）。

---

## 12. 本阶段明确未做的事（owner §26/§28）

```
未实现 materializer          未激活正式世界        未消费正式 Seed
未读正式 Seed 原值           未写正式库            未部署 live
未修改任何冻结 M2/M3 语义    未把测试 profile 改名当正式 profile
未接任何测试 registry 到正式路径
未使用 RNG / 未使用 hash(seed) 生成世界内容
未产生 SNAPSHOT_V1（本文件是 CANDIDATE，且校验器禁止 SNAPSHOT_V1.* 存在）
```

---

## 13. 可复算与校验（如何独立验证本候选）

```powershell
python scripts\build_snapshot_candidate.py            # 生成 JSON 候选（确定性）
python scripts\build_snapshot_candidate.py --check    # 逐字节复现检查（无漂移）
python scripts\validate_snapshot_candidate.py         # 独立校验（schema/来源/合计/禁测/禁物化/红线）
```

校验器执行 6 类独立检查：schema 与 header 旗标 → 来源完整性（`UNATTRIBUTED_NUMBER`
一律失败）→ BLOCKED 项必须挂在已声明的 OD 上 → 分配矩阵**独立复算**（重跑
`RA-ALLOC-001` 并比对规范化文本与 SHA256）→ 合计（总人口/行/列）→ 禁测试夹具 /
禁 materializer / 禁止生产变更能力 / 正式世界红线。

```
attributed_nodes        = 109
owner_approved_nodes    =  19
derived_nodes           =  20
neutral_nodes           =  31
blocked_nodes           =  19
candidate_sha256        = 0a7466c7054c9d51f6a069f94c325e87c20ad0f1f341b806014961c461d62f03
matrix_sha256           = 8dfe3471c1ff9d9c93646df18e4f55335cb93ca634c4afc96a17c86b5b28c457
```
