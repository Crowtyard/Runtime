# M6C.0 — MINIMAL BOOTSTRAP CANON AUDIT

- 阶段：`M6C.0 BOOTSTRAP CANON AUDIT`（owner：`OWNER_DECISION = OPTION_1`，
  **第一轮只授权到 STOP A**：只做审计，**不写 materializer**）
- 前置：`M6A_ACTIVATION_CONTRACT = PASS`、`M6B_EPOCH_WIRING = PASS`、
  `EMPTY_WORLD_CAN_BOOTSTRAP = FALSE`、`WORLD_SEED_BOOTSTRAP_SPEC_STATUS = ABSENT`
- 正式世界：`WORLD_RUNTIME_ROWS = 0` / `NOT_ACTIVATED` / `SEED_CONSUMED = FALSE`（本阶段不变）
- 只读性质：本阶段**只读**取证；不激活、不物化、不写正式库、不读正式 Seed 原值

## 0. 方法：来源优先级与证据级别

按 owner §2 的优先级取证：

```
LOCAL_CANON > APPROVED_LOCAL_DESIGN > LOCAL_COMPATIBILITY > SOURCE_LORE_GENERAL_RULE
```

并额外标注两类**不可提升**的来源（owner §1/§2 明令）：

```
PLANNING_ONLY   （规划值：如"约 N 人"启动基线、槽位规划数）
TEST_FIXTURE    （测试夹具：TEST_PROFILES / TEST-SPECIES-001 / mini_world / 合成基线）
```

本次取证的来源与级别：

| 来源 | 级别判定 | 依据 |
| --- | --- | --- |
| `XIAOGUANG_CROW_KB/world_seed/*`（21 文件） | 规格壳：`CONFIRMED_STATIC_CANON` 规则 + `APPROVED_WORLD_SEED` 结构 + `PROVISIONAL_*` 规划值 + `UNKNOWN` 注册表 | 自声明 `PREPARED_NOT_ACTIVATED`；`04:3/04:8` 明示规划值不得写成当前事实 |
| `XIAOGUANG_CROW_KB/world_bible/*` | LOCAL_CANON（FROZEN v1.0） | `world_bible/VERSION.json` + `MANIFEST.sha256.txt`（17 文件哈希） |
| `XIAOGUANG_CROW_KB/runtime_design/M2*/M3*`（引擎契约） | APPROVED_LOCAL_DESIGN（引擎语义契约） | 文件名与内容为已批准的引擎/管线契约 |
| `XIAOGUANG_CROW_KB/design/phase1_8/*`（含 11 号初始快照提案） | PLANNING_ONLY / PROPOSAL | 11 号自声明"提案层…未批准前数值保持 UNKNOWN，禁止代填" |
| 本仓库 `database/models_world.py`、`services/simulation/*` | 实现事实（FROZEN M2/M3 语义的实现） | M2/M3 里程碑冻结，Golden Baseline 保护 |

**禁止**：从 `tests/baselines/**`、`mini_world`（TEST_FIXTURE_ONLY）、`TEST_*` registry、
`synthetic` 夹具提升任何正式事实。

---

## 1. World Seed 的 bootstrap 角色（owner §6）

```
WORLD_SEED_BOOTSTRAP_ROLE = B
（仅包含规则 / 类型 / slot / constraints；**不含**可直接物化的 bootstrap instance values）
```

四问逐条（只读，21 文件全读；MANIFEST 20 条目逐条复算，20/20 匹配）：

| 问 | 答 | 证据 |
| --- | --- | --- |
| A. 直接包含 bootstrap instance values？ | **NO**（11 个域全部无） | 所有实例字段为 `null` / `0` / `EMPTY` / `UNDECIDED`：`04:16,18`（current_population/official_population_record）、`06:18`（settlement_inventory）、`09:15`（resource_inventory）、`11:12`（institution_inventory）、`07:5-12`（四层 instances 全 0）、`12:11,14`（tribulation_history=EMPTY、official_history_events=0）、`02:17-24`（tick/纪年/anchor/cursor 全 NULL） |
| B. 仅含规则/类型/slot/约束？ | **YES**（11 个域） | 规则（时间倍率、USE≠MANUFACTURE、生产链、无无限资源、节点状态机、自治原则、危险分级）；类型/候选（物种候选、产业类别、节点类型、生态区类型、机构候选）；槽位（`geo_slot_NN`、`settlement_slot_MAIN/SAT_NN`）；UNKNOWN 注册表（`13`）；激活不变量（`14` A1–A10） |
| C. 定义 seed → instance 的确定性派生算法？ | **NO** | 全包无 hash/PRNG/分布/分配/公式构造；关键词扫描仅命中：`02:10` **禁止**自造换算公式、`02:11` 时间倍率分段积分（记账规则）、`06:3` 禁止随机永久命名、`14:56` checksum（仅完整性，A8）、`14:42` seed_id 仅用于唯一性/幂等 |
| D. 混合形式？ | **是**（但混的是**规格种类**，不是"规则+实例"） | 六层：静态 canon 规则 / 已批准结构框架 / 规划数值 / UNKNOWN 占位（45 项）/ 明令禁止项 / 包外候补（`UNRESOLVED_SEED_CANDIDATES.md` U-01..U-15，L27"正式 Seed 包不含以上任何值"）。**不存在实例层** |

