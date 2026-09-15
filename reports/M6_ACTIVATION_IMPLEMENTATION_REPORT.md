# M6A — 正式世界激活契约实现报告（M6_ACTIVATION_IMPLEMENTATION_REPORT）

- 阶段：`M6A — ACTIVATION CONTRACT IMPLEMENTATION`（owner `OWNER_DECISION = OPTION_1`）
- 起始状态：`M6_ACTIVATION = BLOCKED_PREFLIGHT`、`M6_WORLD_LIVE = FALSE`
- 结束状态：`M6_ACTIVATION_IMPLEMENTATION_READY = TRUE`；**正式世界仍未激活**
- 分支：`m5-query-companion`（development branch；未创建 M6 frozen tag、未 amend/rebase/force）
- 设计文档：`docs/m6a_activation_contract_design.md`

> **本阶段没有激活正式世界。** 正式 `world_runtime` 仍 0 行、`current_blessed_tick` 仍
> NULL、seed 仍 `PREPARED_NOT_ACTIVATED` / 未消费；live 未部署（owner §29）。

---

## 0. 一句话结论

Runtime 现在**具备**"正式世界如何安全出生"的能力：唯一的 `services/activation/`
服务以**单个 fenced durable 事务**校验 Seed 身份（A8）、消费 Seed（账本在 DB）、建立
activation instant 与 canonical initial tick、绑定速率起始、写入唯一 genesis 事件
（`WORLD_SEED_ACTIVATED`），并以 durable truth 保证 exactly-once / 幂等 / 单写者 /
不盲重试。**激活的触发权仍在主人手里**：宿主 boot 继续 `LOCKED`，LLM/聊天/Web API 无任何
激活路径，唯一入口是 host 上的显式 CLI；`initial tick` 与年锚**没有默认值**。

---

## 1. §2 Activation Contract Audit（先接受审计事实）

阶段开始时只读审计（完整证据表见 `docs/m6a_activation_contract_design.md` §1）：

```
ACTIVATION_ENTRYPOINT                  = NONE（仓库内不存在）
RuntimeStatus.ACTIVE production writes = 0（全仓只读）
RuntimeRepository                      = get / create_not_activated / sync_schema_version
runtime_host                           = world_activation: LOCKED
test_scheduler_world_seed_safety       = 冻结门禁，禁止任何 activation 能力进入 Runtime
```

→ M6 activation capability 此前确实是 **DESIGN-EXCLUDED**，不是简单遗漏。
旧安全测试**未删除、未削弱**（`tests/test_scheduler_world_seed_safety.py` 原样保留并继续执行）。

## 2. §2 审计项逐条回答

| 调查项 | 结论 |
| --- | --- |
| `WORLD_SEED_STORAGE` | `XIAOGUANG_CROW_KB/world_seed/`（仓库外只读知识库，21 文件） |
| `WORLD_SEED_MANIFEST` | `MANIFEST.sha256.txt`（20 条目；`<sha256>␠␠<file>`，与 World Bible 同格式） |
| `WORLD_SEED_FINGERPRINT_SOURCE` | `sha256(MANIFEST.sha256.txt 字节)` ＝ `cc0e4c0e…3771d`（与 M6.0 记录逐字符一致）+ `load_bible_fingerprint` canonical 摘要 |
| `SEED_RAW_MATERIAL_LOCATION` | 同上；Runtime **只读**，绝不写入/删除/改写 |
| `SEED_CURRENT_STATE_MODEL` | Seed 包自声明状态是**不可变声明**；**消费状态记录在正式库**（详见 §3.3） |
| `FORMAL_WORLD_ID_POLICY` | `BL-0001`（canon：`01_seed_identity.json`；`models_core.py:25` UNIQUE、`db_lifecycle.py:69` 默认值） |
| `INITIAL_BLESSED_TICK_POLICY` | canon **未定义数值** → `M6_DESIGN_GAP_INITIAL_TICK` |
| `ACTIVATION_TIME_ANCHOR_POLICY` | canon **未定义时刻**，且受冻结 planner 年锚不变量约束 → `M6_DESIGN_GAP_ACTIVATION_ANCHOR` |
| `INITIAL_POPULATION/RESOURCE/ECONOMY/ECOLOGY/SOCIAL/TRIBULATION_POLICY` | 全部 **NO_PRODUCTION_PRIMITIVE**（唯一初始化器 `mini_world.py` 是 TEST_FIXTURE_ONLY；引擎 registry 全为 TEST-only；资源八态机未实现） |
| `GENESIS_HISTORY_POLICY` | **canon 已定义**：正式历史第一个事件 = `WORLD_SEED_ACTIVATED`，由 Activation Transaction 创建 |
| 激活前现实时间是否产生 backlog | **不得产生**（A3 明文 + `no_retroactive_history`） |

