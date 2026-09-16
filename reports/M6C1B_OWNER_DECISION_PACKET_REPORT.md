# M6C.1B — OWNER DECISION PACKET & AUTHORITY HARDENING 报告

```
M6C1B_OWNER_DECISION_PACKET_REPORT
STAGE                      = M6C.1B OWNER DECISION PACKET & AUTHORITY HARDENING
M6C1B_STATUS               = COMPLETED（等待主人裁决；未实现 materializer）
AUTHORITATIVE_DB_RESOLUTION = PASS
LEGACY_DB_DETECTED          = TRUE
LEGACY_DB_CLASSIFICATION    = LEGACY_STALE_NON_AUTHORITATIVE_DB
STALE_DB_FALSE_POSITIVE     = 0
AMBIGUOUS_DB_FAIL_CLOSED    = PASS

RA_ALLOC_001 = APPROVED_BOOTSTRAP_DERIVATION（已按 owner 要求复核：integer-only / no RNG /
               deterministic / fixed tie-break / 行边际精确 / 列边际精确 / 可独立复算）
RA_TRIB_001  = APPROVED_BOOTSTRAP_DERIVATION（FIRST_OMEN_BLESSED_YEAR = 10；
               FIRST_OMEN_TICK = 10_000_000；未重新解释为新灾劫规则）
RA_COHORT_001    = PENDING（CANDIDATE_ONLY）
RA_MORTALITY_001 = PENDING
RA_STRUCT_001    = PENDING（CANDIDATE_ONLY_PENDING_EXPLICIT_REVIEW → OD-8）

OCCUPATION_OWNER_DECISION = NOT_REQUIRED
HOUSEHOLD_OWNER_DECISION  = NOT_REQUIRED

TECHNICAL_NEUTRAL_COUNT = 3 字段（24 值实例；AUTO_ACK_ELIGIBLE = TRUE）
DYNAMIC_NEUTRAL_COUNT   = 6 状态族（全部进入 OD-9）

S1_S10_UNTRACKED_BLOCKERS = 0
OWNER_DECISION_COUNT      = 9（<= 10）
OWNER_DECISION_PACKET     = docs/world_creation/M6C1B_OWNER_DECISION_PACKET.md（+ .json）

SNAPSHOT_V1                = NOT_APPROVED
MATERIALIZER_ALLOWED       = FALSE
FORMAL_WORLD_RUNTIME_ROWS  = 0
FORMAL_WORLD_STATUS        = NOT_ACTIVATED
FORMAL_WORLD_SEED_CONSUMED = FALSE
NEXT_ACTION                = AWAIT_OWNER_FINAL_BOOTSTRAP_DECISIONS
```

## 1. 本阶段交付

| 文件 | 作用 |
| --- | --- |
| `docs/world_creation/M6C1B_OWNER_DECISION_PACKET.md` | owner 阅读版：权威裁决 + 规则裁决 + 中性重分类 + **9 个 OD（§11 统一格式）** + S-1..S-10 映射 |
| `docs/world_creation/M6C1B_OWNER_DECISION_PACKET.json` | 机读版（同一结构，供审计与后续自动化） |
| `tests/formal_db.py`（扩展） | 权威解析契约：`resolve_authoritative_db` / `redline_report` / `discover_dbs` + `AuthoritativeDbAmbiguous` |
| `scripts/audit_authoritative_db.py` | 只读审计 CLI（`--plugin-data-dir` 必填；无硬编码路径；退出码 0/2/3） |
| `tests/test_m6c1b_authoritative_db_guard.py` | 19 项：权威解析 / stale 假阳性 / 歧义 FAIL CLOSED / 硬编码路径审计 / §27 复assert |
| `tests/test_m6c1b_owner_decision_packet.py` | 15 项：packet 结构 / 候选来源限制 / 规则状态 / 中性分类可验证 / S-1..S-10 / MD-JSON 一致 |

## 2. 权威库 hardening（owner §2–§6）

**实测（只读；`sqlite3 mode=ro`，不建 sidecar、不写）**：