**包自述的激活事务内容**（唯一枚举句）：A4 —— "Activation Transaction 必须一次性原子创建：
**seed、activation epoch、initial tick、real cursor、initial static world state**"
（`14_activation_invariants.json:28`）。**A4 的原子清单里没有任何域实例载荷**
（无居民数、无聚落数、无资源节点数、无初始库存）。

**实例值从哪来？** 包把答案**外推**给未定义的机制（原文）：
`06:13`"实际启用数量与职能待 SNAPSHOT/激活事务"、`06:14`"仅激活后由 Runtime 生成"、
`09:7`"具体节点激活后生成"、`10:10`"初始值激活后确定"、`11:7`"由激活后世界历史自然演化"、
`U-01..U-15` 的 owner 是"主人裁决 / SNAPSHOT 批准 / 激活后历史形成"。
→ 即：**这些值不是可从 Seed 派生的，而是需要主人新的 canon 决定**。

---

## 2. 逐根审计（owner §3/§5/§7）

约定：
- `IS_REQUIRED` = 冻结 M2/M3 管线要在 tick=0 之后合法产生状态，该根是否**必须存在**；
- `VALUE_STATUS` ∈ {`CANONICAL`, `APPROVED_LOCAL_DESIGN`, `DERIVABLE_FROM_SEED`, `UNDEFINED`, `PLANNING_ONLY`}；
- `STRUCTURE_CANON`（结构/类型/字段是否有 canon）与 `INSTANCE_VALUE_CANON`（实例初值是否有 canon）**分开判定**。

| 根 | IS_REQUIRED | CONSUMING_ENGINE | MINIMUM_FIELDS（结构必需） | CANON_SOURCE（结构） | STRUCTURE_CANON | INSTANCE_VALUE_CANON | VALUE_STATUS |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **SETTLEMENT_ROOT** | TRUE | 全部六域的共同轴（人口 `settlement_ref`、资源 `settlement_relation`、经济 `(settlement,resource)` 唯一键、生态 `settlement_relation`、社会 `(world,settlement)` 唯一键） | `world_id`、`settlement_type`（MAIN/SATELLITE/NODE，NOT NULL） | world_bible `04:25-26` **WS-0406**（≈4 主 + 6~10 卫星，APPROVED_WORLD_SEED_DESIGN）+ world_seed `06` + `models_world.py:18-28` | ✔（槽位与类型） | **部分**：规划量级有设计基线，但"实际启用数量与职能待 SNAPSHOT/激活事务"（`06:13`），名称 UNDECIDED，实例 0 | **APPROVED_LOCAL_DESIGN（量级）+ UNDEFINED（启用集合/命名）**；另存 **canon 冲突**：`design/phase1_8/11:10` 未批草案 S-3 作"核心神社区 + 2~6 聚落" |
| **POPULATION_ROOT** | TRUE | DEMOGRAPHY（`PopulationGroupEngine`） | `world_id`、`species`（NOT NULL）、`count`、`age_advance_carry_ticks`（NOT NULL）、`species_profile_ref`（NULL=UNCONFIGURED） | world_bible `05:3-4` **WS-0501**（≈12,000 启动基线，APPROVED_WORLD_SEED_DESIGN；`05:18-19` WS-0503 四族候选比例）+ world_seed `04` + `models_world.py:31-47` | ✔（宏观群体模型，无个体 agent） | **部分**：总量有设计基线（"约"值、激活前不得表述为当前事实、`U-01` 永不精确化）；**年龄结构/每聚落分配/职业组划分无任何 canon**（NOT_FOUND），物种比例仅"候选值，等待 SNAPSHOT 裁决" | **APPROVED_LOCAL_DESIGN（总量量级）+ UNDEFINED（结构分解）** |
| **RESOURCE_NODE_ROOT** | TRUE | RESOURCE（`ResourceEngine`）+ ECONOMY（经 stock 对账） | `world_id`、`kind`（NOT NULL）、`resource_profile_ref`（NULL=UNCONFIGURED）、`remaining_reserve`（NULL=未定级）、`extraction_capacity`、`extraction_carry`（NOT NULL） | world_bible `07:11-12` WS-0703（八态机）+ world_seed `09:5-7`（节点类型）+ `models_world.py:133-160` | ✔（类型/状态机） | ✘（节点数/储量/坐标全 UNKNOWN；`U-10` 归"激活后 SNAPSHOT/生态生成"） | **UNDEFINED** |
| **ECONOMY_STATE_ROOT** | TRUE | ECONOMY（`EconomyEngine`：缺 stock/pressure 行即 `EconomyStateInconsistent`） | `resource_stocks`：`settlement_ref`(NOT NULL)、`resource_profile_ref`(NOT NULL)、`quantity`、7 个 cum 计数器（NOT NULL）；`production_state`：`(settlement_ref, recipe_ref)` 唯一；`economic_pressure_state`：`(settlement_ref, resource_profile_ref)` 唯一 | world_bible `07:5-6,20-21` + world_seed `08:5-7`（产业类别）+ `models_world.py:186-294` | ✔（类别/规则） | ✘（无库存/产能/配方/价格；正式经济 profile 全 UNCONFIGURED） | **UNDEFINED** |
| **ECOLOGY_STATE_ROOT** | TRUE | ECOLOGY（`EcologyEngine`：缺 state 即 `EcologyZoneMissing`） | `ecology_zones.world_id`、`profile_ref`（NULL=UNCONFIGURED）；`ecology_state.zone_ref`(NOT NULL)；`ecology_feedback_state.zone_ref`(NOT NULL) | world_bible `08:15-16` WS-0805（承载力，PROVISIONAL_DESIGN）+ world_seed `10:5-7`（11 类生态区，CONFIRMED_STATIC_CANON）+ `models_world.py:296-380` | ✔（区类型/字段名） | ✘（区数/位置/边界/初值全未定："初始值激活后确定"，`U-11` 归"激活后 SNAPSHOT"） | **UNDEFINED** |
| **SOCIAL_STATE_ROOT** | TRUE | SOCIAL（`SocialEngine`：缺行即 fail-closed） | `settlement_social_state.settlement_ref`(NOT NULL) + UNIQUE(world,settlement)；`social_feedback_state.settlement_ref`(NOT NULL) + UNIQUE(world,settlement) | world_bible `05:31` WS-0507（两层模型）+ `06:12-13` WS-0604（PROVISIONAL_DESIGN）+ world_seed `07`（四层模型 + 自治原则）+ `models_world.py:414-476` | ✔（模型层/自治原则） | ✘（四层 instances 全 0；正式机构 0；家庭/机构阈值仅存在于测试档） | **UNDEFINED** |
| **TRIBULATION_CONFIG_ROOT** | TRUE | TRIBULATION（`TribulationEngine`：无排期则 `next_tribulation_boundary` 恒 None） | `tribulation_profiles`（profile 定义）、`tribulation_schedules`（排期行）—— 二者当前 **0 行** | world_bible `09:16-18` **WS-0905**（T-3M：REGULAR≈10 / MAJOR≈50 / CENTENNIAL≈100 福地年，APPROVED_WORLD_SEED_DESIGN · LOCAL_SIMULATION_TIERS）+ `02:27-28` WS-0209 | partial（层级/代谢机制/边界） | **部分**：层级有设计基线，但明示"**非已启动倒计时**""正式周期裁决前不落具体日历"；`13:24,38` PENDING/未裁决；`U-13` 待主人终裁；另有**未批竞争草案**（`design/phase1_8/13:21`：区域 20~40 年 / 世界 80~120 年）；首个前兆时间 PENDING | **APPROVED_LOCAL_DESIGN（层级量级）+ UNDEFINED（正式周期/首个前兆）**（`M6C_BLOCKER_TRIBULATION_PROFILE = TRUE`：正式 profile 不存在；且引擎静默回落测试档） |

