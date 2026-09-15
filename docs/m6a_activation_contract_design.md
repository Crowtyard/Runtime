# M6A — 正式世界激活契约设计（ACTIVATION CONTRACT DESIGN）

> **M6B 后续（2026-09-16）**：本文件 §2 登记的两个策略缺口已由主人 canon 裁决
> （`INITIAL_BLESSED_TICK = 0`；activation anchor = 显式 durable UTC instant），
> `M6_DESIGN_GAP_RUNTIME_EPOCH_ANCHOR_WIRING` 已经 OPTION A 接线解决，
> `M6_DESIGN_GAP_INITIAL_WORLD_STATE` 经经验审计判为 **BLOCKING**。
> 见 `docs/m6b_bootstrap_and_epoch_audit.md`。以下内容保留为 M6A 阶段的历史记录。

- 阶段：`M6A — ACTIVATION CONTRACT IMPLEMENTATION`（**不是**正式世界激活）
- 结论：`ACTIVATION_ENTRYPOINT_IMPLEMENTED = TRUE`；
  `SEED_CONSUMPTION_ATOMICITY = SINGLE_DB_TRANSACTION_ATOMICITY_PASS`；
  正式世界保持 `NOT_ACTIVATED`（0 行 / tick NULL / seed 未消费）。
- 本文件回答 owner 指令 §2 的全部只读调查项、登记 §2–§13 发现的 canon 缺口，
  并给出协议设计。实现见 `services/activation/`。

---

## 1. §2 Activation Contract Audit（只读调查结果）