```
resolved（marker 指向）  = <launcher instance>\core\data\plugin_data\astrbot_plugin_blessed_land_runtime\blessed_land.sqlite
MARKER_CHECKSUM_MATCH    = True
FORMAL_DB_SHA256         = 7754b1d4658ea94ce509ae7fb7c06c33c44f98782021b3708e6f29ce69102837（= M6 基线，未漂移）
world_runtime            = 0 行    业务表 = 全部 0 行（唯一非空 = alembic_version a9d4f2b7c1e8）
CANDIDATE_DB_COUNT       = 2       NON_AUTHORITATIVE_DB_DETECTED = TRUE（1）
  └ legacy: D:\MY SELF\AstrBot\data\plugin_data\...\blessed_land.sqlite
    world_runtime = 1（**不被采纳**，consulted_for_redline = False）、sha256 e0c5d32f…8203
STALE_DB_FALSE_POSITIVE  = 0       FALSE_POSITIVE_ACTIVATED = False
```

**处置**：`LEGACY_DB_PRESERVED = TRUE`、`LEGACY_DB_AUTHORITATIVE = FALSE`；**未删除/未覆盖/未迁移**（保留 forensic / historical diagnosis）。

**硬化规则（已测）**：
1. 正式库**只能**经 `runtime_state/authoritative_db.json` 解析（生产架构既有契约）；
2. 无权威元数据却有候选 → `AMBIGUOUS`；
3. checksum 不符 / marker 路径越界 / 显式覆盖与 marker 冲突 / marker 指向缺失文件 → `AMBIGUOUS`；
4. `AMBIGUOUS` → `AuthoritativeDbAmbiguous`（FAIL CLOSED），**不得**执行 activation / materialization / formal mutation；
5. **禁止**"选第一个 / 选最新 mtime / 选固定路径"；
6. 红线数值**只能**取自权威库；非权威副本仅被登记，绝不参与判定。

**硬编码路径审计（§4）**：命中 4 处（3 处为 M5 期 live/诊断脚本，1 处为 M6C.1 候选文档字符串），**具备 DB 能力的硬编码路径 = 0**；生产目录（`services/`、`plugin_shell/`、`database/`）命中 = 0；任何**新增**或**具备 DB 能力**的硬编码路径都会使守卫测试失败。

## 3. 中性值重分类（owner §7–§9）

- **TECHNICAL_NEUTRAL = 3 字段**（`settlements.state` / `settlements.region_ref` / `settlements.settlement_type`），`ENGINE_READ_COUNT = 0`，均 `AUTO_ACK_ELIGIBLE = TRUE`；本轮**未**改 SNAPSHOT_V1 状态（owner §8）。
- **DYNAMIC_NEUTRAL = 6 状态族**（`ecology_state` / `ecology_feedback_state` / `settlement_social_state` / `social_feedback_state` / `economic_pressure_state` / `resource_stocks`），全部进入 **OD-9**。
- 两个已登记陷阱：`ecology_state.habitat_quality` 的列默认 **0 = 最差质量**（不是中性起点）；`resource_stocks.quantity = 0` 且无开采 → **dead economy**（并经 feedback 影响人口）。
- 静态扫描可验证：引擎消费 settlements 行的键集合 = `{working_name, population_capacity, species(来自 population_groups)}`，**不含** `state`/`region_ref`/`settlement_type`；`region_ref` 的引擎读取点全在 `resource_nodes`/`ecology_zones`/`tribulations`（9 处，逐行钉住）。

## 4. 九个 Owner Decision（≤10；详细候选见 packet）

| # | 决策 | 阻塞的 REQUIRED root | 候选数 |
| --- | --- | --- | --- |
| OD-1 | S-2 异人种族身份（species 字符串） | `population_groups.species` + 正式 population registry 键 | 3 + CUSTOM |
| OD-2 | 人口世界法则（年龄结构/生命表/繁衍/迁移/聚落容量） | `cohort_buckets`、`mortality_by_bucket`、`birth_rate`、`emigration_rate`、`migration_weights`、`population_capacity` | 3 + CUSTOM（+2 子决策） |
| OD-3 | 资源集合、节点与正式 resource profile（S-5） | `resource_profiles`、`resource_nodes`、`resource_stocks` 矩阵 | 3 + CUSTOM |
| OD-4 | 初始经济状态与产业配方（S-4 + D-B7） | `production_recipes`、`economic_pressure_state`、初始库存 | 3 + CUSTOM |
| OD-5 | 生态区与正式 EcologyProfile（D-B8） | `ecology_zones/state/feedback` 三表 + profile 数值 | 3 + CUSTOM |
| OD-6 | 正式社会阈值（S-7 + D-B9） | 正式 `SocialProfile` 全部阈值 | 3 + CUSTOM |
| OD-7 | 正式灾劫 profile 数值（S-10 剩余） | 每 tier 正式 profile 数值 | 3 + CUSTOM |
| OD-8 | RA-STRUCT-001 结构基数规则显式复核 | 物化行集合基数 | 3 + CUSTOM |
| OD-9 | DYNAMIC_NEUTRAL 初始状态值 | 6 个状态族的初始值 | 3 + CUSTOM |