**逐根结论**：七根**全部 IS_REQUIRED = TRUE**。**结构**多数有 canon；**实例值**只有三条**粗粒度设计基线**
（人口≈12,000；聚落≈4 主+6~10 卫星；灾劫层级≈10/50/100 福地年），且都带"约值/未落定/激活前不得表述为事实/
待 SNAPSHOT 裁决"的限定；**没有任何一根**具备可直接物化的完整 `INSTANCE_VALUE_CANON`
（结构分解、每聚落分配、节点/储量/库存/区数/社会阈值等全部 `UNDEFINED`）。

### 2.1 canon 已定义的解决机制（重要）
审计发现 canon **并不缺少"如何补齐实例值"的机制**，而是该机制**尚未执行**：

```
WORLD_CREATION_REVIEW → 逐项批准 S-1..S-10 → 生成 SNAPSHOT_V1（正式世界数据）
→ 之后才允许实现 WORLD_STATE 引擎与时间轴集成 / 正式激活
```

证据：`design/phase1_8/11_initial_world_snapshot_proposal.md:3`（"提案层…**未批准前数值保持 UNKNOWN，禁止代填**"）、
`:8-17`（S-1..S-10 十项，**全部 PENDING_APPROVAL**）、`:21-23`（"任何数值/名单仅在主人批准后写入 WORLD_STATE 草稿；
批准时逐项打勾形成 SNAPSHOT_V1；**模拟启动前必须 SNAPSHOT_V1 就绪**"）；
`design/phase1_8/PHASE_1_8_DESIGN_REPORT.md:50,61`；`runtime_design/20_implementation_roadmap.md:30`
（"SNAPSHOT_V1 批准 → 正式激活…不在本阶段"）。
**当前无任何已批准的初始世界快照**（NOT_FOUND；`world_seed/VERSION.json` = `PREPARED_NOT_ACTIVATED`）。

因此 M6C 的正确路径是 owner §21 的分支 B：**先由主人批准 bootstrap canon（SNAPSHOT_V1）**，
再由一个明确的独立 sub-stage 实现 materializer —— 而不是在审计中顺手发明数值。

### 2.2 引擎侧硬前置与"只能由 bootstrap 提供"的表（§13/§14 证据）

**（a）任何引擎都**不能**创建、只能由 bootstrap 提供的表**（所有权表 `contracts.py:23-42`
＋全 services/ 检索 `table="…"` 无命中）：

```
settlements · ecology_zones（无任何 owner）· resource_profiles · production_recipes ·
tribulation_profiles · tribulation_schedules · industries · ecological_regions ·
persons · tribulations · timeline_entries · cultural_elements
```

→ 这些根**不可能**由冻结引擎自己长出来；缺它们就只能永久缺席（M6B 已实测）。

**（b）完整性/量级要求（引擎会 fail-closed 或静默丢数据）**

