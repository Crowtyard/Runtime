# M6C1B — OWNER DECISION PACKET & AUTHORITY HARDENING

```
STATUS                     = AWAITING_OWNER_DECISIONS
SNAPSHOT_V1_CANDIDATE      = ACCEPTED_AS_CANDIDATE
SNAPSHOT_V1                = NOT_APPROVED
MATERIALIZER_ALLOWED       = FALSE
FORMAL_ACTIVATION_ALLOWED  = FALSE
FORMAL_WORLD_SEED_CONSUMED = FALSE
OWNER_DECISION_COUNT       = 9（上限 10）
S1_S10_UNTRACKED_BLOCKERS  = 0
MACHINE_READABLE           = docs/world_creation/M6C1B_OWNER_DECISION_PACKET.json
```

> 本阶段**不实现 Materializer、不激活世界、不消费 Seed、不改正式库**。
> 本文件只做两件事：**（1）权威库 hardening 与审计**；**（2）把剩余阻塞收敛成 9 个决策**。

---

## PART 0 — 权威库裁决与硬化（owner §2–§6）

### 0.1 实测结果（只读）

```
AUTHORITATIVE_DB_RESOLUTION = PASS
contract   = <plugin_data>/runtime_state/authoritative_db.json（Runtime 写出：plugin_shell/runtime_host.py:212-225）
resolved   = C:\Users\<user>\.astrbot_launcher\instances\<instance-id>\core\data\plugin_data\
             astrbot_plugin_blessed_land_runtime\blessed_land.sqlite
MARKER_CHECKSUM_MATCH       = True
FORMAL_DB_SHA256            = 7754b1d4658ea94ce509ae7fb7c06c33c44f98782021b3708e6f29ce69102837（= M6 基线）
FORMAL_WORLD_RUNTIME_ROWS   = 0
FORMAL_WORLD_STATUS         = NOT_ACTIVATED
CURRENT_BLESSED_TICK        = NULL
ALEMBIC_HEAD                = a9d4f2b7c1e8        INTEGRITY = ok
CANDIDATE_DB_COUNT          = 2
NON_AUTHORITATIVE_DB_DETECTED = TRUE（1 个）
   └ D:\MY SELF\AstrBot\data\plugin_data\...\blessed_land.sqlite
     world_runtime = 1 | sha256 e0c5d32f…8203 | consulted_for_redline = False
STALE_DB_FALSE_POSITIVE     = 0
FALSE_POSITIVE_ACTIVATED    = False
```

**定性**：`LEGACY_DB_PRESERVED = TRUE`、`LEGACY_DB_AUTHORITATIVE = FALSE`。
**禁止**删除/覆盖/迁移该副本（保留用于 forensic / historical diagnosis）；正式代码、测试、红线审计**一律不得**再通过硬编码路径把它当正式库。

### 0.2 硬化内容（新增，只读能力）

| 交付 | 作用 |
| --- | --- |
| `tests/formal_db.py`（扩展） | `resolve_authoritative_db()` / `redline_report()` / `discover_dbs()`：权威**只能**来自 marker；无 marker 有候选 → `AMBIGUOUS`；checksum 不符 / 路径越界 / 显式覆盖与 marker 冲突 → `AMBIGUOUS` → `AuthoritativeDbAmbiguous`（FAIL CLOSED） |
| `scripts/audit_authoritative_db.py` | 只读审计 CLI；`--plugin-data-dir` **必须显式给出**（脚本内无任何硬编码路径）；退出码 0/PASS、2/AMBIGUOUS、3/ABSENT |
| `tests/test_m6c1b_authoritative_db_guard.py` | 19 项守卫：stale 假阳性 0、AMBIGUOUS FAIL CLOSED、checksum 冲突、路径越界、explicit 冲突、硬编码路径审计封闭 |

**禁止的选择方式**（已由测试钉住）：选第一个 / 选最新 mtime / 选固定路径 → 一律不允许；无法唯一确定即 `AMBIGUOUS` + FAIL CLOSED，**不得**执行 activation / materialization / formal mutation。

### 0.3 硬编码路径审计（§4）

```
HARDCODED_PATH_FINDINGS                    = 4（全部为文档/诊断脚本，均**无 DB 能力**）
HARDCODED_PATH_FINDINGS_WITH_DB_CAPABILITY = 0
生产目录（services/ plugin_shell/ database/）命中 = 0
```

| 文件 | 性质 |
| --- | --- |
| `scripts/isolated_astrbot_marker_acceptance.py` | M5 期 live 接受性辅助（探测运行中的 AstrBot core）；不打开 DB |
| `scripts/m5_real_astrbot_smoke.py` | M5 期 live 冒烟辅助；不打开 DB |
| `tests/test_query_isolation.py` | M5 隔离测试（对 Private Companion 源码做 checksum）；不打开 DB |
| `scripts/build_snapshot_candidate.py` | M6C.1 候选元数据：记录权威路径**模式**与 stale 副本定性（文档字符串）；经校验器证明无 DB 能力 |

