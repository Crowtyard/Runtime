# M6B — ACTIVATION BOOTSTRAP & EPOCH CLOSURE 报告（M6B_BOOTSTRAP_AND_EPOCH_CLOSURE_REPORT）

- 阶段：`M6B`（owner：`M6A_ACTIVATION_CONTRACT_IMPLEMENTATION = ACCEPTED`；
  `M6_ACTIVATION_CAPABLE_LIVE_STAGING = NOT_YET_AUTHORIZED`）
- 分支：`m5-query-companion`（development branch；未创建 M6 frozen tag、未 amend/rebase/force）
- 设计/审计：`docs/m6b_bootstrap_and_epoch_audit.md`
- **正式世界仍未激活**：0 行 / tick NULL / seed 未消费；live 未更新（仍为 PRE-M6 staged Runtime）

## 0. 一句话结论

**Epoch 侧收口成功，Bootstrap 侧受阻。**

- `EPOCH_WIRING = PASS`：RuntimeScheduler 现在从 durable truth 读取世界年锚（OPTION A），
  不再依赖 `2026-01-01Z` 固定锚；restart / 进程替换 / 不同墙钟读回**完全相同**的 anchor，
  且年锚/时钟不自洽时 fail-closed（绝不偷偷 repair）。`WAIT_FOR_2027_01_01_ACTIVATION = REJECTED`
  已落实：Runtime correctness 不再依赖任何特定现实日期。
- `EMPTY_WORLD_CAN_BOOTSTRAP = FALSE`：一个**完全为空**的已激活世界能被冻结管线
  **合法推进**（零异常、确定性、零悬空引用），但**永远不会形成任何域状态** ——
  人口/资源/经济/生态/社会/灾劫/历史实体恒为 0，只有 `TIME_ADVANCE` 空转。
  因此 `M6_DESIGN_GAP_INITIAL_WORLD_STATE = BLOCKING`、`M6B_READY = FALSE`、
  `M6_ACTIVATION = BLOCKED_DESIGN`（**不是代码失败**）。

## 1. Owner canon 决策落地

| 决策 | 实现 |
| --- | --- |
| `INITIAL_BLESSED_TICK = 0` | `domain.constants.WorldActivationPolicy.INITIAL_BLESSED_TICK`；契约拒绝任何非 0 取值；未激活仍为 NULL（**NULL ≠ 0**） |
| activation anchor = 显式 durable UTC instant | `ActivationRequest.activation_anchor_us`（CLI：`--activation-anchor-utc` / `--activation-anchor-us`，**拒绝隐式 now()**）；写入 genesis `effect.activation_anchor_us`；`read_world_epoch_anchor()` 为唯一读法 |
| 一次 operation 只确定一次 anchor | 重试**必须复用同一 anchor**：同值 → `ALREADY_COMMITTED`（零写入）；异值 → `ActivationRefused`（**loser 不得覆盖 anchor**） |
| `WAIT_FOR_2027_01_01_ACTIVATION` | `REJECTED`（年锚由 activation 显式确立，不再等待特定现实日期） |

## 2. Epoch Wiring（OPTION A）实现

```
RuntimeScheduler(epoch0_us=None)  →  动态模式（生产：main.py 不传 epoch0）
   world NOT_ACTIVATED → DEFAULT_OPERATIONAL_EPOCH0_US（既有 operational 默认；DORMANT 路径）
   world ACTIVATED     → durable_truth.read_world_epoch_anchor()   ← 唯一来源
                         读不到 → _fail(...)（FAILED，零写入，绝不按 now() 重建）
```

- 生效年锚**每 cycle** 从 durable truth 解析（planner 按 anchor 值缓存，不缓存 anchor 真值）；
- 规划阶段异常 → FAILED（fail-closed）；显式传入 `epoch0_us` 的既有 M4 路径行为逐字不变；
- 批次执行把**同一个**生效年锚交给冻结 `run_blessed_year`（年锚对齐不变量）。

## 3. Bootstrap Viability Audit（经验证据）

synthetic activation world（tick=0，anchor 显式）→ 业务表全空 → 冻结生产管线
（`PopulationGroupEngine` / `ResourceEngine` / `EconomyEngine` / `EcologyEngine` /
`SocialEngine` + `TribulationEngine` + `DOMAIN_ADAPTERS` + `HistoryLinkBuilder`）
经生产适配器逐年推进 4 年：