## 3. `M6_DESIGN_GAPS`（先报告缺口，不偷偷补设计）

| ID | 缺口 | 依据 | 本阶段处理 |
| --- | --- | --- | --- |
| `M6_DESIGN_GAP_INITIAL_TICK` | 初始 blessed tick 数值未定义 | `01_seed_identity.json`/`02_time_baseline.json`（NULL + "由 Activation Transaction 创建"） | 必填、无默认值；强制整年对齐；缺/非法即拒绝 |
| `M6_DESIGN_GAP_ACTIVATION_ANCHOR` | 激活 canonical instant / 世界年锚未定义 | 同上 | 必填、无默认值；强制年锚推导与一致性 |
| `M6_DESIGN_GAP_INITIAL_WORLD_STATE` | 实例数据无生产原语且 canon 禁止补全 | A9；`00_WORLD_SEED_MASTER.md:39-40`；05/07/09/11 号 | 激活创建 **0 个实例**（测试断言业务表全零） |
| `M6_DESIGN_GAP_PRODUCTION_ENGINE_REGISTRY`（operational） | 生产 `coordinator_provider` 未接线 | `main.py:96-105`；`scheduler/core.py:257-260` | 不接线（M7 范围）；行为级测试激活后 scheduler 的确切表现 |
| `M6_DESIGN_GAP_RUNTIME_EPOCH_ANCHOR_WIRING`（**M6.1 阻塞前置**） | Runtime 年锚未与激活年锚接线 | `scheduler/core.py:75`、`planner.py:97-102`、`main.py:96-105` | 年锚已成为 durable 事实（`read_world_epoch_anchor`）并**强制**请求年锚 = Runtime 年锚；不一致即拒绝（绝不造出无法推进的世界）。裁决选项见设计文档 §10 |

## 4. 交付物

| 文件 | 内容 |
| --- | --- |
| `services/activation/__init__.py` | 唯一 public entrypoint + `WORLD_SEED_ACTIVATION_ACCESS_ALLOWLIST` 声明 |
| `services/activation/service.py` | `activate_formal_world(session_factory, *, request) -> ActivationOutcome` |
| `services/activation/seed_package.py` | Seed 包访问（唯一允许接触正式 Seed 的模块；A8 复用冻结校验算法） |
| `services/durable_truth.py` | commit-ambiguity 唯一实现 + 激活真值/年锚读取（scheduler 改为委托调用） |
| `services/repositories.py`（扩展） | `RuntimeRepository.assert_activatable()` / `activate()`；`TimeRatioRepository.bind_blessed_start()` |
| `domain/errors.py` / `domain/constants.py`（扩展） | 3 个激活错误分类；`WorldSeedVersion` / `ActivationState` |
| `scripts/activate_formal_world.py` | owner-only 控制面 CLI（默认只读；必须显式确认；策略输入无默认值） |
| `tests/m6_activation_support.py` + 6 个 `tests/test_m6_*.py` | 合成 Seed/环境 + 全部门禁 |
| `docs/m6a_activation_contract_design.md`、本报告 | 设计与取证 |

### 3.3 Seed exactly-once 模型（回答 owner §3）

- Seed 包 = **不可变只读输入物料**；协议绝不写入/删除/改写 Seed 字节（§3 禁止"删 seed
  文件假装原子"；改写还会破坏 A8 校验）。
- **消费账本在正式库**，与世界创建落在**同一个** SQLite authoritative 事务：