任何**新增**的硬编码路径，或任何**具备 DB 能力**的硬编码路径，都会让守卫测试失败。

---

## PART 1 — 规则裁决落地（owner §0）

```
RA-ALLOC-001 v1.0 = APPROVED_BOOTSTRAP_DERIVATION
   integer-only ✔  no RNG ✔  deterministic ✔  fixed tie-break ✔
   exact row marginals ✔（4000/3000/2500/2500）
   exact column marginals ✔（MAIN 2000×4 / SAT 500×8）
   independently reproducible ✔（matrix_sha256 = 8dfe3471c1ff9d9c93646df18e4f55335cb93ca634c4afc96a17c86b5b28c457）
RA-TRIB-001       = APPROVED_BOOTSTRAP_DERIVATION（FIRST_OMEN = year 10 = tick 10_000_000；
                    依据冻结 omen phase 从 tier window T 开始、无 pre-T lead；不得重新解释为新灾劫规则）
RA-COHORT-001     = CANDIDATE_ONLY（待 owner 审批 cohort buckets / mortality-survival values / derived ratios）
RA-MORTALITY-001  = PENDING_OWNER_DECISION
RA-STRUCT-001     = CANDIDATE_ONLY_PENDING_EXPLICIT_REVIEW → 见 OD-8
```

**既有 owner 决议，本期不再列为 OD**：

```
PRODUCTION_TEST_PROFILE_FALLBACK = FORBIDDEN
FORMAL_PROFILE_MISSING_BEHAVIOR  = FAIL_CLOSED
REMOVE_PRODUCTION_TEST_PROFILE_FALLBACK = TRUE
FORMAL_PROFILE_REGISTRY（五/六域生产 registry）= 已授权；本轮只决定 profile content
OCCUPATION_BOOTSTRAP_OWNER_DECISION = NOT_REQUIRED   （occupation_group 无 frozen engine read）
HOUSEHOLD_BOOTSTRAP_OWNER_DECISION  = NOT_REQUIRED   （household_stats 无 authoritative read/write，不在 projection）
```

---

## PART 2 — 中性值重分类（owner §7–§9）

```
TECHNICAL_NEUTRAL_COUNT = 3 字段（24 个已声明值实例）
DYNAMIC_NEUTRAL_COUNT   = 6 状态族
```

### A. TECHNICAL_NEUTRAL（`AUTO_ACK_ELIGIBLE = TRUE`；本轮**不改** SNAPSHOT_V1 状态）

| FIELD | VALUE | ENGINE_READ_COUNT | WHY_NON_DYNAMIC |
| --- | --- | --- | --- |
| `settlements.state` | `ACTIVE` | **0** | 引擎只经 `working_name` / `population_capacity` 消费 settlements 行；引擎中 `state` 键的读取全部属于 `resource_nodes`（`resource.py:220-262`）与 `households`/`institutions`（`social.py:219,499,540`）。仅影响 snapshot 序列化与 state hash |
| `settlements.region_ref` | `NULL` | **0** | 引擎中 `region_ref` 的读取**全部**针对 `resource_nodes`（`resource.py:132,151,152,168`）、`ecology_zones`（`ecology.py:210`）、`tribulations`（`tribulation.py:553,560,634,648`），**无一处**读 settlements 行（settlements 消费键集合 = `{working_name, population_capacity, species}`）；在 `REGION_REF_NULL_EVERYWHERE` + tick=0 无 resource_nodes 前提下不产生任何分支。**REOPEN_TRIGGER**：若 OD-3 批准任何非空 `region_ref` 节点，本字段升级为 DYNAMIC |
| `settlements.settlement_type` | `MAIN`/`SATELLITE` | **0** | 无引擎读取（仅 snapshot/state_hash 可见）；值本身已由 owner D-B2 批准 |

### B. DYNAMIC_NEUTRAL（会被 frozen engine 读取并影响轨迹 → **必须 owner 批准**：见 OD-9）

| 状态族 | 引擎消费者 | 引擎默认是否中性 | 陷阱 |
| --- | --- | --- | --- |
| `ecology_state`（12 行） | `ecology.py`（quality / level_of / regeneration） | **否** | 列默认 `habitat_quality = 0` = 最差质量（CRITICAL），不是中性起点 |
| `ecology_feedback_state`（12） | RESOURCE/DEMOGRAPHY（下一 committed step） | 是 | 默认比值 1/1、stress NONE |
| `settlement_social_state`（12） | `social.py` | 是 | 默认 stress 0、cohesion/stability 1_000_000 |
| `social_feedback_state`（12） | DEMOGRAPHY（下一 committed step） | 是 | 默认全 1/1 |
| `economic_pressure_state`（12×C） | `economy.py` | 是 | 默认全 0、ratio 0/1、stress NONE |
| `resource_stocks`（12×R） | `resource.py` + `economy.py` | **否** | `quantity = 0` 且无开采 → 经济永久零产出（dead economy），并经 feedback 影响人口 |