| 要求 | 后果 | 依据 |
| --- | --- | --- |
| `settlements.working_name` 必须**有值** | 四域以 truthy `working_name` 为键（经济相位 A–D、生态压力、社会相位、灾劫目标）；无值即被跳过 | `economy.py:118-121`、`ecology.py:169,189`、`social.py:154-156`、`tribulation.py:367-369` |
| `population_groups` 必须覆盖**每一个 cohort bucket（0…N-1）** | 出生写入 bucket 0、移民写入首个生育 bucket，且只会 update **已存在**的行 → **缺行即静默丢人口**（违反 P_INV_12） | `population.py:339,344-346,415-424`；`mini_world.py:154-155`（"空 bucket 也占行 —— 出生落入 bucket 0，缺行会丢失人口"） |
| `resource_stocks` 必须是**完整矩阵**（每个 working_name 聚落 × 任一 stock 行中出现的每个 `resource_profile_ref`） | 否则引擎在相位 C 中途 **KeyError**（非契约化异常） | `economy.py:297-305`（`stocks[(sref, ref)]`） |
| `economic_pressure_state` 每个 `(聚落 × 消费类资源)` 一行 | 缺行 → `EconomyStateInconsistent`（fail-closed） | `economy.py:359-362` |
| 每个生态区必须有 `ecology_zones` + `ecology_state` + `ecology_feedback_state` 三行 | 缺行 → `EcologyZoneMissing` | `ecology.py:191-199` |
| 每个聚落必须有 `settlement_social_state` + `social_feedback_state` | 缺行 → `IntegrityError`（与人口是否为 0 无关） | `social.py:568-575` |
| `tribulation_schedules.tier` ∈ {REGULAR,MAJOR,CENTENNIAL} 且 `period_years` 非空 | 否则 `_TIER_ORDER[...]` **KeyError** | `tribulation.py:174-177` |
| 物种（`population_groups.species`）必须是 registry key | 未知物种 → `DemographyProfileUnconfigured`；经济引擎**即使聚落为空**也会先于短路触发 | `population.py:169-171`；`economy.py:129-131,107-113` |

**（c）两处引擎侧"陷阱"（正式世界必须知情）**

1. `TribulationEngine`：DB 的 `tribulation_profiles` 行是**死读** —— 载入并传参，但参数在
   `_run_stage` 体内从未被引用（`tribulation.py:338-339,450,462-463`）；
   实际 lookup 只用构造函数注入的 `self._profiles`（`736-744`）。反之
   `tribulation_schedules` **确实被读**（`336-337,170-177`），是唯一能起灾劫的生产杠杆。
2. `SocialEngine`：`SocialProfileUnconfigured` **定义了但从未 raise**；
   `SOCIAL_PROFILES` registry 是**死代码**（全仓仅定义处与一处测试断言引用），
   唯一配置通道是构造参数，且 `self._profile = profile or TEST_SOCIAL_PROFILE`（`142`）
   会在传入空/None 时**静默回落测试档**。
3. `PopulationGroupEngine`：`DEMOGRAPHY_PROFILE_REF = "TEST_PROFILE_001"`（`40`）会被写入
   `population_groups.species_profile_ref`，但它**不是** `SPECIES_PROFILES` 的 key（`116`）
   → 持久化的 profile 引用无法反解回 registry。
   另：`_settlement_order`（`149-150`）对 "TEST-MAIN-A" 返回 0、**其它一律返回 1**，
   并在 `370-371` 用作 `migration_weights` 下标 → 正式聚落名会一律走 weight[1]，
   若 profile 的 `migration_weights` 少于 2 项即 **IndexError**。

以上均属**冻结引擎内部**的既有耦合；M6C 只登记、不修改（owner §0 禁止改冻结语义），
但它们构成正式 profile registry（D-C）必须一并解决的边界条件。

### 2.3 最小性证据：哪些**不需要**在 tick=0 物化（owner §14）

逐项以"删除后冻结引擎能否照常产生状态"验证，以下**不属于** minimum bootstrap：

| 表 | 为什么不是必需 | 依据 |
| --- | --- | --- |
| `households` / `lineages` / `institutions` | SOCIAL 是**唯一会自己创建根行**的 M2 引擎（`new_row` 插入） | `social.py:288-291,400-411,547-558` |
| `tribulation_episodes` / `tribulation_decisions` / `tribulation_impact_plans` / `tribulation_recovery_states` / `tribulation_residual_changes` / `resource_succession_candidates` | 由 TRIBULATION 引擎 / owner decision API / coordinator 在运行中创建 | `tribulation.py:376-412,520-522,548-563,572-598,629-659`；`coordinator.py:336-353` |
| `tribulation_profiles` | **死读**：载入后从不参与 lookup → 空表与有表行为一致 | `tribulation.py:338-339,450,462-463` vs `736-744` |
| `ecological_regions` / `industries` / `persons` / `tribulations` / `timeline_entries` / `cultural_elements` | 无任何 M2/M3 引擎读或写（`ecological_regions`/`industries` 虽在所有权表中但从未被写） | `contracts.py:23-42` + 全目录检索无命中 |
| `production_recipes` / `production_state` | 可选：无 `production_state` 行则该 聚落×配方 不生产（不报错） | `economy.py:189-191` |
| `resource_nodes` | 可选但**行为决定**：无节点即无开采（RESOURCE 合法空转） | `resource.py:138-142` |