```
NO_EXCEPTION = TRUE         DETERMINISTIC = TRUE（两次独立运行逐字节一致）
NO_INVALID_REFS = TRUE      NO_DIVIDE_BY_ZERO = TRUE
NO_M2M3_INVARIANT_VIOLATION = TRUE
CLOCK = tick 4,000,000；cursor = anchor + 4×YEAR_US（年锚对齐）
EVENTS = WORLD_SEED_ACTIVATED ×1 + TIME_ADVANCE ×4（零域事件）
ENTITIES = 全部 0（人口/资源/经济/生态/社会/灾劫/历史实体与因果链接）
HISTORY_INDEX_WATERMARK = 4,000,000（索引水位随时钟推进，但零历史被建立）
```

→ 空世界"不崩但永远空"：**永久空世界**（与 §8 的 no permanent dead world 冲突）。

## 4. WORLD SEED 物化审计（§10/§11）

只读统计 21 个设计文件的**状态元数据**（不据"文件里出现数字"就写正式 DB）：

| 域 | seed 文件 | 判定 |
| --- | --- | --- |
| 身份 / 时间规则 | 01 / 02 | `CANONICAL`（规则）；初始 tick/anchor 由 owner canon 决定 |
| 地理 | 03 | `CANONICAL`（静态 canon）+ `PLANNING_ONLY`（规划分带槽，名称 UNDECIDED） |
| **人口** | 04 | **`PLANNING_ONLY`**（总人口为规划值；无 cohort/年龄组/职业组分解） |
| 物种 | 05 | `APPROVED_LOCAL_DESIGN`（候选身份）+ `UNDEFINED`（population_share 未定） |
| 聚落 | 06 | `PLANNING_ONLY`（槽位数量级；NAME=UNDECIDED） |
| 社会结构 | 07 | `APPROVED_LOCAL_DESIGN`（四层模型/自治原则）+ `UNDEFINED`（实例 0） |
| 经济 | 08 | `APPROVED_LOCAL_DESIGN`（规则）+ `UNDEFINED`（无初始库存/产能数据） |
| 资源 | 09 | `APPROVED_LOCAL_DESIGN`（类型/八态机）+ `UNDEFINED`（实例 0） |
| 生态 | 10 | `APPROVED_LOCAL_DESIGN`（区类型）+ `UNDEFINED`（无初值） |
| 机构 | 11 | `PLANNING_ONLY` / `UNDEFINED`（实例 0） |
| 初始事件边界 | 12 | `CANONICAL`（`WORLD_SEED_ACTIVATED`） |
| UNKNOWN 注册表 | 13 | `UNDEFINED`（A9 必须保持 UNKNOWN） |
| 激活不变量 | 14 | `CANONICAL`（A1–A10） |

```
WORLD_SEED_BOOTSTRAP_SPEC_STATUS = ABSENT
```

## 5. MINIMUM_REQUIRED_BOOTSTRAP_STATE（结构性，不含数值）

1. **聚落根**（settlements）——各域共同轴；
2. **人口根**（population_groups：物种×聚落×年龄组×职业组）；
3. **资源节点根**（resource_nodes + 有效 `resource_profile_ref`）；
4. **经济状态根**（resource_stocks + production_recipes/state + economic_pressure_state）；
5. **生态根**（ecology_zones + ecology_state + ecology_feedback_state）；
6. **社会状态根**（settlement_social_state + social_feedback_state，每聚落）；
7. **灾劫配置根**（tribulation_profiles + tribulation_schedules）；
8. **正式 profile registry（五域）** —— 生产引擎目前不存在正式 registry
   （`TEST_PROFILES` / `TEST-SPECIES-001` / `TEST-ECONOMY-PROFILE-001` 等皆为测试夹具；
   `TribulationEngine` 默认用 `TEST_PROFILES`，DB 行不参与 lookup）。

探针证据：完整 mini world 基线**会**产生域事件；逐一移除后 —— 缺社会状态/resource stock/
ecology state → 冻结引擎 fail-closed；缺人口根/灾劫排期 → 不报错但该域**永不产出**。

## 6. 测试与回归