**不得**因为"默认值 / 中性值 / 初始值"三个词之一就绕过 owner 审批（owner §9）。

---

## PART 3 — 九个 Owner Decision（每个 ≤3 候选 + CUSTOM）

> 候选来源严格限定：`LOCAL_CANON` / `APPROVED_LOCAL_DESIGN` / `OWNER_ALREADY_APPROVED_FACTS` /
> `FROZEN_ENGINE_NEUTRAL_CONSTRAINT` / `DETERMINISTIC_DERIVATION_FROM_APPROVED_FACTS`。
> **禁止**：TEST_PROFILES、synthetic fixtures、常识猜测、模型自行世界观创作。

### OD-1 — S-2 异人种族身份（species 字符串）

```
WHY_BLOCKING   = population_groups.species 为 NOT NULL 且必须命中正式 species profile registry；
                 未知 species → DemographyProfileUnconfigured（fail-closed）。没有 species 就无法物化任何人口行
FROZEN_CONSUMER= population.py:166-172；economy.py:107-131
SCHEMA_FIELDS  = population_groups.species (String(32), NOT NULL)；FORMAL_POPULATION_PROFILE_REGISTRY 键集合
UNIT           = NONE（标识符字符串）
IDENTITY_CANON = PRESENT（不是 ABSENT；主人应**确认**已有 canon 名，而不是发明新名）
```

**EXISTING_APPROVED_CONSTRAINTS**：WS-0502【APPROVED_WORLD_SEED_DESIGN】「毛民、石人、鲛人、菇人（**主人圈定**）」（`world_bible/05:6-7`）；WS-0503 同名次配「约 4,000 ｜ 约 3,000 ｜ 约 2,500 ｜ 约 2,500」（`05:18-19`）；D-B5 名额已批准；`world_seed/05_species_baseline.json:5,9,13,17` 声明英文名 `Hairy Men / Rockmen / Mermen / Mushroommen`（`population_share: null`）；Runtime 既有正式名约定见 `feedback.py:11-12`。

> ⚠ **OPTION_A/B/C 不适用**：三选项都不等于四族集合（A={人族,小人,毛民,石人}、B 含羽民、C 含墨人）。
> ⚠ **算术张力**：四族名额合计恰为 12,000，而 WS-0503 括注「余量人族/其他」并在 seed 中另列「人族居民」。
> 若 D-B5 全部占满，则人族 = 0（候选 A 的后果，须主人确认）。

| 候选 | VALUE | SOURCE | LONG_TERM_EFFECT |
| --- | --- | --- | --- |
| **A** | `GROUP_1=Hairy Men(毛民,4000)`、`GROUP_2=Rockmen(石人,3000)`、`GROUP_3=Mermen(鲛人,2500)`、`GROUP_4=Mushroommen(菇人,2500)`；人族=0（不建行） | OWNER_ALREADY_APPROVED_FACTS + seed 名称 | 与已批准名额逐位对齐；人族 tick=0 不存在（未来加人族需改配额并重算 RA-ALLOC-001） |
| **B** | 四族名同 A，但从 12,000 中划一部分给人族 | WS-0503 括注 | **推翻 D-B5 数字** → RA-ALLOC-001 输入变化 → 矩阵与 digest 全部改变 |
| **C** | 用中文规范名（毛民/石人/鲛人/菇人）作 registry key 与 DB 值 | seed `canonical_name` | 与 Runtime 既有英文正式名约定不一致，需同步改 registry 键与 feedback 对照表 |

```
RECOMMENDED_NEUTRAL_CANDIDATE = A（不引入新事实，只把既定 canon 名与已批准名额连起来）
OWNER_MUST_CHOOSE = A / B / C / CUSTOM
```

### OD-2 — 人口世界法则（年龄结构 / 生命表 / 繁衍 / 迁移 / 聚落容量）

```
WHY_BLOCKING   = SpeciesDemographyProfile 无任何默认值，缺 profile 即 fail-closed；
                 cohort 行必须覆盖 0..N-1 每个 bucket，缺行静默丢人口（违 P_INV_12）
FROZEN_CONSUMER= population.py:63-97（结构）、:307（逐 bucket 死亡率）、:325-338（出生）、
                 :361-367（迁出）、:370-371（迁移权重）、:187-189,:329-332（容量收缩）
SCHEMA_FIELDS  = population_groups.age_cohort / species_profile_ref / demography_version；
                 settlements.population_capacity
UNIT           = cohort bucket 宽 = 1 福地年；birth_rate = /fer­tile 人/福地年（Fraction）；
                 mortality_by_bucket = 每年死亡概率（Fraction 0..1）；emigration_rate = /福地年；
                 migration_weights = 无量纲（和=1，长度≥2，EC-3）；population_capacity = 人
```