→ **MINIMUM_BOOTSTRAP_ENTITY_SET** = §2 的七根 + §2.2(b) 的完整性要求；
其余一律不属于最小集（materializer 不得"顺便生成以后可能用到的内容"，owner §14）。

---

## 3. 正式 Profile Registry 状态（owner §4/§17）

六个域的 profile registry 现状（均为**引擎自声明**的测试夹具）：

| 域 | registry 符号 | 定义位置 | 构造默认值 | 自声明 |
| --- | --- | --- | --- | --- |
| DEMOGRAPHY | `SPECIES_PROFILES`（`TEST-SPECIES-001`） | `population.py:100-116` | `profiles if profiles is not None else SPECIES_PROFILES`（`:162`） | "TEST_FIXTURE_ONLY：synthetic species 参数（**不得作为正式种族 Canon**）"（`:100`）；缺 profile → `DemographyProfileUnconfigured`（`:169`，"正式种族保持 UNCONFIGURED"） |
| RESOURCE | `RESOURCE_PROFILES`（TEST-RESOURCE-001..003） | `resource.py:66-88` | `profiles if profiles is not None else RESOURCE_PROFILES`（`:116`） | "synthetic resource profile（**不得作为正式资源 Canon**）"（`:66`）；缺 profile → `ResourceProfileUnconfigured`（`:124`） |
| ECONOMY | `SPECIES_ECONOMY_PROFILES`（`TEST-SPECIES-001`） | `economy.py:73-80` | `profiles if profiles is not None …`（`:103`） | "synthetic economy profile（**不得作为正式种族 Canon**）"（`:73`）；缺 profile → `EconomyProfileUnconfigured`（`:110`） |
| ECOLOGY | `ECOLOGY_PROFILES`（`TEST-ECOLOGY-PROFILE-001`） | `ecology.py:115-119` | `profiles if profiles is not None else ECOLOGY_PROFILES`（`:137`） | "synthetic ecology profile（**不得作为正式生态 Canon**）"（`:115`）；缺 profile → `EcologyProfileUnconfigured`（`:143`） |
| SOCIAL | `SOCIAL_PROFILES`（`TEST-SOCIAL-PROFILE-001`） | `social.py:103-107` | **`self._profile = profile or TEST_SOCIAL_PROFILE`（`:142`）** ⚠ 传 `None`/空即回落测试档 | "synthetic social profile（**不得作为正式社会 Canon**）"（`:103`） |
| TRIBULATION | `TEST_PROFILES` + `TEST_SCHEDULE` | `tribulation.py:118-159` | **`self._profiles = profiles or TEST_PROFILES`（`:308`）** ⚠ 静默回落测试档（空 dict 也回落） | "合成 profile（**正式 profile=0，绝不自动创建**）"（`:118`） |

附：`services/simulation/feedback.py` 的 shortage→mortality / 生态→人口 / 社会→人口 反馈映射
同样自声明 `TEST_FIXTURE_ONLY`，且"`species != TEST-SPECIES-001` → `Fraction(0)`（正式种族 UNCONFIGURED）"
（`feedback.py:10-12, 21, 30, 55, 71, 74, 105`）。

```
FORMAL_POPULATION_PROFILE_REGISTRY   = ABSENT（仅 TEST_SPECIES_PROFILE）
FORMAL_RESOURCE_PROFILE_REGISTRY     = ABSENT（仅 TEST_RESOURCE_PROFILE_*）
FORMAL_ECONOMY_PROFILE_REGISTRY      = ABSENT（仅 TEST_ECONOMY_PROFILE）
FORMAL_ECOLOGY_PROFILE_REGISTRY      = ABSENT（仅 TEST_ECOLOGY_PROFILE）
FORMAL_SOCIAL_PROFILE_REGISTRY       = ABSENT（仅 TEST_SOCIAL_PROFILE）
FORMAL_TRIBULATION_PROFILE_REGISTRY  = ABSENT（仅 TEST_PROFILES / TEST_SCHEDULE）
FORMAL_PROFILE_REGISTRY_GAP          = TRUE
```

> **灾劫特别提示（owner §18）**：`TribulationEngine` 的 `profiles or TEST_PROFILES` 是
> **静默回落**（传空 dict 也会回落测试档）；且 DB 中的 `tribulation_profiles` 行
> **不参与 profile lookup**（lookup 只读内存 registry）。因此"提供正式 profile"必须
> 同时解决：① 正式 profile 数据来源（canon）；② 去除静默回落。
> 本阶段**未**改动（§18 要求"不得把测试 profile 改个名就当正式 profile"）。

---

## 4. ROOT_DEPENDENCY_GRAPH（owner §12）

**关键事实**：业务表之间**没有任何 DB 级外键** —— ORM 全库只有
`*.world_id -> world_runtime` 这一组外键（`database/models_world.py`；自动提取：
45 张表，FK 边仅 7 条，全部指向 `world_runtime`）。表间关系全部是**软引用字符串列**
（`settlement_ref` / `resource_profile_ref` / `zone_ref` / `recipe_ref` / `species` …）。

因此依赖拓扑**不能**由 DB FK 给出，只能由**引擎前置条件 + 软引用语义**决定：