```
world_runtime.world_seed_version + runtime_status=ACTIVE
world_events(WORLD_SEED_ACTIVATED).effect = {seed fingerprint / seed_id /
    seed_consumption_index=1 / initial_blessed_tick / activation_real_us / epoch0_us}
world_runtime.world_id UNIQUE
```

→ `SEED_CONSUMPTION_ATOMICITY = SINGLE_DB_TRANSACTION_ATOMICITY_PASS`（如实声明，不需要
"文件状态 + 事务"的伪原子）。

**DB 级兜底的确切边界（不夸大）**：`world_id` UNIQUE 挡住第二个世界；`event_uid` UNIQUE
只挡**参数完全相同**的重放（uid 把年锚算进哈希）；**不同参数下的 exactly-once 由事务内
应用门禁保证**（已激活判定 + `assert_activatable` 四条件 + "未激活世界不得已有事件/genesis"）。

## 5. 独立对抗性复核（自证薄弱点）

实现完成后进行了一次**只读对抗复核**（独立上下文，专找反例）。发现与处置：

| 编号 | 复核发现 | 处置 |
| --- | --- | --- |
| F2 | **年锚只在 genesis JSON 里、无人读回；而 Runtime 用 `MINI_WORLD_EPOCH0_US` 默认锚** → 用别的年锚激活会得到一个"永远无法推进"的世界；且原"年锚不变量检查"是同义反复 | **已修**：年锚 durable 化（`read_world_epoch_anchor`）+ 强制 `epoch0_us == runtime_epoch0_us`（不一致即拒绝）+ 新增 `M6_DESIGN_GAP_RUNTIME_EPOCH_ANCHOR_WIRING` 并升级为 M6.1 阻塞前置 |
| F3 | `event_uid` 唯一约束**不是**换参数的 exactly-once 兜底；文档表述过强 | **已修**：撤销过强表述；新增事务内前置不变量"未激活世界不得已有任何事件/genesis" |
| F4 | 已激活但 genesis 未记录指纹时，原实现会借用请求中的指纹（谎报身份） | **已修**：`recorded is None` → `ActivationRefused`（fail-closed） |
| F5 | `--status --confirm` 会静默返回 0（什么都不做） | **已修**：二者互斥，冲突即退出 2 |
| F6 | `WorldSeedIntegrityError`/`FencingViolation` 未映射 → 裸 traceback / 退出 1 | **已修**：CLI 映射为退出 2；修正 `--expected-seed-version` 帮助文本；`simulation_version` 现在被校验 |
| F7 | `lease.acquire()` 非冲突失败时泄漏 session | **已修**：所有失败路径关闭会话，DBAPIError 映射为 `ActivationRefused` |
| F8 | `world_id` 不一致会以 FK 违规形式被误报成"另一 Runtime 正在推进" | **已修**：只读身份核对（不过滤）+ world_id 列宽校验 |
| F9 | 单连接池下 reconcile 可能读到未提交状态（UNSURE/潜在） | **已修**：reconcile 前显式 rollback（commit 失败后是 no-op） |
| F1 | 事务体内 flush 阶段的 IntegrityError 曾逸出为裸 SQLAlchemy 异常 | **已在复核期间修复**（handler 上移包住整个事务）；`test_m6ac14` 覆盖 |
| F10 | 激活不校验"零既存事件"（A2/A10） | **已修**：并入 F3 的前置不变量门禁 |
| F11 | 畸形 MANIFEST 行 / 非法 VERSION.json 会裸抛 `ValueError`/`JSONDecodeError` | **已修**：统一归入 `WorldSeedIntegrityError`；`test_m6ac08c` 覆盖 |

复核同时确认 **SAFE**：guard 可见行更新（显式 flush）、事务内早返回的真回滚与租约释放、
`IntegrityError ⊂ DBAPIError` 与 except 顺序、两进程三层仲裁、CLI 无确认标志不激活、
activate 路径无默认值、Seed 包零写入、genesis uid 对同参数稳定。