**EXISTING_APPROVED_CONSTRAINTS**：总量 12000 / 四族名额 / 每聚落 2000·500 已批准；引擎结构（bucket 宽 1 福地年、bucket 0 = 出生、末位开区间、`mortality` 长度 == `cohort_buckets`）；canon 唯一量化寿命 = 石人「寿千余（有载）」（`world_bible/05:11`）；石人繁衍机制 = 无雌性/分裂繁殖（同处）→ **冻结引擎的性别化生育模型无法表达**；canon 明令 UNKNOWN 禁止自行补值（`05:16`、`13_known_unknowns.md:3`、11 号:3）。

**canon NOT_FOUND（全部）**：生育区间、出生率、死亡率曲线、婴儿夭折、迁出/迁入率、户均子女、年龄占比 —— 且 canon 明确**拒绝**预设（"不预设人口 120 年必须到多少"）。

| 候选 | VALUE | SOURCE | LONG_TERM_EFFECT |
| --- | --- | --- | --- |
| **A** | 四族共用同一 profile：owner 给 寿命上限 L（→ `cohort_buckets = L+1`）、生育区间、`birth_rate`、`emigration_rate`、`migration_weights(≥2, 和=1)`、年龄带死亡概率 | FROZEN_ENGINE_NEUTRAL_CONSTRAINT + OWNER 数值 | 最简单；石人 canon 方向（长寿/分裂繁殖）无法表达，四族人口学同质 |
| **B** | 共享速率 + 每族寿命上限（`cohort_buckets` 各异；石人给更长上限） | LOCAL_CANON（石人寿千余，作**方向**）+ OWNER 速率 | 行数 = 12 × Σ_species(L_s+1)；石人可达千级 bucket → 该族 cohort 行数 = 12×(L+1)，性能与覆盖成本上升 |
| **C** | 四族完全独立 profile（速率与寿命各自给） | OWNER 数值 | 最大保真；owner 需给 4×6 组数值；引擎无需改动 |

**子决策**：① 石人繁衍语义（近似声明不符 / `birth_rate=0` 人口只减 / CUSTOM）；② `settlements.population_capacity` —— 与"每聚落人口"**是不同字段**：`room = max(capacity − total_after, 0)/capacity` 作出生倍率，`NULL` → 倍率 1（无约束）；**陷阱：capacity == 初始人口 → 出生恒为 0（人口冻结）**。

**分布预览（`PREVIEW_INPUT_PLACEHOLDER_NOT_A_CANDIDATE`：仅演示 RA-COHORT-001 机制，所用死亡率是占位输入，不是数值提案）**：

| 情形 | N | cohort 行数(48×N) | <15 岁 | 15–64 | ≥65 |
| --- | --- | --- | --- | --- | --- |
| ceiling 40y, q=1/100 | 41 | 1,968 | 0.415 | 0.585 | 0.000（截断：≥40 全部并入末位 bucket） |
| ceiling 100y, q=1/100 | 101 | 4,848 | 0.217 | 0.537 | 0.246 |
| ceiling 100y, q=1/200 | 101 | 4,848 | 0.180 | 0.519 | 0.301 |
| ceiling 1000y, q=1/1000 | 1001 | 48,048 | 0.022 | 0.075 | 0.903（极老年龄结构） |

```
RULES_NEEDING_RATIFICATION = RA-COHORT-001（CANDIDATE_ONLY）、RA-MORTALITY-001（PENDING）
RECOMMENDED_NEUTRAL_CANDIDATE = 无（canon 对全部速率 NOT_FOUND 且禁止代填）
OWNER_MUST_CHOOSE = A / B / C / CUSTOM
```

### OD-3 — 资源集合、节点与正式 resource profile（S-5）

```
WHY_BLOCKING   = resource_stocks 必须是完整矩阵（聚落 × 资源）；缺行 → 经济引擎 KeyError（非契约化异常）
FROZEN_CONSUMER= economy.py:297-305（矩阵查表）、:276-294（消费类别）；resource.py:138-142（无节点即无开采）
SCHEMA_FIELDS  = resource_profiles(resource_id/unit/quantity_scale/renewability/extractability/
                 consumption_category/production_usability)；resource_nodes(kind/state/
                 resource_profile_ref/settlement_relation/remaining_reserve/extraction_capacity/
                 reserve_ceiling_minor)；resource_stocks.quantity
UNIT           = minor units（1 canonical unit = quantity_scale minor units）；
                 extraction_capacity = minor units/福地年；remaining_reserve = minor units
```

**EXISTING_APPROVED_CONSTRAINTS**：`node_types` 8 类已批准（灵田 / 药园·药材点 / 果园 / 矿脉·石材点 / 水源·水产点 / 林产·采集点 / 菌类点 / 特殊灵性资源点）`world_seed/09:5-7`；8 态状态机（WS-0703 CONFIRMED_STATIC_CANON）；WS-0702 资源不能无限生成；canon 明示"资源节点实例 0；储量/坐标/状态全 UNKNOWN；未确认资源数量不得伪造"（`09:14-17`）；S-5 建议清单 PENDING_APPROVAL。