```
world_runtime (ACTIVE, tick=0, anchor)          ← 已由 M6A/M6B 保证
  └─ time_ratio_history（blessed 起始 = 0，速率行）  ← M6A 已建立
       └─ settlements（聚落根：settlement_ref 的取值域）
            ├─ population_groups（species, settlement_ref, count, species_profile_ref）
            ├─ resource_nodes（kind, resource_profile_ref, settlement_relation）
            │    └─ resource_stocks（settlement_ref × resource_profile_ref）   [ECONOMY 前置]
            ├─ resource_profiles（resource_id → profile 语义）               [RESOURCE/ECONOMY 前置]
            ├─ production_recipes / production_state（settlement_ref × recipe_ref）[ECONOMY]
            ├─ economic_pressure_state（settlement_ref × resource_profile_ref） [ECONOMY 前置]
            ├─ ecology_zones（profile_ref, settlement_relation）
            │    ├─ ecology_state（zone_ref）
            │    └─ ecology_feedback_state（zone_ref）
            └─ settlement_social_state（world_id × settlement_ref 唯一）
                 └─ social_feedback_state（world_id × settlement_ref 唯一）
  └─ tribulation_profiles / tribulation_schedules   [TRIBULATION 前置；当前 0 行]
  └─ world_events（genesis；唯一正式历史起点）
```

- **无 cycle**：软引用图是有向无环的（settlement → 各域 → 各域派生状态），
  且 DB 层不存在业务 FK，故不存在 DB 级环；
- **无 invalid ref 需要应用层自证**：由于没有 DB 外键，软引用的完整性（例如
  `population_groups.settlement_ref` 是否指向真实聚落）**不受数据库保护** ——
  任何未来的 materializer 必须自行校验并在失败时 fail-closed（M6B 的
  `PRAGMA foreign_key_check` 在此**无效**，因为它没有 FK 可查）。

> 该发现同时解释了 M6B §8 的 `NO_INVALID_REFS = TRUE` 是**平凡成立**（业务表为空），
> 而非被 DB 约束保证。

---

## 5. STRUCTURE_CANON vs INSTANCE_VALUE_CANON（owner §5）

| 域 | STRUCTURE_CANON（结构/类型/字段/规则） | INSTANCE_VALUE_CANON（实例初值） |
| --- | --- | --- |
| 时间 | ✔ `02`：倍率规则 + effective-dated 区间积分（CONFIRMED_STATIC_CANON）；tick=0 与 anchor 已由 owner canon 决定（M6B） | ✔（owner 已裁决：tick=0、anchor=显式激活时刻） |
| 地理 | ✔ `03`：神社 canon + 自然类型（CONFIRMED_STATIC_CANON） | ✘ 分带槽名称/位置/边界 UNDECIDED |
| 聚落 | ✔ `06`：槽位与类型（PROVISIONAL_APPROVED_SEED / 结构） | ✘ 启用数量与名称 UNDECIDED、实例 0 |
| 人口 | ✔ `04`：宏观群体模型（APPROVED_WORLD_SEED，无个体 agent） | ✘ 启动基线为规划值；年龄结构/物种比例 UNKNOWN |
| 物种 | ✔ `05`：候选身份（APPROVED_WORLD_SEED_DESIGN） | ✘ population_share 全 null |
| 资源 | ✔ `09`：节点类型 + 八态机 | ✘ 实例 0、储量/坐标 UNKNOWN |
| 经济 | ✔ `08`：产业类别 + USE≠MANUFACTURE + 生产链 | ✘ 无产量/价格/库存 |
| 生态 | ✔ `10`：生态区类型 + 状态字段名 | ✘ 初始值"激活后确定" |
| 社会 | ✔ `07`：四层模型 + 自治原则 | ✘ 四层 instances 全 0 |
| 机构 | ✔ `11`：候选类型（PROVISIONAL_DESIGN） | ✘ 正式机构 0 |
| 灾劫 | partial：仅代谢机制/边界（`09:11-13`、`12:11-12`） | ✘ 无窗口/周期/等级映射（UNDECIDED） |

**结论**：**结构已批准 ≠ 可以创造实例数量**（owner §5 明令）。当前**没有任何域**
具备 `INSTANCE_VALUE_CANON`（除时间，已由 owner 在 M6B 裁决）。

---

## 6. 硬门禁（owner §16，已实现并测试）

`tests/test_m6c_bootstrap_canon_guard.py`（本阶段新增，6 项，全绿）：

| 门禁 | 内容 |
| --- | --- |
| `M6C-G01` | 正式 bootstrap/activation 路径的**代码级**扫描（AST，docstring 不计）：不得出现 `TEST_PROFILES` / `TEST-SPECIES` / `TEST_*_PROFILE` / `TEST_SCHEDULE` / `mini_world` / `synthetic_world` / `TEST_FIXTURE_ONLY` → **`TEST_FIXTURE_REFERENCES_IN_BOOTSTRAP = 0`** |
| `M6C-G01b` | activation/bootstrap 路径不得 import 或构造任何冻结引擎（`population/resource/economy/ecology/social/tribulation/mini_world/contracts/coordinator`） |
| `M6C-G01c` | runtime scheduler 不得构造引擎（只编排 `catch_up`/adapter；引擎由接线方提供） |
| `M6C-G02` | **把本次审计的 canon 缺口钉成回归门禁**：六域 registry 必须仍自声明 `TEST_FIXTURE_ONLY`；"正式种族/资源/生态保持 UNCONFIGURED" 语义必须保留；`TribulationEngine` 的 `profiles or TEST_PROFILES`、`SocialEngine` 的 `profile or TEST_SOCIAL_PROFILE` 必须仍在 → 任何"改名当正式"或"静默接上测试档"都会失败，必须显式授权后连同门禁一起改 |
| `M6C-G02b` | 除引擎目录自身外，production 路径不得引用 `TEST_*` registry（只读查询层的 `source="TEST_FIXTURE_ONLY"` 是 **provenance 标签**默认值，单独说明并排除） |
| `M6C-G03` | §29：未获授权前**不得**出现 materializer（AST 定义名判定，不误伤注释/散文） |