```
M6 + M6B 套件：113 collected / 0 failed / 0 errors / 0 skipped
  M6A（77）：contract / idempotence / crash / single-writer / time-anchor / boundary guard
  M6B（36）：epoch wiring（8）、anchor atomicity + crash matrix（13）、
             bootstrap viability（15）

§19 列出的调度/时间/恢复/DB 套件（17 个文件）：
  109 collected / 109 passed / 0 failed / 0 errors / 0 skipped（21 分钟）
  （含 test_scheduler_lifecycle/catchup/dormant_gate/crash_recovery/commit_ambiguity/
    ack_lost/fencing/single_writer/observability/pause_resume/determinism/
    writer_recovery + test_time_engine/test_catchup/test_fencing/test_guards/
    test_database）

FAST_REGRESSION = PASS
  canonical fast regression：906 collected / 865 passed / 0 failed / 0 errors /
  41 skipped（41 = 12 个 BLR_FORMAL_DB_PATH 正式库守护 + 29 个 BLR_TEST_PG_DSN
  PostgreSQL 门禁；UNEXPECTED_SKIPS = 0）
  逐组：
    g1  183 / 170 / 0 / 13  ← **canonical-sequential**（规范运行器顺序执行）
    g2  199 / 196 / 0 /  3  ← parallel harness（同一 chunks() 文件列表与 JUnit 格式）
    g3  187 / 167 / 0 / 20  ← parallel harness
    g4  174 / 173 / 0 /  1  ← parallel harness
    g5  163 / 159 / 0 /  4  ← parallel harness
  说明：本阶段新增 3 个测试文件使 runner 的 61 文件分组重排，group 1 落到
  2.8 小时级的 1000 年预算等价测试上；为压缩墙钟并规避长时运行被环境信号打断的
  风险，group 2–5 改用**同一运行器**的并行 harness 执行（并发只会让用例更严苛，
  不会放松判定）。**本次未使用任何"精确替换"**——所有分组均为直接通过。

GOLDEN_BASELINE_MUTATIONS = 0（tests/baselines 零字节变化；GB1 会话守卫未触发）
```

**测试侧适配（非语义变更）**：`_execute_batch` 新增「生效年锚」参数后，
两处测试内 monkeypatch 需同步签名（`test_scheduler_ack_lost.py`、
`test_scheduler_commit_ambiguity.py`）——这是 M6B §3「批次必须用同一个生效年锚」
的直接后果，冻结的 catch_up/planner/time_engine 语义未改动。

## 7. 修改清单

**production（4 文件修改，无新增）**

- `services/scheduler/core.py`：OPTION A 年锚接线（`_effective_epoch0_us` / `_planner_for`）、
  规划阶段 fail-closed、`_execute_batch(plan, epoch0_us)`、`DEFAULT_OPERATIONAL_EPOCH0_US`
- `services/activation/service.py`：owner canon（tick=0 强制；`activation_anchor_us`；
  anchor 一致性拒绝；genesis effect 记录 anchor + policy）
- `scripts/activate_formal_world.py`：`--activation-anchor-utc` / `--activation-anchor-us`
  （显式 anchor，拒绝隐式 now()）；状态输出读回 durable anchor
- `domain/constants.py`：`WorldActivationPolicy`（INITIAL_BLESSED_TICK / ANCHOR_POLICY）

**tests（M6B 新增 3 + M6A/M4 适配 6）**

- 新增：`tests/test_m6b_epoch_wiring.py`、`tests/test_m6b_anchor_atomicity.py`、
  `tests/test_m6b_bootstrap_viability.py`
- 适配：`tests/m6_activation_support.py`、`tests/test_m6_activation_contract.py`、
  `tests/test_m6_activation_idempotence.py`、`tests/test_m6_activation_time_anchor.py`、
  `tests/test_m6_world_seed_safety.py`（CLI 标志）、`tests/test_scheduler_ack_lost.py`、
  `tests/test_scheduler_commit_ambiguity.py`（monkeypatch 签名）

**docs（新增 2 + 追加说明 2）**

- 新增：`docs/m6b_bootstrap_and_epoch_audit.md`、本报告
- 追加 M6B 后续说明：`docs/m6a_activation_contract_design.md`、
  `reports/M6_ACTIVATION_IMPLEMENTATION_REPORT.md`

**未改动**：`main.py`（生产路径本来就不传 epoch0 → 自动进入动态模式）、
World Seed 包、正式库、live、Golden Baseline、`tests/baselines/**`、
任何 YEAR_US / time-ratio / offline-catchup / 整数有理时间语义。

## 8. 正式红线（本阶段结束时实测）

```
FORMAL_WORLD_RUNTIME_ROWS  = 0
FORMAL_WORLD_STATUS        = NOT_ACTIVATED
FORMAL_WORLD_CURRENT_TICK  = NULL
FORMAL_WORLD_SEED_CONSUMED = FALSE
FORMAL_DB_SHA256           = 7754b1d4658ea94ce509ae7fb7c06c33c44f98782021b3708e6f29ce69102837
                             （与 M6.0 快照一致；本阶段未新增 migration）
WORLD_SEED_MANIFEST_SHA256 = cc0e4c0e16c7e2ec8cecb4ba871afc3af1a402e94732e645fceb4b1aca73771d
WORLD_SEED_STATUS          = PREPARED_NOT_ACTIVATED
LIVE_DEPLOYED              = FALSE
```

---

## 返回字段（§24）