| 候选 | VALUE | SOURCE | LONG_TERM_EFFECT |
| --- | --- | --- | --- |
| **A** | 不设资源：profiles=0、nodes=0；`resource_stocks` 仍建完整矩阵但 `quantity=0` | FROZEN_ENGINE_NEUTRAL_CONSTRAINT | RESOURCE 合法空转；经济零产出 → 短缺路径（须与 OD-9 一起接受） |
| **B** | 8 类各 1 个正式 profile（owner 给 unit/scale/renewability/category）+ 每聚落 1 个基础节点（12 节点） | LOCAL_CANON（类型已批准）+ OWNER 数值 | 最小非空资源生态；每聚落至少一条开采线，库存可被补充 |
| **C** | owner 指定完整资源清单与每节点储量/开采容量 | OWNER 数值 | 最大保真；owner 需给 节点数×(kind,profile,reserve,capacity) |

```
RECOMMENDED_NEUTRAL_CANDIDATE = 无（canon 对一切资源数量/储量 NOT_FOUND）；A 是唯一零发明选项但对经济是硬约束
OWNER_MUST_CHOOSE = A / B / C / CUSTOM
```

### OD-4 — 初始经济状态与产业配方（S-4 + D-B7）

```
WHY_BLOCKING   = resource_stocks / economic_pressure_state 缺行即 fail-closed；production_recipes 决定是否有产出
FROZEN_CONSUMER= economy.py:164-170、:188-211（batches = min(容量进位, 输入库存, 劳动力)）、:359-362、:266-294
SCHEMA_FIELDS  = production_recipes(recipe_id/input_resource_ref/input_qty_minor/output_resource_ref/
                 output_qty_minor/capacity_batches_per_year/labor_per_batch/loss_num/loss_den)；
                 economic_pressure_state 全字段；resource_stocks.quantity
UNIT           = input/output_qty_minor = minor units/批；capacity_batches_per_year = 批/福地年；
                 labor_per_batch = 人/批（0 = 无劳动力约束）；per_capita_demand = canonical units/人/福地年
```

**EXISTING_APPROVED_CONSTRAINTS**：`industry_sectors` 7 类已批准（农业 / 采集 / 手工业 / 市场 / 交通 / 资源生产 / 外界物品输入）`world_seed/08:5-7`；生产链 `RESOURCE_NODE → 采/种 → 加工 → 运输 → 储存 → 市场 → 消费/培育/储备`（WS-0701）；`USE ≠ MANUFACTURE`（不得假设可复现现代工业链）；货币形态 UNKNOWN，canon 默认「物/劳务交换 + 记账」（不引入元石/仙元石）；canon NOT_FOUND：配方、产能、劳动力、人均需求、初始库存、价格、仓储容量（"buffer/储备年限"策略在 canon 中**不存在**）。

| 候选 | VALUE | SOURCE | LONG_TERM_EFFECT |
| --- | --- | --- | --- |
| **A** | 无初始产业：recipes=0、无 `production_state` 行（不生产、不报错）；pressure 行用引擎默认中性值；库存 0 | FROZEN_ENGINE_NEUTRAL_CONSTRAINT | 零产出世界 → 立刻进入短缺路径（feedback 影响人口）；仅当 OD-3=A 或 owner 明示接受时成立 |
| **B** | 按 7 个已批准 sector 各 1 条基础配方（owner 给 in/out/qty/capacity/labor/loss），库存按 owner 给的缓冲年限起步 | LOCAL_CANON（sectors/链条已批准）+ OWNER 数值 | 最小自洽经济；产量受节点与劳动力双重限制 |
| **C** | owner 指定完整配方表与每聚落初始库存绝对值 | OWNER 数值 | 最大控制力；owner 需填 配方数 + 12×R 个库存数 |

```
RECOMMENDED_NEUTRAL_CANDIDATE = 无：canon 对全部经济数量 NOT_FOUND，且引擎没有"经济中性初始态"的正式定义
                                （列默认 0 会把世界推入短缺路径）
OWNER_MUST_CHOOSE = A / B / C / CUSTOM
```

### OD-5 — 生态区与正式 EcologyProfile（D-B8）

```
WHY_BLOCKING   = 每区必须有 ecology_zones + ecology_state + ecology_feedback_state 三行，缺一即 EcologyZoneMissing
FROZEN_CONSUMER= ecology.py:189-199（三行完整性）、:254-290（压力权重/再生/阈值 level_of）
SCHEMA_FIELDS  = ecology_zones(zone_id/region_ref/settlement_relation/profile_ref)；
                 ecology_state(habitat_quality/regeneration_capacity/ecological_stress/*_pressure/carry/min-max)；
                 ecology_feedback_state(比值字段)
UNIT           = quality/stress/pressure ∈ [0, ECOLOGY_STATE_SCALE = 1_000_000]；
                 renewable_regen_minor_per_full_quality = minor units/福地年；
                 pop_pressure_per_person = minor units/人；thresholds 长度 3 严格递减
```