| 调查项 | 结论 | 证据 |
| --- | --- | --- |
| `ACTIVATION_ENTRYPOINT`（调查前） | **NONE** —— 仓库内不存在任何激活实现 | 生产路径无 seed/activat/bootstrap/genesis 模块；`runtime_host.py:344,368` 固定 `"world_activation": "LOCKED"`；`RuntimeStatus.ACTIVE` 全仓只被**读取**（`guard.py:30`、`scheduler/core.py:418-421`、`world_query_service.py:141,165`） |
| `WORLD_SEED_STORAGE` | `XIAOGUANG_CROW_KB/world_seed/`（仓库**之外**的只读知识库目录，21 文件） | `services/activation/seed_package.py::default_seed_dir`；与 `config/settings.py:24-25` 的 Bible 目录同一知识库根 |
| `WORLD_SEED_MANIFEST` | `MANIFEST.sha256.txt`（20 条目，格式 `<sha256>␠␠<filename>`） | `world_seed/MANIFEST.sha256.txt`；解析/校验复用 `domain/versions.py::load_bible_fingerprint`（同一格式已被 World Bible 使用） |
| `WORLD_SEED_FINGERPRINT_SOURCE` | `sha256(MANIFEST.sha256.txt 字节)` ＋ `load_bible_fingerprint` 的 canonical 摘要 | 实跑值 `cc0e4c0e16c7e2ec8cecb4ba871afc3af1a402e94732e645fceb4b1aca73771d`，与 owner 在 M6.0 记录的 `WORLD_SEED_MANIFEST_SHA256` **逐字符一致** |
| `SEED_RAW_MATERIAL_LOCATION` | 同上（Seed 包目录）；Runtime **只读**，绝不写入/删除 | `seed_package.py` 只读取 `VERSION.json` 与 `MANIFEST.sha256.txt`，不读取任何 baseline 数据文件内容 |
| `SEED_CURRENT_STATE_MODEL` | Seed 包自声明状态为**不可变声明**（`PREPARED_NOT_ACTIVATED`），不是可写账本；**消费状态记录在正式库** | `VERSION.json.status`、`00_WORLD_SEED_MASTER.md:4`（"准备激活的数据包，不是已发生的世界事实"）、A6/A7（唯一性/幂等由 Runtime 侧保证） |
| `FORMAL_WORLD_ID_POLICY` | `BL-0001`（canon：`01_seed_identity.json` world_id，`CONFIRMED_STATIC_CANON`，来源 LOCAL_CANON） | `models_core.py:25`（`world_id` UNIQUE，注释 `'BL-0001'`）、`db_lifecycle.py:69`（`world_id: str = "BL-0001"` 默认值） |
| `INITIAL_BLESSED_TICK_POLICY` | **canon 未定义数值** —— 只说"仅可由未来 Activation Transaction 创建" | `01_seed_identity.json`（`initial_blessed_tick=NULL / NOT_ACTIVATED`）、`02_time_baseline.json`（`current_blessed_tick=NULL`）；全仓出现的 `tick=0` 均为测试夹具（`tests/conftest.py:105,119` 等）→ **GAP-1** |
| `ACTIVATION_TIME_ANCHOR_POLICY` | **canon 未定义时刻**；但受冻结 planner 硬约束：`cursor == epoch0 + (tick//1e6)*YEAR_US` 且 `tick % 1e6 == 0` | `runtime_design/04/05`（A3 不得回溯）；`services/scheduler/planner.py:94-102` → **GAP-2** |
| `INITIAL_POPULATION_POLICY` | **NO_PRODUCTION_PRIMITIVE** | 无任何生产 INSERT `population_groups`/`persons`（仅 `services/simulation/mini_world.py:157,166`，TEST_FIXTURE_ONLY）；`population.py:181-185` 零行即零产出；唯一 profile 为 `TEST_PROFILES` |
| `INITIAL_RESOURCE_POLICY` | **NO_PRODUCTION_PRIMITIVE**（"八态状态机"未实现） | `resource.py:22` 自述"完整八态状态机属后续里程碑"；仅 STABLE↔EXHAUSTED；registry TEST-only |
| `INITIAL_ECONOMY_POLICY` | **NO_PRODUCTION_PRIMITIVE**（缺行即 `EconomyStateInconsistent`） | `economy.py:164-170, 359-362`；registry TEST-only |
| `INITIAL_ECOLOGY_POLICY` | **NO_PRODUCTION_PRIMITIVE**（缺行即 `EcologyZoneMissing`） | `ecology.py:192-199` |
| `INITIAL_SOCIAL_POLICY` | **NO_PRODUCTION_PRIMITIVE**（缺 `settlement_social_state` 即 `IntegrityError`） | `social.py:567-575`；household/institution 只在**激活后的仿真步**内生成 |
| `INITIAL_TRIBULATION_POLICY` | **NO_PRODUCTION_PRIMITIVE**（formal profiles/schedules = 0 行） | `tribulation.py:15-16, 119-159, 194-195` |
| `GENESIS_HISTORY_POLICY` | **canon 已定义**：正式历史第一个事件只能是 `WORLD_SEED_ACTIVATED`，事件本体由 Activation Transaction 创建 | `00_WORLD_SEED_MASTER.md:23,42`、`12_initial_event_boundary.json`（`activation_event` + `no_retroactive_history` + `official_history_events=0`） |
| 激活前现实时间是否产生 backlog | **不得产生**（A3 明文） | `14_activation_invariants.json` A3："Activation 时现实等待时间不得回溯补算（无'过去百年已发生'）"；`12_initial_event_boundary.json:no_retroactive_history` |

---

## 2. `M6_DESIGN_GAPS`（canon 缺口 —— 不偷偷补设计）