---

## 7. Canon Gap 判定（owner §8/§9）

```
MINIMUM_REQUIRED_BOOTSTRAP_STATE = 7 roots（见 §2）
  全部 IS_REQUIRED = TRUE；全部缺 INSTANCE_VALUE_CANON
CANONICAL_BOOTSTRAP_SPEC = INCOMPLETE
M6C_CANON_READY = FALSE
```

**为什么不进入 M6C.1**：owner §8 明确要求"任何 M2/M3 必需 root 的必要实例值仍为
`UNDEFINED` 且无 approved deterministic derivation rule → `M6C_CANON_READY = FALSE`，
不要写正式 materializer"。本次审计证实：

1. 七根的实例初值**没有任何一根**具备完整 canon：只有三条**粗粒度设计基线**
   （人口≈12,000 / 聚落≈4 主+6~10 卫星 / 灾劫层级≈10/50/100 福地年），且均是"约值+
   激活前不得表述为事实+待 SNAPSHOT 裁决"；**引擎所需的分解结构（年龄 cohort、
   每聚落分配、职业组、启用集合、节点数/储量、库存/产能、区数/初值、社会阈值、
   正式周期）全部 UNDEFINED**；
2. Seed 包**不提供**实例值（角色 = B），也**不定义**派生算法（C = NO），
   且明令禁止补全（A9；`13:3`"UNKNOWN MUST REMAIN UNKNOWN"；`UNRESOLVED:27-28`）；
3. canon **已定义解决机制但尚未执行**：`WORLD_CREATION_REVIEW → S-1..S-10 逐项批准 →
   SNAPSHOT_V1`，且明文"**模拟启动前必须 SNAPSHOT_V1 就绪**"（`11:21-23`）。
   当前 **S-1..S-10 全部 PENDING_APPROVAL**、无已批准初始快照（NOT_FOUND）；
4. 现有 profile registry 全部是测试夹具（`FORMAL_PROFILE_REGISTRY_GAP = TRUE`），
   且 `TribulationEngine` 会**静默回落**测试档（`tribulation.py:308`）；
5. 存在一处需主人裁决的 canon 冲突：S-3 草案（2~6 聚落）vs WS-0406（4 主+6~10 卫星）。

---

## 8. 最小 owner 决策列表（owner §19/§20）

**只列"无法从现有资料推出、且确实阻塞正式 materialization"的最小集。**
可从已批准结构/规则推出的项（聚落类型枚举、节点状态机、USE≠MANUFACTURE、宏观群体模型、
生态区类型、社会四层模型、时间倍率与区间积分）**不列**。

### D-A｜批准 S-1..S-10 → 形成 SNAPSHOT_V1（canon 已有的机制与清单）

canon **已经定义了机制与清单**，只是尚未执行（见 §2.1）。十项全部 `PENDING_APPROVAL`
（`design/phase1_8/11_initial_world_snapshot_proposal.md:8-17`）：S-1 大致总人口、
S-2 异人种族组合、S-3 主要聚落数量、S-4 主要产业、S-5 主要资源区、S-6 荒兽/异兽层级、
S-7 社会组织、S-8 基础设施、S-9 发展水平、S-10 灾劫状态。
→ 请主人依 `:21-23` 的提交纪律逐项批准/变更/否决，形成 **SNAPSHOT_V1**。

**同时请裁决一处 canon 冲突**：`S-3 草案`（"核心神社区 + 2~6 聚落"）与已批准设计基线
`WS-0406`（"约 4 主 + 6~10 卫星"）**数值不一致**（`11:10` vs `world_bible/04:25-26`）。

### D-B｜SNAPSHOT_V1 未覆盖、但冻结引擎在 tick=0 **必需**的结构化参数

S-1..S-10 是"世界层"决策，**不包含引擎所需的分解结构**。以下全部 `UNDEFINED`（NOT_FOUND）：