**EXISTING_APPROVED_CONSTRAINTS**：11 类生态区已批准（`mountain / forest / lake / river-stream / wetland / grassland / fields(灵田) / medicine_garden(药园) / orchard / resource_zones / settlement_ecology`）`world_seed/10:5-7`（CONFIRMED_STATIC_CANON）；状态字段名 8 个（WS-0801 APPROVED_WORLD_SEED）；WS-0805 承载力为 PROVISIONAL_DESIGN 且**无数值**；**`carrying_capacity` 的实际公式消费 = 无任何冻结引擎读取**（仅 snapshot/state_hash 可见）→ 与 EcologyProfile 数值无关；canon NOT_FOUND：一切生态数值。

| 候选 | VALUE | SOURCE | LONG_TERM_EFFECT |
| --- | --- | --- | --- |
| **A** | 12 区（每聚落 1 区，`settlement_relation = working_name`）；profile 数值由 owner 给；不建 `ecological_regions` 行（`carrying_capacity` 不设） | FROZEN_ENGINE_NEUTRAL_CONSTRAINT（区数由 fail-closed 需求派生）+ OWNER 数值 | 满足完整性；轨迹由 owner 数值决定 |
| **B** | 按 11 个 canon zone TYPES 建模（或按 8 个 regional_band_slots） | LOCAL_CANON（类型已批准） | 区数 > 12 → ecology_* 三表行数同步放大；需额外 区↔聚落 映射（`settlement_relation` 为单值） |
| **C** | owner 指定区集合与每区 profile 数值 | OWNER 数值 | 最大控制力 |

```
RECOMMENDED_NEUTRAL_CANDIDATE = 结构上推荐 A 的 12 区基数（引擎强制）；数值无中性候选
OWNER_MUST_CHOOSE = A / B / C / CUSTOM
```

### OD-6 — 正式社会阈值（S-7 + D-B9）

```
WHY_BLOCKING   = 每聚落必须有 settlement_social_state + social_feedback_state（缺行即 IntegrityError，
                 与人口是否为 0 无关）；户/宗族/机构的形成与分化全部由 SocialProfile 阈值驱动
FROZEN_CONSUMER= social.py:267-299（formation_size 形成户）、:300-345（split_threshold 拆分）、
                 :499-540（institution_found_pop 成立/解散）、:651-652（stress_thresholds）、:76-89（字段）
SCHEMA_FIELDS  = SocialProfile 全字段（formation_size / split_threshold / lineage_* /
                 institution_found_pop / institution_dissolve_pop / institution_*_cohesion /
                 pressure_weights / stress_thresholds / migration_modifier_k /
                 fertility_context_k / social_support_k）
UNIT           = 户规模/阈值/人口门槛 = 人或户（整数）；cohesion 与 stress_thresholds ∈ [0, SOCIAL_STATE_SCALE]；
                 pressure_weights 无量纲（和=1，键固定 {economy,ecology,mobility}）；k 为无量纲 Fraction
```

**EXISTING_APPROVED_CONSTRAINTS**：WS-0601/0603 自治原则（CONFIRMED_STATIC_CANON）；WS-0602 组织形态**存在**（家庭/村落/工坊/资源组织/运输/市场/仓储/学徒/公共事务；当前不建完整国家官僚体系）；WS-0608 允许家庭形成/代际/迁居（APPROVED_DESIGN）；WS-0406 聚落与 WS-0402 神社核心；机构 9 项候选与管理层为 PROVISIONAL_DESIGN（不写 Canon）；canon NOT_FOUND：户规模数值、形成/分化阈值、凝聚力数值、迁移权重数值（现存阈值只在 `TEST_SOCIAL_PROFILE`，TEST_FIXTURE_ONLY）。

| 候选 | VALUE | SOURCE | LONG_TERM_EFFECT |
| --- | --- | --- | --- |
| **A** | owner 给正式阈值集合（户规模、拆分阈值、机构门槛、凝聚力三档、压力权重、stress 阈值、三个 k） | OWNER 数值（结构受引擎约束） | 社会演化按 owner 设定展开；阈值决定 household/lineage/institution 产出节奏 |
| **B** | 阈值按聚落人口确定性派生（如 `formation_size` 由户规模政策 + 聚落人口推导），作为**新派生规则**提交 owner 批准 | DETERMINISTIC_DERIVATION_FROM_APPROVED_FACTS（需 owner 先批准规则） | owner 只需给少量政策参数；代价是新增一条需版本化、可复算的规则 |
| **C** | 明确「正式世界不使用社会阈值」= 不启用社会派生（仅建 state/feedback 行满足 fail-closed） | OWNER 决议 | household/lineage/institution 永不产生 → 社会层长期空转；人口仍演化（社会反馈保持中性 1/1） |

```
RECOMMENDED_NEUTRAL_CANDIDATE = 无中性数值；若 owner 要零发明且不启用该域，C 是唯一自洽选项（须明示接受空转）
OWNER_MUST_CHOOSE = A / B / C / CUSTOM
```

### OD-7 — 正式灾劫 profile 数值（S-10 剩余部分）