**未重新请求**（既有决议）：周期 10/50/100、首个前兆 10 福地年、`REMOVE_PRODUCTION_TEST_PROFILE_FALLBACK = TRUE`、`FAIL_CLOSED`、registry 建立授权、occupation / household（`NOT_REQUIRED`）。

**canon 挖掘结论（本轮 3 次只读深挖）**：四族身份 canon **存在**（毛民/石人/鲛人/菇人；WS-0502「主人圈定」+ WS-0503 名额与 D-B5 逐位吻合；seed 声明英文名）→ OD-1 是"**确认**"而非"发明"；而**一切速率/数量**（生育、死亡、迁移、资源储量、生态数值、社会阈值、灾劫强度、经济数值）在 canon 中 **NOT_FOUND** 且被明文禁止代填 → 只能由 owner 给值或明确授权规则。

## 5. S-1..S-10（`UNTRACKED_BLOCKING_FIELD = 0`）

```
S-1  ALREADY_OWNER_APPROVED          S-6  NON_BLOCKING_NO_ENGINE_REPRESENTATION（tracked）
S-2  BLOCKED_BY_OD_1                 S-7  BLOCKED_BY_OD_6
S-3  ALREADY_OWNER_APPROVED          S-8  NON_BLOCKING_NO_ENGINE_REPRESENTATION（tracked）
S-4  BLOCKED_BY_OD_4                 S-9  DERIVABLE
S-5  BLOCKED_BY_OD_3                 S-10 ALREADY_OWNER_APPROVED + DERIVABLE + BLOCKED_BY_OD_7
```

非阻塞登记：U-1 S-6、U-2 S-8、U-3 `ecological_regions` 无业务键（`carrying_capacity` 无引擎消费）、U-4 迁移权重无法按聚落区分（EC-3）。

## 6. 测试证据（§27）

```
pytest tests/test_m6c1b_authoritative_db_guard.py      → 19 passed
pytest tests/test_m6c1b_owner_decision_packet.py       → 15 passed
pytest tests/test_m6c1_snapshot_candidate.py           → 26 passed（未回退；candidate_sha256 00d24192…）
pytest tests/test_m6c_bootstrap_canon_guard.py         →  6 passed（M6C-G01..G06 未回退）
AUTHORITATIVE_DB_RESOLUTION = PASS（live 只读审计，exit 0）
STALE_DB_FALSE_POSITIVE     = 0
AMBIGUOUS_DB_FAIL_CLOSED    = PASS（合成歧义夹具 + CLI exit 2）
RA_ALLOC_001                = PASS（矩阵复算 + 双边际 + digest 不变 = 8dfe3471…c457）
RA_TRIB_001                 = PASS（first omen 10_000_000；tick0 episodes 0）
TEST_PROFILE_REFERENCES_IN_BOOTSTRAP = 0
MATERIALIZER_PRESENT        = FALSE
candidate build reproducible= PASS
SNAPSHOT_V1_CANDIDATE 只补 metadata：分配矩阵 digest 与内容不变（M6C.1B §28）
```

全系列合并回归（M6A + M6B + M6C.1 + M6C.1B + seed safety）：

```
RESULT     = PASS（exit code 0）
COLLECTED  = 177
PASSED     = 177
FAILED     = 0
ERRORS     = 0
```

未修改 simulation production semantics → 按 owner §27 **无需** canonical full fast regression。

## 7. 未做（owner §25/§26）

```
未实现 materializer      未激活世界      未消费 Seed      未写正式库      未部署 live
未删除/覆盖/迁移 legacy stale DB       未把测试档当正式档       未引入任何未批准数值
```

```
STOP。不得实现 materializer。不得激活世界。等待主人对 OD-1..OD-9 的裁决。
```