| ID | 缺口 | canon 依据 | 本实现的处理（**不发明**） |
| --- | --- | --- | --- |
| `M6_DESIGN_GAP_INITIAL_TICK` | 初始 blessed tick 的**数值**未定义 | 01/02 号只声明 `NULL` + "由 Activation Transaction 创建" | `ActivationRequest.initial_blessed_tick` 为**必填、无默认值**；并强制冻结 planner 的整年对齐不变量；缺参数即 `ActivationRefused` |
| `M6_DESIGN_GAP_ACTIVATION_ANCHOR` | 激活 canonical instant / 世界年锚 `epoch0` 未定义 | 同上（`activation_epoch=NULL`） | `epoch0_us` **必填、无默认值**；强制 `activation_real_us == epoch0_us + year_index*YEAR_US`；不通过即拒绝 |
| `M6_DESIGN_GAP_INITIAL_WORLD_STATE` | "initial static world state"（人口/资源/经济/生态/社会/灾劫实例）**无生产原语**且 canon 禁止补全 | A9"Runtime 不得自行补 UNKNOWN"；`00_WORLD_SEED_MASTER.md:39-40`（12,000 是规划值，**严禁写成当前人口**）；05/07/09/11 号 `instances=0` / `比例 NULL` / `NAME=UNDECIDED` | 激活**只创建** A4 列出的运行时级内容（seed 版本、activation instant、initial tick、real cursor、速率起始绑定、genesis 事件），**创建 0 个实例**；由测试断言业务表全零 |
| `M6_DESIGN_GAP_PRODUCTION_ENGINE_REGISTRY`（operational） | 生产 `coordinator_provider` 未接线 | `main.py:96-105` 未传 provider；`scheduler/core.py:257-260` fail-closed | 不接线（属 M7 范围）。已测试并如实报告激活后的 scheduler 行为 |
| `M6_DESIGN_GAP_RUNTIME_EPOCH_ANCHOR_WIRING`（**M6.1 阻塞前置**） | Runtime 年锚未与激活年锚接线：`main.py` 不传 epoch0，scheduler 用 `MINI_WORLD_EPOCH0_US`（2026-01-01Z）；激活年锚若不同，世界激活后永远无法推进 | `scheduler/core.py:75`、`planner.py:97-102`、`main.py:96-105` | 已把年锚变为 durable 事实（`read_world_epoch_anchor`）并**强制**请求年锚 = Runtime 年锚（不一致即拒绝，绝不造出无法推进的世界）；两种裁决见 §10 |

> 以上四项**均需主人裁决**后方可推进 M6.1；本阶段只交付"能安全出生的能力"，
> 不替主人决定世界起点数值，也不替主人物化世界内容。

---

## 3. 激活协议

```
                 ┌──────────────────────────────────────────────┐
 0. 请求校验      │ world_id / seed_dir / epoch0_us / initial_tick│  缺任一即 REFUSED
                 │ + runtime_epoch0_us（Runtime 侧年锚）          │  （无默认值）
                 │ 整年对齐 + 年锚一致性 + 年锚与 Runtime 一致     │
                 └──────────────────────────────────────────────┘
 1. A8 Seed 校验   load_seed_package()：MANIFEST 逐文件 sha256 复算 +
                   自声明状态 = PREPARED_NOT_ACTIVATED + 版本匹配      → 只读
 2. durable 预判   read_activation_truth()：已 COMMITTED → ALREADY_COMMITTED
                   （零写入幂等返回；换 Seed / 无指纹记录 → REFUSED）  → 只读
                   世界身份核对：请求 world_id 必须等于库中唯一世界      → 只读
 ──────────────────────────────────────────────────────────────────────────
 3. 单写者租约     WriterLease.acquire()（PK + CAS 接管仲裁）        → 冲突即 REFUSED
 ──────────────────────────────────────────────────────────────────────────
 4. 单一 durable 事务（WorldMutationContext，fencing 校验）
      4.1 事务内二次判定（并发最终仲裁）：已激活 → rollback 返回 ALREADY
      4.2 A2/A10 前置不变量：未激活世界不得已有**任何**事件 / genesis；
          simulation_version 必须与世界记录一致
      4.3 选出生效速率行（rate_at / 冻结 time_engine）
      4.4 RuntimeRepository.activate()  ← 唯一允许写 ACTIVE 的位置
      4.5 TimeRatioRepository.bind_blessed_start()（NULL → initial tick）
      4.6 create_simulation_event(WORLD_SEED_ACTIVATED) ← 唯一事件入口（guard）
      4.7 ctx.commit()（COMMIT 前 assert_current_fence）
 ──────────────────────────────────────────────────────────────────────────
 5. commit 歧义    DBAPIError → 先 rollback → durable truth reconcile
                   → COMMITTED / fail-closed（绝不盲重试）
 6. 提交后核对     read_activation_truth() 必须显示 ACTIVE（否则 fail-closed）
 7. 释放租约       仅 token 匹配（绝不误删他人租约）
```

- **原子边界**：4.3–4.5 全部落在同一个 `WorldMutationContext` 事务；未显式
  `ctx.commit()` 即整体 rollback（A5：无部分状态）。