```
WHY_BLOCKING   = 无匹配 tier 的正式 profile → 该 tier 静默不触发；profile 数值决定灾劫强度与后果
                 （周期与首个前兆**已解决，不在本项**）
FROZEN_CONSUMER= tribulation.py:87-107（结构）、:736-744（按 tier 取 profile）、:517-518（intensity）、
                 :696-729（plan）；适配器消费 population_risk / resource_damage / inventory_damage /
                 social_displacement / ecology_pressure
SCHEMA_FIELDS  = tribulation_profiles(profile_id/tier/theme/intensity_min/intensity_max/
                 precursor_steps/preparation_steps/impact_steps/recovery_steps/六项风险/
                 ecology_pressure/succession_rules)；tribulation_schedules(schedule_id/tier/
                 period_years/enabled)
UNIT           = intensity ∈ [0,100]（整数）；*_steps = 福地年；六项风险 = Fraction ∈ [0,1]；
                 ecology_pressure ∈ [0, 1_000_000]
```

**EXISTING_APPROVED_CONSTRAINTS**（**不得重复请求**）：周期 10/50/100（D-E）；首个前兆 tick 10_000_000（RA-TRIB-001 已批准）；`REMOVE_PRODUCTION_TEST_PROFILE_FALLBACK = TRUE` 与 `FAIL_CLOSED`（既有决议）；九阶段生命周期（WS-0902 APPROVED_DESIGN）；tick=0 无活跃灾劫（`world_seed/12` + M3 preflight：schedule=NOT_ACTIVATED、history=EMPTY）；引擎强制 `precursor_steps ≥ 1`（EC-1）；canon NOT_FOUND：intensity/伤害/各 steps 的一切数值，正式灾劫主题名（仅有可配置主题池）；母世界阶梯名（地灾/天劫/浩劫/万劫）**禁止**本地使用。

| 候选 | VALUE | SOURCE | LONG_TERM_EFFECT |
| --- | --- | --- | --- |
| **A** | 每 tier 一套正式 profile：theme 取 canon 主题池（灵气潮汐/地脉波动/兽群躁动/生态失衡），intensity 区间、六项风险、四类 steps 由 owner 给 | LOCAL_CANON（阶段/主题池/风险维度结构）+ OWNER 数值 | 灾劫产生真实后果（人口/资源/库存/社会/生态五路适配器均生效） |
| **B** | 建 profile 但六项风险置 0（结构合规、零伤害） | FROZEN_ENGINE_NEUTRAL_CONSTRAINT（零伤害） | 事件会发生但无领域后果 → 叙事与机制脱节，须 owner 明示接受 |
| **C** | owner 指定 theme 名称与全部数值（含 targeting / succession 规则） | OWNER 数值 | 最大控制力；owner 需给 3×约 14 个字段 |

```
RECOMMENDED_NEUTRAL_CANDIDATE = 无（B 是"零后果"而非引擎中性）
OWNER_MUST_CHOOSE = A / B / C / CUSTOM
```

### OD-8 — RA-STRUCT-001 结构基数规则（显式复核）

```
WHY_BLOCKING   = 该规则产出物化时的行集合基数；owner 已标记 CANDIDATE_ONLY_PENDING_EXPLICIT_REVIEW，
                 未复核则不得写进 SNAPSHOT_V1
FROZEN_CONSUMER= ecology.py:191-199；social.py:568-575；economy.py:164-170,359-362（fail-closed 行要求）
SCHEMA_FIELDS  = ecology_zones / ecology_state / ecology_feedback_state / settlement_social_state /
                 social_feedback_state / resource_stocks / economic_pressure_state /
                 tribulation_schedules 的行集合
UNIT           = 行数（整数）
```

| 候选 | VALUE | SOURCE | LONG_TERM_EFFECT |
| --- | --- | --- | --- |
| **A** | 批准 RA-STRUCT-001 v1.0（区=聚落数；state/feedback 行数由引擎要求派生；排期=已批准 tier 数） | FROZEN_ENGINE_NEUTRAL_CONSTRAINT | 物化器可依此生成完整行集合；规则版本化、可复算 |
| **B** | 不批准为规则，改在 SNAPSHOT_V1 中逐表列出显式行数 | OWNER 决议 | 无派生规则；与引擎要求的一致性不再被规则保证 |
| **C** | 批准但限范围（仅 ecology/social 的 state 行，不含 stocks 矩阵） | OWNER 决议 | 矩阵部分回到 OD-3/OD-4 显式给值 |

```
RECOMMENDED_NEUTRAL_CANDIDATE = A（规则只表达引擎强制要求，不引入任何世界观数值）
OWNER_MUST_CHOOSE = A / B / C / CUSTOM
```

### OD-9 — DYNAMIC_NEUTRAL 初始状态值