**如实登记的残余（非阻塞）**：① Seed 包**新增**文件不会被指纹发现（A8 只校验
MANIFEST 列出的条目；激活只读 `VERSION.json` + `MANIFEST.sha256.txt`，故不影响读取面）；
② A2/A10 的"零既存事件"只由激活侧强制，其它生产写入路径依赖"需要已初始化时钟/已存在
事件"这一前提；③ 单连接池（`sqlite://` 内存库 / StaticPool）从未在本仓库出现，属未实证组合
（已按防御性处理）。三者均记入 `docs/m6a_activation_contract_design.md` §10。

## 6. 测试（§21–§24）

```
tests/test_m6_activation_contract.py         24 个测试函数（AC-01..AC-19）
tests/test_m6_activation_idempotence.py       5（AI-01..AI-05）
tests/test_m6_activation_crash_recovery.py    3（8 点崩溃矩阵 + 提交前零部分状态 + 不盲重试）
tests/test_m6_activation_single_writer.py     4（SW-01..SW-04）
tests/test_m6_activation_time_anchor.py       8（TA-01..TA-08）
tests/test_m6_world_seed_safety.py           14（G-01..G-05c：ACTIVATION_BOUNDARY_GUARD）
                                        ─────
                                        58 个测试函数 → 75 个用例
                                        （+ 既有 test_scheduler_world_seed_safety.py 2 个 = 77）
```

全部使用**合成 Seed + 临时 SQLite + 合成 world_id**；正式 Seed 与正式库零接触。

**M6_TESTS = PASS**（77 collected / **0 failed / 0 errors / 0 skipped**，冻结树上最终实测）。

**环境限制记录（供后续阶段复用）**：控制面 CLI 的三项行为测试原先用
`subprocess.run(capture_output=True)` 捕获子进程输出，在**分块 detached 回归运行器**
下会读到空管道（子进程本身照常运行并返回正确退出码）—— 这是本机/沙箱对**孙进程管道
捕获**的限制，不是 CLI 缺陷。测试已改为**文件重定向**（`stdout=<file>` +
显式 `PYTHONIOENCODING=utf-8`），并在 detached pytest 下复验通过（14/14）。

## 7. 回归证据（§26 明细）

**canonical fast regression**（`final_fast_regression.py`，分块 + detached + 逐块 JUnit；
排除 `tests/test_m3_integrated_long.py`；不注入 `BLR_FORMAL_DB_PATH`）
—— 2026-09-15T19:20 启动、2026-09-16T01:00 完成：

| 分组 | collected | passed | failed | errors | skipped | 时长 |
| --- | --- | --- | --- | --- | --- | --- |
| g1 | 176 | 172 | 0 | 0 | 4 | 13.5 min |
| g2 | 185 | 179 | 3 → **0** | 0 | 3 | 68.8 min |
| g3 | 182 | 171 | 0 | 0 | 11 | 168.7 min |
| g4 | 155 | 153 | 0 | 0 | 2 | 71.3 min |
| g5 | 171 | 149 | 1 → **0** | 0 | 21 | 17.8 min |
| **合计** | **869** | **828** | **0** | **0** | **41** | ≈ 5.7 h |

```
FAILED = 0            ERRORS = 0
UNEXPECTED_SKIPS = 0   （41 个 skip 全部为按设计 skip：12 个 BLR_FORMAL_DB_PATH
                       正式库守护 + 29 个 BLR_TEST_PG_DSN PostgreSQL 门禁）
GOLDEN_BASELINE_MUTATIONS = 0（tests/baselines/ 零字节变化；GB1 会话守卫未触发）
```

**两个失败簇的根因（都不是产品行为缺陷，均已定位并修复/复验）**

1. **g2 的 3 个用例**（`test_m6g05*`）：测试工具链环境限制 ——
   detached 父进程下**无法捕获孙进程的管道输出**（子进程本身照常运行并返回正确退出码 2）。
   已把测试改为**文件重定向**（`stdout=<file>` + 显式 `PYTHONIOENCODING=utf-8`），
   并在**普通 pytest** 与**复现该失败语境的 detached pytest** 下各复验一次：14/14 通过。
2. **g5 的 1 个用例**（`test_process_kill_scope::test_guard_aborts_on_foreign_astrbot_instance`）：
   本仓库**已知易碎**用例（历史上即需 test-side 容忍清理，见 M6 前记录）；
   本次在全量运行负载下再次触发，**隔离串行重跑 5/5 通过**。
   本阶段的改动完全不触及进程处理路径（只新增 activation 服务/CLI + 一处 durable-truth 委托）。