- **一次性创建**（A4）：seed 版本记录、activation instant、initial tick、
  real cursor、速率起始绑定、genesis 事件 —— 同一事务。
- **顺序依赖**：`runtime_lock` 对 `world_runtime` 有 FK（`models_core.py:189-190`
  + `db.py:33`），因此 metadata 行必须先存在；metadata 由**既有**非权威路径
  创建（`db_lifecycle.seed_database`，自述"绝不激活世界"）。激活本身仍是一个
  原子事务 —— metadata 播种**不是** seed 消费，也不进入任何世界真值。

## 4. Seed exactly-once 模型

- Seed 包 = **不可变只读输入物料**：本协议绝不写入/删除/改写 Seed 字节
  （那会破坏 A8 的 MANIFEST 校验，owner §3 明令禁止"先删 seed 文件"以假装原子）。
- **消费账本在正式库**（因此可以做到真正的单事务原子性）：
  1. `world_runtime.world_seed_version`（+ `runtime_status=ACTIVE`）；
  2. **不可变** genesis 事件（`world_events` 只追加 + DB 触发器禁 UPDATE/DELETE/TRUNCATE）
     的 `effect` 内记录 `world_seed_fingerprint` / `world_seed_id` /
     `seed_consumption_index=1` / `initial_blessed_tick` / `activation_real_us` / `epoch0_us`；
  3. `world_id` UNIQUE（第二个世界在 DB 层不可能存在）。
- `WORLD_SEED_CONSUMPTION_COUNT = COUNT(event_type='WORLD_SEED_ACTIVATED') ∈ {0,1}`。
- **DB 级兜底的确切边界（重要，勿夸大）**：
  - `world_runtime.world_id` UNIQUE → 结构上不可能存在第二个世界行；
  - `world_events.event_uid` UNIQUE → 只能挡住**参数完全相同**的重放（uid 把
    年锚/版本算进哈希，因此换年锚的重放会得到不同 uid，DB 层挡不住）；
  - 因此"不同参数下的 exactly-once"由**事务内的应用门禁**保证：
    已激活行判定（4.1）+ `assert_activatable`（四条件 fail-closed）+
    4.2 的"未激活世界不得已有事件/genesis"前置不变量。
- `activation_operation_id`（§7）= `deterministic_hex_id([world_id, seed_version,
  fingerprint, initial_tick], schema="world-activation-v1")` —— durable、确定性、
  同一 (世界, seed, tick) 恒等。

### 4.1 年锚的持久化与 Runtime 接线（F2：本阶段发现的关键前置）

年锚不是装饰性字段：冻结 planner 强制
`cursor == epoch0_us + year_start*YEAR_US`（`planner.py:97-102`），而生产的
`RuntimeScheduler` 目前**没有**被传入 epoch0（`main.py:96-105`），因此它用
`MINI_WORLD_EPOCH0_US`（2026-01-01Z，`scheduler/core.py:75`）。

如果激活时的年锚与 Runtime 年锚不同，激活会**成功**，但世界在首个 cycle 就
永远无法推进（`plan()` 抛"durable real cursor 与年锚不一致"，host 只记录日志）。
因此本契约：

1. 把年锚写进 genesis 事件的 `effect.epoch0_us`（durable）；
2. 新增唯一读法 `services/durable_truth.read_world_epoch_anchor()`；
3. **强制** `request.epoch0_us == request.runtime_epoch0_us`，否则 fail-closed 拒绝
   （绝不造出一个无法推进的世界）。

剩余待接线项登记为 `M6_DESIGN_GAP_RUNTIME_EPOCH_ANCHOR_WIRING`（见 §2/§10）。

## 5. 幂等 / 单写者 / commit 歧义