```
WHY_BLOCKING   = 这些行必须存在（fail-closed），且初始值会被冻结引擎读取并影响后续轨迹
                 → 不属于技术中性，必须 owner 批准
FROZEN_CONSUMER= ecology.py（habitat_quality）、economy.py（stocks/pressure）、
                 social.py（cohesion/stability/stress）、feedback.py（短缺/生态/社会 → 人口映射）
SCHEMA_FIELDS  = ecology_state.habitat_quality 等；ecology_feedback_state；settlement_social_state；
                 social_feedback_state；economic_pressure_state；resource_stocks.quantity 与 8 个 cum_*
UNIT           = quality/pressure ∈ [0, 1_000_000]；quantity/cum_* = minor units；
                 比值 = num/den（默认 1/1）；stress_level 枚举 NONE/LOW/HIGH
```

| 候选 | VALUE | SOURCE | LONG_TERM_EFFECT |
| --- | --- | --- | --- |
| **A** | 采用引擎 server default（stocks 0、pressure 全 0、cohesion/stability 1_000_000、feedback 全 1/1、ecology pressure/stress 0），**并把 `habitat_quality` 设为 ECOLOGY_STATE_SCALE（满质量 = 无退化起点）** | FROZEN_ENGINE_NEUTRAL_CONSTRAINT + 明示的无退化起点 | stocks=0 会进入短缺路径（除非 OD-3/OD-4 提供开采或库存）；生态从满质量开始 |
| **B** | 全部采用 server default（含 `habitat_quality = 0`） | FROZEN_ENGINE_NEUTRAL_CONSTRAINT | 生态从**最差质量**起步 → 立即走退化/恢复路径，可能产生非预期早期生态事件 |
| **C** | owner 指定初始状态值（可配合 OD-3 的库存缓冲政策） | OWNER 数值 | 可控起点；owner 需给 6 个状态族 × 12 行的关键字段值 |

```
RECOMMENDED_NEUTRAL_CANDIDATE = A 的引擎默认部分（4 个状态族）；habitat_quality 需 owner 单独选定
                                （默认 0 有陷阱）；stock=0 的 dead-economy 风险已登记
OWNER_MUST_CHOOSE = A / B / C / CUSTOM
```

---

## PART 4 — S-1..S-10 映射（`UNTRACKED_BLOCKING_FIELD = 0`）

| # | 项 | 状态 | 说明 |
| --- | --- | --- | --- |
| S-1 | 大致总人口 | `ALREADY_OWNER_APPROVED` | 12000（D-B4） |
| S-2 | 异人种族组合 | `BLOCKED_BY_OD_1` | canon 名已存在（毛民/石人/鲛人/菇人），待确认 |
| S-3 | 主要聚落数量 | `ALREADY_OWNER_APPROVED` | 12 = 4 MAIN + 8 SAT（D-B2；WS-0406 胜出） |
| S-4 | 主要产业 | `BLOCKED_BY_OD_4` | 7 sector 已批准；配方数值缺 |
| S-5 | 主要资源区 | `BLOCKED_BY_OD_3` | 8 node_types 已批准；实例/储量缺 |
| S-6 | 荒兽/异兽层级 | `NON_BLOCKING_NO_ENGINE_REPRESENTATION` | WS-0802：BL-011 异兽 ≠ 荒兽阶梯；引擎无实体（**已 tracked**，非 UNTRACKED） |
| S-7 | 社会组织 | `BLOCKED_BY_OD_6` | 组织形态为 CANON；阈值缺 |
| S-8 | 基础设施 | `NON_BLOCKING_NO_ENGINE_REPRESENTATION` | 引擎无基础设施表；可由 `institutions` 表达（**已 tracked**） |
| S-9 | 发展水平 | `DERIVABLE` | 不设独立字段，由 S-4/S-5/S-8 集合共同表达 |
| S-10 | 灾劫状态 | `ALREADY_OWNER_APPROVED` + `DERIVABLE` + `BLOCKED_BY_OD_7` | 周期已批准；首个前兆已派生；profile 数值与 mode 待 OD-7 |

**非阻塞登记**（不请求决策，但必须 tracked）：U-1 S-6；U-2 S-8；U-3 `ecological_regions` 无业务键（`carrying_capacity` 无引擎消费）；U-4 迁移权重无法按聚落区分（EC-3，冻结引擎既有耦合）。

---

## PART 5 — 本轮明确未做（owner §25/§26）

```
未实现 materializer        未激活正式世界        未消费正式 Seed
未读正式 Seed 原值         未写正式库            未部署 live
未删除/覆盖/迁移 legacy stale DB
未把测试 profile 改名当正式 profile            未接任何测试 registry 到正式路径
未使用 RNG / hash(seed) 生成世界内容
```

## PART 6 — 验证

```
pytest tests/test_m6c1b_authoritative_db_guard.py   → 19 passed
python scripts/audit_authoritative_db.py --plugin-data-dir <launcher instance plugin_data>
    → AUTHORITATIVE_DB_RESOLUTION = PASS（exit 0）；NON_AUTHORITATIVE_DB_DETECTED = TRUE；
      FORMAL_WORLD_RUNTIME_ROWS = 0；STALE_DB_FALSE_POSITIVE = 0
```

```
NEXT_ACTION = AWAIT_OWNER_FINAL_BOOTSTRAP_DECISIONS
```