```
M6B_BOOTSTRAP_AND_EPOCH_CLOSURE_REPORT

OWNER_INITIAL_BLESSED_TICK     = 0
OWNER_ACTIVATION_ANCHOR_POLICY = EXPLICIT_DURABLE_ACTIVATION_UTC_INSTANT

EPOCH_WIRING              = PASS（OPTION A；year anchor 来自 durable truth）
DURABLE_ANCHOR_READ       = PASS（唯一读法 services/durable_truth.read_world_epoch_anchor）
RESTART_ANCHOR_EQUIVALENCE = PASS（restart / 进程替换 / 不同墙钟 → 同一 anchor）
PRE_ACTIVATION_BACKLOG    = 0

DEMOGRAPHY_EMPTY_BOOTSTRAP  = CANNOT_PROGRESS
RESOURCE_EMPTY_BOOTSTRAP    = CANNOT_PROGRESS
ECONOMY_EMPTY_BOOTSTRAP     = CANNOT_PROGRESS
ECOLOGY_EMPTY_BOOTSTRAP     = CANNOT_PROGRESS
SOCIAL_EMPTY_BOOTSTRAP      = CANNOT_PROGRESS
TRIBULATION_EMPTY_BOOTSTRAP = CANNOT_PROGRESS

EMPTY_WORLD_CAN_BOOTSTRAP   = FALSE
   （合法推进 + 确定性 + 零异常 + 零悬空引用 = TRUE；
     但零域状态形成、永久空世界 = 不可接受）

WORLD_SEED_BOOTSTRAP_SPEC_STATUS = ABSENT

INITIAL_POPULATION_SPEC  = PLANNING_ONLY
INITIAL_RESOURCE_SPEC    = APPROVED_LOCAL_DESIGN（类型/机制）+ UNDEFINED（实例初值）
INITIAL_ECONOMY_SPEC     = APPROVED_LOCAL_DESIGN（规则）+ UNDEFINED（初始数据）
INITIAL_ECOLOGY_SPEC     = APPROVED_LOCAL_DESIGN（区类型）+ UNDEFINED（初值）
INITIAL_SOCIAL_SPEC      = APPROVED_LOCAL_DESIGN（结构模型）+ UNDEFINED（实例）
INITIAL_TRIBULATION_SPEC = UNDEFINED

GENESIS_POLICY   = WORLD_SEED_ACTIVATED 是第一个正式事件（M6A 既有策略不变）
GENESIS_INTEGRITY = PASS（唯一 1 条；uid 确定性；cause 含 activation operation identity；
                         无孤儿 / 无环 / 无非法引用）

ACTIVATION_ATOMIC_FIELDS = PASS（六字段同一事务；崩溃注入下要么全无、要么全有）
CONCURRENT_ACTIVATION    = PASS（不同 anchor 并发 → winner=1；库中只有 winner 的
                           anchor；one genesis；one seed consumption）
ANCHOR_CRASH_MATRIX      = PASS（8/8；无 anchor duplication / mutation / loss）

M6_TESTS                  = PASS（113 collected / 0 failed / 0 errors / 0 skipped）
FAST_REGRESSION           = PASS（906 collected / 865 passed / 0 failed / 0 errors /
                             41 expected skips / 0 unexpected skips；见 §6）
GOLDEN_BASELINE_MUTATIONS = 0

FORMAL_WORLD_RUNTIME_ROWS  = 0
FORMAL_WORLD_STATUS        = NOT_ACTIVATED
FORMAL_WORLD_SEED_CONSUMED = FALSE

M6_DESIGN_GAP_INITIAL_WORLD_STATE = BLOCKING

M6B_READY = FALSE
   （成功分支 A 要求 EMPTY_WORLD_CAN_BOOTSTRAP = TRUE → 不成立；
     成功分支 B 要求存在 canonical bootstrap state → ABSENT；
     故落入阻塞分支：M6_ACTIVATION = BLOCKED_DESIGN，需主人进一步决定初始世界 canon）

NEXT_ACTION = AWAIT_OWNER_DECISION_ON_INITIAL_WORLD_STATE_CANON
```

## 需要主人决定的事项（三选一，本阶段**未**实现任何 materializer）

1. **授权"最小 bootstrap 规范 + materializer"子阶段**：明确正式世界出生时必须存在哪些根实体、
   由谁在哪个 sub-stage 物化、其 canonical 来源为何（含**五域正式 profile registry**）。
2. **显式授权修改冻结 M2 语义**（例如允许引擎从空世界自发生成初始实体）—— 本阶段明确不做，
   因为它会改变 M2/M3 的不变式。
3. **接受"空世界出生"** 并把世界内容整体推迟（当前证据：世界将永久为空、仅 `TIME_ADVANCE` 空转；
   与 §8 的 no permanent dead world 判定冲突，不建议）。

**STOP** — 未激活正式世界，未消费正式 World Seed，未部署 live。