| 要求 | 实现 |
| --- | --- |
| §9 幂等 | 二次 activate → `ALREADY_COMMITTED`（`written=False`）；无第二世界 / 无第二次消费 / 无 reset / 无新 anchor / 无第二 genesis；**已激活但无指纹记录** → 拒绝（不谎报身份） |
| §15 单写者 | `WriterLease`（PK 仲裁 + 过期 CAS 接管 + commit 前 fence 复验）；两个 Activator → `ACTIVATION_WINNERS=1`；`world_id` 身份先于租约核对（避免 FK 违规被误报成租约竞争） |
| §16 歧义复用 | **不在激活里新写第二套协议**：抽取 `services/durable_truth.py`（原 `RuntimeScheduler._read_durable_tick_resilient` 的唯一实现），scheduler 改为委托调用，激活服务使用同一实现；reconcile 前显式 rollback，确保只读服务器真值 |
| A2/A10 前置不变量 | 事务内断言：未激活世界必须**零事件**（含零 genesis）、`simulation_version` 与世界记录一致 |
| fail-closed | durable truth 不可读 → `ActivationOutcomeUnknown`；绝不盲重试（`BLIND_ACTIVATION_RETRY_COUNT = 0`）；Seed 完整性/封装错误 → `WorldSeedIntegrityError`（CLI 映射为退出码 2） |

## 6. 时间锚与 `PRE_ACTIVATION_BACKLOG = 0`

- 激活事务把 `last_committed_real_us` 设为 activation canonical instant（年锚对齐），
  因此 `catch_up` 的积分区间从**激活时刻**开始 —— NOT_ACTIVATED 期间流逝的现实时间
  永不进入福地历史（A3；owner §10）。
- 时间规则覆盖守卫：世界原点不得早于速率 canon 的有效起点，否则冻结
  `time_engine.rate_at` 无法积分 → 拒绝（不是"把速率行挪一挪"硬凑）。
- 速率行 `blessed_effective_from_tick`：`NULL`（未开始计）→ `initial_blessed_tick`
  （`models_core.py:50` 对该列的语义定义）。

## 7. 复用映射（禁止重造）

| 冻结原语 | 位置 | 本阶段用途 |
| --- | --- | --- |
| `load_bible_fingerprint` | `domain/versions.py:24` | A8 Seed MANIFEST 校验（同格式复用） |
| `WorldMutationContext` | `services/fencing.py:32` | 激活的单一 fenced 事务与 commit 前复验 |
| `WriterLease` | `services/writer_lock.py:52` | 单写者仲裁 / fencing token |
| `create_simulation_event` | `services/guard.py:39` | genesis 事件唯一受保护入口（激活守卫复用） |
| `EventRepository.append` / `deterministic_event_uid` | `repositories.py:117` / `simulation/event_stream.py:25` | 事件身份（128-bit 确定性） |
| `rate_at` / `RateWindow` / `Integrator` | `services/time_engine.py` | 生效速率选择与分段积分 |
| `TimeRate` / `TICKS_PER_BLESSED_YEAR` / `NATURAL_TIME_RATE` | `domain/blessed_time.py` | 量纲与整年对齐 |
| `deterministic_hex_id` | `services/identity.py` | `activation_operation_id` |
| `read_snapshot` / `world_state_hash_v6` | `simulation/snapshot.py` / `state_hash.py` | 测试层"同一 synthetic seed → 同一 initial world hash" |
| `db_lifecycle.seed_database` | `services/db_lifecycle.py:67` | metadata（NOT_ACTIVATED）非权威播种 |
| `read_durable_tick_resilient`（新抽取） | `services/durable_truth.py` | scheduler 与激活**共用**的 commit-ambiguity 核对 |

## 8. `ACTIVATION_BOUNDARY_GUARD`（§17）

原 M4 门禁 `tests/test_scheduler_world_seed_safety.py` **保留不删**（scheduler 专项窄门禁），
新增 `tests/test_m6_world_seed_safety.py` 作为其广义重构：

```
WORLD_SEED_ACTIVATION_ACCESS_ALLOWLIST = M6_ACTIVATION_SERVICE_ONLY
ALLOWED_PREFIXES = ("services/activation/",)
```

1. `G-01`：只有 allowlist 可以命中 seed 激活 token（scheduler/query/simulation/
   history/database/domain/config/plugin_shell/main 显式单列）；
2. `G-02`：`runtime_status` 赋值（非 NOT_ACTIVATED）只允许出现在
   `services/repositories.py`；repository 必须保留 fail-closed 原语；