| # | 参数 | 为什么阻塞（冻结依据） | 所属 |
| --- | --- | --- | --- |
| D-B1 | 人口的**年龄结构**（cohort 划分与占比） | 出生/死亡/年龄推进作用于既有 cohort（`population.py:181-185` 零行即零产出） | POPULATION |
| D-B2 | 人口的**每聚落分配**（含物种×聚落交叉） | `population_groups` 以 `settlement_ref` 为轴；社会/资源的派生都按聚落 | POPULATION |
| D-B3 | **职业组划分**与户统计口径 | `occupation_group` / `household_stats` 参与社会派生 | POPULATION/SOCIAL |
| D-B4 | 四族**精确名额**（候选 4k/3k/2.5k/2.5k 仍"等待 SNAPSHOT 裁决"） | `species` 是 NOT NULL 且决定 profile 解析 | POPULATION |
| D-B5 | **启用聚落集合**（MAIN/SAT 各启用哪些槽位、每聚落 `settlement_type`、是否用 `WORKING_NAME`） | `06:13`"实际启用数量与职能待 SNAPSHOT/激活事务" | SETTLEMENT |
| D-B6 | **资源节点集合**：节点数、每节点 `kind`、正式 `resource_profile_ref`、`remaining_reserve`/`extraction_capacity` 的初值与口径 | RESOURCE 零节点即零产出；`09:15`"储量/坐标/状态全 UNKNOWN" | RESOURCE |
| D-B7 | **初始经济状态**：每 `(聚落×资源)` 初始库存、`production_recipes` 清单与产能、是否需初始 `production_state`/`economic_pressure_state` 行 | 缺 stock/pressure 行 → `EconomyStateInconsistent`（fail-closed） | ECONOMY |
| D-B8 | **初始生态区集合**：区数、每区正式 `profile_ref`、`ecology_state`/`ecology_feedback_state` 初值语义 | 缺 state 行 → `EcologyZoneMissing`（fail-closed） | ECOLOGY |
| D-B9 | **正式社会阈值来源**：`formation_size`/`split_threshold`/`institution_found_pop` 等（或明确"正式世界不使用阈值"） | 阈值目前只存在于 `TEST_SOCIAL_PROFILE`；缺状态行 → fail-closed | SOCIAL |
| D-B10 | **灾劫正式周期数值终裁**（≈10/50/100 是否落定）与**首个前兆时间** | `13:24,38` PENDING/未裁决；`U-13` 待主人终裁；另有未批竞争草案（20~40/80~120） | TRIBULATION |

### D-C｜五域正式 profile registry 的授权与来源（owner §17）

```
FORMAL_PROFILE_REGISTRY_GAP = TRUE（六域构造默认全部指向测试档，见 §3）
```
请主人授权新建 **bootstrap configuration 层**（只描述合法初始实体模板/参数，**不改变后续 engine law**），
并指定每个 profile 数值的 canon 来源。**特别地**（owner §18）：灾劫需明确
①正式 profile 数据来源；②是否授权**去除** `TribulationEngine` 的 `profiles or TEST_PROFILES` 静默回落。

### D-D｜是否授权"确定性派生"（owner §6）

若主人希望初始实例值由规则/seed **确定性派生**（而非逐项给值），必须先批准一个 derivation rule：
canon 现有确定性原语只覆盖 **RNG 子流**（`M2_PREFLIGHT:97-104`）、**event uid**（`:112-118`）、
**实体 id**（`M2D:123-127`），**均不产生世界内容**；且 A9 禁止 Runtime 自行补 UNKNOWN。
M6C **不得**临时发明 `hash(seed) % N` 之类的规则。

---

## 9. 本阶段明确未做的事

- **未实现 materializer**（§29：第一轮只授权到 STOP A；门禁 `M6C-G03` 已钉住）；
- **未修改任何冻结 M2/M3 语义**、未新增人口/资源/经济/生态/社会/灾劫/history 规则；
- **未把测试 profile 改名当正式 profile**、未接任何测试 registry 到正式路径；
- **未激活正式世界**、未消费正式 Seed、未读正式 Seed 原值、未写正式库、未部署 live。

---

## ADDENDUM — M6C.1（审计更正；原文不删，逐条并列）

M6C.1（SNAPSHOT_V1 CANDIDATE CONSTRUCTION）对 §8 D-B 列表做了代码级复核，
发现**一处原文不成立**，登记如下（原文保留以满足历史可追溯）：

| 位置 | 原文主张 | M6C.1 更正 | 证据 |
| --- | --- | --- | --- |
| §8 D-B3（本文第 338 行） | `occupation_group` / `household_stats` 阻塞，因为"参与社会派生" | **不成立**。`occupation_group` 在全仓**无任何引擎读取**（WRITE_ONLY：仅影响 snapshot 行序与 `world_state_hash`）；`household_stats` **零读零写**，且**不在** snapshot 字段投影内。二者因此**不阻塞** tick=0 物化，D-B3 可从"阻塞项"降级为"无需裁决" | `snapshot.py:88-91,263-264`；`state_hash.py:40,66`；`economy.py:133-136,188-211`（劳动力 = 聚落总人口，与职业无关）；`social.py:157-200` |

补充确认（M6C.1 新增证据，均不影响原文其余结论）：

- `households` / `lineages` / `institutions` **不需要**预置：SOCIAL 在缺行时自建
  （`social.py:267-299`），其 fail-closed 只针对 `settlement_social_state`
  （`568-571`）与 `social_feedback_state`（`572-575`）—— 支持原文 §2.3 判定。
- `population_groups` **无** `(world_id, species, settlement_ref, age_cohort)` 唯一约束
  （`models_world.py:31-47` 无 `__table_args__`），而同一 bucket 出现两行会**重复计数**
  （`population.py:289-292` vs `344-346`）→ "每 bucket 恰好一行"是 **bootstrap 义务**，
  DB 层无兜底。
- 灾劫：`precursor_steps = 0` 会在同一步触发 `ep["id"]` **KeyError**
  （`tribulation.py:426-433,439-441,472-475`）→ `precursor_steps >= 1` 是引擎强制下界。

以上更正已同步进 `docs/world_creation/SNAPSHOT_V1_CANDIDATE.md` §11 与候选 JSON
`audit_corrections`。