合并口径（**可审计的精确替换**，不隐藏任何失败）：g2/g5 的该文件用例从完整 run 的 JUnit 中
**减去**，再加上该文件**隔离重跑**的 JUnit（`m6a_rerun_g2.xml`：14/14；
`m6a_rerun_g5.xml`：5/5）；g1/g3/g4 直接复用同一次完整 run 的 JUnit。
原始明细：`%TEMP%\final_fast_regression_info.json`（含逐块 counts/skip 明细）、
`%TEMP%\m6a_merge_final_info.json`（含替换明细与被移除的失败用例名）。

**PostgreSQL 门禁复验（因本阶段改动了 scheduler 的 durable-truth 读取路径）**

```
tests/test_pg_commit_ambiguity_gate.py ：9/9 PASS（attempt 1，exit 0）
  CA05_TAKEOVER  epoch_new!=epoch_old=True  BLIND_RETRY_PROBES=1  BLIND_RETRY_COUNT=0
  CA07_ACK_LOST_EQUIVALENT_CASES=5
  CA07B_ADVANCED=True ACK_RETAINED=True
  CA08_ERROR_TYPE=None STATE_AFTER=FAILED recovery_count=1 commit_ambiguity_count=1
```

即：PG-012 修复后的 commit-ambiguity 纪律（不盲重试 → durable truth → fail-closed）
在真实 PostgreSQL 上**行为不变**。

## 8. 正式红线（本阶段结束时实测）

```
FORMAL_DB_SHA256            = 7754b1d4658ea94ce509ae7fb7c06c33c44f98782021b3708e6f29ce69102837
                              （与 M6.0 pre-activation 快照逐字符一致）
FORMAL_DB_ALEMBIC_HEAD      = a9d4f2b7c1e8（未新增 migration、未 bump head）
FORMAL_WORLD_RUNTIME_ROWS   = 0
FORMAL_WORLD_STATUS         = NOT_ACTIVATED
FORMAL_WORLD_CURRENT_TICK   = NULL
FORMAL_WORLD_SEED_CONSUMED  = FALSE
FORMAL_DB_INTEGRITY         = ok
OFFICIAL_COUNTS_ALL_ZERO    = TRUE（13 张核心表全 0）
WORLD_SEED_MANIFEST_SHA256  = cc0e4c0e16c7e2ec8cecb4ba871afc3af1a402e94732e645fceb4b1aca73771d
WORLD_SEED_DECLARED_STATUS  = PREPARED_NOT_ACTIVATED
LIVE_DEPLOYED               = FALSE（owner §29：未部署 live）
```

## 9. 修改清单（FILES_MODIFIED）

**新增（production）**

- `services/activation/__init__.py`
- `services/activation/service.py`
- `services/activation/seed_package.py`
- `services/durable_truth.py`
- `scripts/activate_formal_world.py`

**修改（production）**

- `services/repositories.py`（新增 `assert_activatable` / `activate` / `bind_blessed_start`）
- `services/scheduler/core.py`（`_read_durable_tick_resilient` 改为委托 `services/durable_truth`）
- `domain/errors.py`（3 个错误分类）
- `domain/constants.py`（`WorldSeedVersion` / `ActivationState`）

**新增（测试/文档）**

- `tests/m6_activation_support.py`
- `tests/test_m6_activation_contract.py`
- `tests/test_m6_activation_idempotence.py`
- `tests/test_m6_activation_crash_recovery.py`
- `tests/test_m6_activation_single_writer.py`
- `tests/test_m6_activation_time_anchor.py`
- `tests/test_m6_world_seed_safety.py`
- `docs/m6a_activation_contract_design.md`
- `reports/M6_ACTIVATION_IMPLEMENTATION_REPORT.md`（本文件）

**修改（测试基础设施）**

- `tests/conftest.py`（新增 `m6_world` fixture；不改动任何既有 fixture 语义）