3. `G-03`：RuntimeHost boot 仍 `world_activation = LOCKED`（2 处）；无 activate 端点、
   无配置开关；LLM hook 与其后续查询路径零激活原语；控制面必须显式确认标志；
4. `G-04`：正式 Seed 包 MANIFEST 逐字节冻结 + 自声明状态仍 `PREPARED_NOT_ACTIVATED`；
   `WORLD_SEED_ACTIVATED` 字面量只有唯一 canonical 定义处（`services/durable_truth.py`）；
5. `G-05`：控制面缺确认标志时**行为级**证明零写入并拒绝（退出码 2）。

## 9. 控制面（§19/§20）

- 形式：host 上的**维护 CLI** `scripts/activate_formal_world.py`（默认只读 `--status`）。
- 显式：必须 `--confirm-formal-world-activation`；`--initial-blessed-tick` /
  `--epoch0-us` 无默认值。
- 非聊天：不注册任何 Web API / AstrBot 命令 / 自然语言路由（插件对外 API 保持
  6 个 GET 只读端点，`test_plugin_shell` PL16/PL17 继续 PASS）。
- 非 LLM：`@on_llm_request` 路径无任何激活原语（`G-03c`）。
- 非 scheduler：scheduler 不引用激活服务（`G-01c`）。
- 宿主 boot：`world_activation = LOCKED` 不变（部署能力 ≠ 自动激活）。

## 10. 已知边界与残余（如实登记）

1. **年锚接线**（`M6_DESIGN_GAP_RUNTIME_EPOCH_ANCHOR_WIRING`）：本契约强制
   请求年锚 = Runtime 年锚，但不负责把 Runtime 年锚接到 durable 事实；接线前只能在
   年锚整点激活（见 §10 裁决项 2）。
2. **Seed 包"新增文件"不可检测**：`load_bible_fingerprint` 只遍历 MANIFEST 条目，
   因此往包目录里**新增**文件不会改变指纹（不影响激活读取面，因为只读
   `VERSION.json` + `MANIFEST.sha256.txt`）。若主人要求"包目录逐项白名单"，需另立规则。
3. **单连接池下的 reconcile**：reconcile 前已显式 rollback，且本仓库 CLI/Settings/测试
   全部使用文件库或 PG（`sqlite://` 内存库 + StaticPool 才会共享连接）。已按防御性处理，
   不再构成隐患，但仍是**未在单连接池下实证**的组合。
4. **A2/A10 只由激活侧强制**：激活拒绝"未激活世界已有事件"，但其它生产写入路径
   （`catchup`/`coordinator`/`tribulation`/`history.corrections`）直接调用
   `EventRepository.append`，其安全性依赖"需要已初始化时钟/已存在事件"这一前提。

## 11. 明确留给主人的事项

1. `M6_DESIGN_GAP_INITIAL_TICK` / `M6_DESIGN_GAP_ACTIVATION_ANCHOR` 的**取值裁决**；
2. `M6_DESIGN_GAP_RUNTIME_EPOCH_ANCHOR_WIRING`（**M6.1 阻塞前置**）二选一：
   - (a) **把 Runtime 年锚接到激活年锚**：`main.py` 构造 `RuntimeScheduler` 时传入
     `epoch0_us = durable_truth.read_world_epoch_anchor(...)`（未激活用现有默认）——
     这样"世界在任何时刻出生"都成立，A3（backlog 0）天然满足；
   - (b) **不接线**：那么必须在一个**年锚整点**激活（`activation_real_us` 恰好等于
     2026-01-01Z + k 年，即 2027-01-01Z / 2028-01-01Z…，初始 tick = k×1_000_000），
     由契约的一致性检查强制；
3. `M6_DESIGN_GAP_INITIAL_WORLD_STATE`：是否授权一个独立的"初始世界物化"阶段
   （需要新的、可追溯的原语；本阶段按 canon 拒绝物化）；
3. 生产引擎注册表接线（M7）与激活后 scheduler 的行为预期；
4. live staging（owner §29）与真正的一次性正式激活（另行授权）。