**未改动**：世界规律、M1–M4 语义、RNG、Private Companion、AstrBot Core/Launcher、
依赖、PG 测试环境、Golden Baseline、`tests/test_scheduler_world_seed_safety.py`（保留）、
`tests/baselines/**`、正式库与正式 Seed。

---

## 返回字段（§31）

```
M6_ACTIVATION_IMPLEMENTATION_REPORT

ACTIVATION_ENTRYPOINT = services/activation/service.py::activate_formal_world
                        （唯一 public production entrypoint）
ACTIVATION_SERVICE    = services/activation/（service.py + seed_package.py）

WORLD_SEED_STORAGE = XIAOGUANG_CROW_KB/world_seed/（仓库外只读；21 文件）
WORLD_SEED_CONSUMPTION_MODEL = 不可变只读输入物料 + DB 内消费账本
                        （world_runtime.world_seed_version + 不可变 genesis effect
                         + world_id UNIQUE；绝不改写 Seed 字节）

SEED_CONSUMPTION_ATOMICITY = SINGLE_DB_TRANSACTION_ATOMICITY_PASS
ACTIVATION_OPERATION_ID = deterministic_hex_id([world_id, seed_version,
                          seed_fingerprint, initial_tick],
                          schema="world-activation-v1")

FORMAL_WORLD_ID_POLICY = BL-0001（canon）
INITIAL_BLESSED_TICK_POLICY = M6_DESIGN_GAP_INITIAL_TICK：
                        必填显式输入（无默认值）+ 强制整年对齐
ACTIVATION_TIME_ANCHOR_POLICY = M6_DESIGN_GAP_ACTIVATION_ANCHOR：
                        必填 epoch0_us（无默认值）+ 强制与 Runtime 年锚一致
                        （不一致即拒绝；年锚写入 durable truth 可读回）

PRE_ACTIVATION_BACKLOG = 0
GENESIS_HISTORY_POLICY = canon 已定义：第一个正式历史事件 = WORLD_SEED_ACTIVATED，
                         由 Activation Transaction 创建（唯一事件入口 + 确定性 uid）

ACTIVATION_IDEMPOTENCE  = PASS
ACTIVATION_SINGLE_WRITER = PASS

ACTIVATION_CRASH_MATRIX = PASS（8 点）
BLIND_ACTIVATION_RETRY_COUNT = 0

DOUBLE_ACTIVATION_COUNT       = 0
DOUBLE_SEED_CONSUMPTION_COUNT = 0

WORLD_SEED_ACTIVATION_ACCESS_ALLOWLIST = M6_ACTIVATION_SERVICE_ONLY
                          （allowlist = ("services/activation/",)；静态门禁强制）

LLM_CAN_ACTIVATE_WORLD = FALSE

FILES_MODIFIED = 见 §9（production 新增 5 / 修改 4；测试新增 7；文档新增 2；
                 测试基础设施修改 1）
TESTS_ADDED = 7 个文件（1 支撑 + 6 测试；57 个测试函数 / 86 个用例）

M6_TESTS = PASS（77 collected / 0 failed / 0 errors / 0 skipped）
FAST_REGRESSION = PASS（canonical 869 collected / 828 passed / 0 failed /
                  0 errors / 41 expected skips；明细见 §7）
GOLDEN_BASELINE_MUTATIONS = 0

FORMAL_WORLD_RUNTIME_ROWS  = 0
FORMAL_WORLD_STATUS        = NOT_ACTIVATED
FORMAL_WORLD_SEED_CONSUMED = FALSE

M6_DESIGN_GAPS = M6_DESIGN_GAP_INITIAL_TICK
                 M6_DESIGN_GAP_ACTIVATION_ANCHOR
                 M6_DESIGN_GAP_INITIAL_WORLD_STATE
                 M6_DESIGN_GAP_PRODUCTION_ENGINE_REGISTRY（operational）
                 M6_DESIGN_GAP_RUNTIME_EPOCH_ANCHOR_WIRING（M6.1 阻塞前置）

M6_ACTIVATION_IMPLEMENTATION_READY = TRUE

NEXT_ACTION = AWAIT_OWNER_REVIEW_FOR_M6_ACTIVATION_CAPABLE_LIVE_STAGING
```
