# M6 WORLD ACTIVATION — 报告

- 报告时间：2026-09-15（本地）
- 阶段：`M6.0 FINAL ACTIVATION PREFLIGHT` → **在 M6.1 之前判定 BLOCKED**
- `PRE_ACTIVATION_HEAD = a1da81c4f77eb78323975537af329a72f2a7f815`
  （工作区 clean；live 部署包源码 HEAD = `138a2c620f452f97900951877fd9baab7fef8aa9`；
   `a1da81c4` 相对其仅新增 `reports/` 文档，production 内容一致）
- **结论：`M6_ACTIVATION = BLOCKED_PREFLIGHT`**
  —— 仓库内**不存在正式 activation entrypoint**；按 §4「不得现场另写第二套 activation
  protocol」与 §5「不能证明 seed 消费原子性 → BLOCKED，不得消费 Seed」，
  本次**未执行激活、未消费 World Seed、未创建正式 `world_runtime` 行**。
- `M6_WORLD_LIVE = FALSE`

---

## 1. M6.0 Activation Entry Point Audit（§4，只读）

审计范围：仓库全部生产路径（`main.py`、`services/`、`plugin_shell/`、`database/`、
`domain/`、`config/`），以及 `runtime_design/` 设计文档与 manifest。

### 1.1 未找到任何 activation 实现

```
按文件名检索 seed / activat / bootstrap / genesis / world_init / init_world
  → 生产路径命中 0 个模块（services/ 下仅 history、query、scheduler、simulation）
按标识符检索 def activate / activate_world / world_activation /
  consume_seed / seed_consumed / WORLD_SEED_CONSUMED /
  PREPARED_NOT_ACTIVATED / class WorldSeed / activation_anchor
  → 生产代码命中 0 处；仅命中测试夹具与安全门禁（见 1.3）
runtime_design/ 内无 M6 设计文档（仅 M2A/M2B/M2C/M2D/M2_PREFLIGHT/M3A/M3B/M3_PREFLIGHT）
```

### 1.2 生产代码只会「拒绝激活」，不会执行激活

| 证据 | 位置 | 含义 |
| --- | --- | --- |
| `RuntimeStatus.ACTIVE` 在生产代码中**只被读取**（guard / scheduler / query service），**从不被写入** | `services/guard.py:30`、`services/scheduler/core.py:420`、`services/query/world_query_service.py:141,165` | 没有任何代码把世界置为 ACTIVE |
| `world_seed_version` 仅在 `create_not_activated` 中被显式置 `None` | `services/repositories.py:46` | 没有任何代码写入真实 seed 版本 |
| `RuntimeRepository` 仅有 `get` / `create_not_activated` / `sync_schema_version` | `services/repositories.py` | **无 `activate` / `bootstrap` / `consume_seed`** |
| `require_world_activated()` 是「世界推进的终极安全锁」，未激活即抛 `WorldNotActivated` | `services/guard.py:22-36` | 设计上是**反向守卫**，不是激活器 |
| `db_lifecycle.seed_database` 注释明示「播种 world_runtime(NOT_ACTIVATED) + 自然态速率行（**绝不激活世界**）」 | `services/db_lifecycle.py:5,79` | 生产启动只播种未激活元数据 |
| RuntimeHost 明示「绝不伪造 manifest hash、**绝不激活**」 | `plugin_shell/runtime_host.py:192-195` | 部署期不激活 |
| `/diagnostics` 与页面固定报告 `"world_activation": "LOCKED"` | `plugin_shell/runtime_host.py:344,368` | 宿主对外声明激活能力为**锁定** |

### 1.3 冻结门禁**静态禁止** seed 消费路径（这是最强的反向证据）

`tests/test_scheduler_world_seed_safety.py`（M4 冻结门禁，全量回归中 PASS）：

```python
FORBIDDEN = ("world_seed/", "XIAOGUANG_CROW_KB", "04_population_baseline",
             "05_species_baseline", "06_settlement_baseline", "consume_seed",
             "activate_seed", "seed_activation", "WORLD_SEED_INDEX",
             "UNRESOLVED_SEED", "MANIFEST.sha256")
def test_scheduler_source_never_consumes_world_seed():
    # 任一 token 出现在调度器源码即失败
```

即：**任何 seed 消费实现都会立刻违反已冻结的门禁** —— 在运行时层面「激活」
是被明确排除的能力，而非遗漏。

### 1.4 World Seed 包的性质

`XIAOGUANG_CROW_KB/world_seed/`（21 个文件，均为 2026-09-07）为 **PHASE_1_8 设计/准备产物**
（00_WORLD_SEED_MASTER.md、01–13 基线、`14_activation_invariants.json`、
`WORLD_SEED_INDEX.json`、`PHASE_1_8_WORLD_SEED_ACTIVATION_PACKAGE_FINAL_REPORT.md`、
`MANIFEST.sha256.txt`），**不是运行时激活服务**。

### 1.5 审计结论

```
ACTIVATION_ENTRYPOINT             = NONE（仓库内不存在）
ACTIVATION_SERVICE                = NONE
WORLD_SEED_CONSUMPTION_PATH       = NONE（且被冻结门禁静态禁止实现）
FORMAL_WORLD_INITIALIZATION_PATH  = NONE
TIME_ANCHOR_INITIALIZATION_PATH   = NONE
INITIAL_WORLD_RUNTIME_WRITE       = NONE（无任何生产写入 RuntimeStatus.ACTIVE）
INITIAL_HISTORY_BEHAVIOR          = N/A（无激活 → 无 genesis event 定义）
```

**未现场另写 activation protocol**（§4 明确禁止）；本轮**未消费 World Seed**。

## 2. Seed Consumption Atomicity Gate（§5）→ 不可证明

§5 要求证明「seed 标记 consumed」与「正式 world_runtime / activation metadata 建立」
属于同一 durable atomic boundary 或具备确定性一次性可恢复协议。

```
SEED_CONSUMPTION_ATOMICITY = NOT_PROVABLE
  原因：不存在任何实现可被审计（无代码、无 migration 字段用于 seed consumed 标记、
        无 activation 事务入口）。原子性/一次性/可恢复性**均无从证明**。
```

按 §5 明文规定：**`M6_ACTIVATION = BLOCKED`；STOP；不得消费 Seed** —— 已遵守。

## 3. Activation Idempotence Design（§6）→ 不可证明

```
ACTIVATION_IDEMPOTENCE_DESIGN = NOT_PROVABLE
  无激活实现 → 无法证明「第二次相同请求不重复消费 seed / 不创建第二世界 /
  不重置 tick / 不重写 anchor」。
```

## 4. Pre-Activation Offline Time 语义（§7）

```
PRE_ACTIVATION_BACKLOG        = N/A（未激活，无 anchor 建立动作）
ACTIVATION_TIME_ANCHOR_POLICY = 现有冻结 M1 Time Engine 语义仍然有效：
   激活判定 = runtime 行存在 + runtime_status==ACTIVE + world_seed_version 非空
   （services/guard.py:4）；现实时间锚 = world_runtime.last_committed_real_us
   （M1 游标）；未激活期间不产生任何追溯补算路径（catch_up 入口被
   require_world_activated 拒绝）。**未现场重新解释任何契约。**
```

## 5. M6.0 Preflight Snapshot（§8，只读）

```
FORMAL_DB_SHA256_PRE_ACTIVATION = 7754b1d4658ea94ce509ae7fb7c06c33c44f98782021b3708e6f29ce69102837
FORMAL_DB_ALEMBIC_HEAD          = a9d4f2b7c1e8
FORMAL_DB_INTEGRITY             = ok

WORLD_RUNTIME_ROWS = 0     WORLD_EVENTS = 0        SIMULATION_RUN = 0
RUNTIME_LOCK = 0           TIME_RATIO_HISTORY = 0  SIMULATION_CHECKPOINTS = 0
causal_history_links / history_state_changes / history_episode_index /
entity_history_index / history_index_state / tribulation_episodes = 全部 0

CURRENT_BLESSED_TICK = NULL（world_runtime 0 行）
WORLD_RUNTIME_STATUS = NOT_ACTIVATED
WORLD_SEED_STATUS    = PREPARED_NOT_ACTIVATED
WORLD_SEED_CONSUMED  = FALSE
SCHEDULER_STATUS     = DORMANT（counters 全 0；last_error = null）
AUTHORITATIVE_DB_CHECKSUM_MATCH = TRUE（authoritative_db.json == 库 SHA256）
PRIVATE_COMPANION_SOURCE_UNCHANGED = TRUE（529/529）
```

**World Seed 只记录指纹/状态（§3：绝不读取/打印/写日志/写报告 seed 本身）**：

```
WORLD_SEED_DIR_PRESENT      = TRUE（21 个文件）
WORLD_SEED_MANIFEST_SHA256  = cc0e4c0e16c7e2ec8cecb4ba871afc3af1a402e94732e645fceb4b1aca73771d
WORLD_SEED_STATUS           = PREPARED_NOT_ACTIVATED
WORLD_SEED_CONSUMED         = FALSE
SEED_VALUE_READ_OR_PRINTED  = FALSE
```

## 6. M6 Pre-Activation Rollback Point（§9）

```
M6_ROLLBACK_PATH = D:\MY SELF\IKUN\小光\incident_quarantine\m6_pre_activation_20260915_182700
  含：plugin_source/（live Runtime 源码快照，tree hash
      60e63db1fe969d32f56708c119c905af81752e83abdcb7ff1a50359bb11dc230，101 文件）
      plugin_data/blessed_land.sqlite（**SQLite 一致备份**）
        sha256 = 9e5a8e40b2c0ef32edeef29962652ecbd75492d3b5d9c5a0c56ba9e56c4e2d9d
        integrity = ok / head = a9d4f2b7c1e8 / world_runtime rows = 0
      plugin_data/runtime_state/（authoritative_db.json + scheduler_state.json）
      seed_metadata.json（仅指纹/状态）
```

用途限定：仅灾难性 recovery。**activation 一旦 durable commit，不得回滚到未激活
（避免世界分叉）**；commit ambiguity 原则继续适用（先确定 durable truth 再决定恢复）。
本轮未触发任何回滚。

## 7. M6.1 / M6.2 字段（未执行，如实标注）

M6.1 与 M6.2 **未执行**（BLOCKED_PREFLIGHT）。以下字段为 `NOT_ATTEMPTED` /
`NOT_APPLICABLE`，**不得**被解读为任何形式的激活或世界创建：

```
ACTIVATION_DURABLE_OUTCOME       = NOT_ATTEMPTED
WORLD_RUNTIME_ROWS               = 0（保持未激活）
WORLD_RUNTIME_STATUS             = NOT_ACTIVATED
WORLD_SEED_STATUS                = PREPARED_NOT_ACTIVATED
WORLD_SEED_CONSUMED              = FALSE
WORLD_SEED_CONSUMPTION_COUNT     = 0
INITIAL_BLESSED_TICK             = N/A（未激活；canonical 初值应由尚未实现的
                                   激活契约定义，§12 禁止自行假设 0/1）
ACTIVATION_TIME_ANCHOR           = N/A
INITIAL_OFFICIAL_HISTORY_EVENTS  = N/A（世界未激活 → 官方事件 0）
SCHEDULER_STATE_T0/T5M/T10M/T15M = DORMANT / DORMANT / DORMANT / DORMANT
                                   （未激活世界按设计保持 DORMANT，无观察窗口必要）
CURRENT_TICK_T0/T5M/T10M/T15M    = NULL / NULL / NULL / NULL
ACTIVE_WRITER_COUNT              = 0
STALE_WRITER_MUTATIONS           = 0
HISTORY_ORPHAN_LINKS             = 0
HISTORY_CAUSAL_CYCLES            = 0
HISTORY_INVALID_REFS             = 0
BLIND_ACTIVATION_RETRY_COUNT     = 0（未发起任何 activation 请求，更无盲重试）
SECOND_ACTIVATION_ATTEMPT        = NOT_PERFORMED
ACTIVATION_IDEMPOTENCE_RUNTIME   = NOT_APPLICABLE
FIRST_LAUNCHER_STOP              = NOT_PERFORMED（本轮无需停机：未进入 M6.1）
SECOND_LAUNCHER_START            = NOT_PERFORMED
ACTIVATED_RESTART                = NOT_PERFORMED
TICK_AFTER_RESTART               = N/A
HISTORY_AFTER_RESTART            = N/A
```

live 实例当前仍 RUNNING（主人上一阶段第二次启动的状态，未被本阶段改动）；
世界仍 `NOT_ACTIVATED`、scheduler 仍 `DORMANT`。

## 8. 本阶段禁止事项遵守

```
新增世界规律 / 修改 M1–M4 semantics / 修改 RNG / 修改各引擎规律 = 无
修改 Private Companion = 无（529/529 未变）
继续 M5 persona 修复 = 无（KL-M5-001/002 保持 OWNER_DEFERRED）
修改 AstrBot Core / Launcher / live venv / 依赖 = 无
修改 PostgreSQL test environment = 无（blr-pre-m6-postgres 保持 healthy；
                                   stayops-postgres 未触碰）
修改 Golden Baselines = 无
手工 INSERT/UPDATE 世界或 seed / 直接 SQL 初始化 = 无
另写第二套 activation protocol = 无（§4 禁止）
```

## 9. 结论与所需主人决定

M6.1「一次性世界激活」在当前代码基线上**不可能通过既有路径完成**：
Runtime 从设计上就把激活标为 `LOCKED`，并以冻结门禁禁止任何 seed 消费实现。
因此本轮的正确结果是 **BLOCKED_PREFLIGHT**，而不是用临时脚本「激活到能跑」
（那会同时违反 §4、§5、§11 与 §2 的「不得修改 semantics」）。

**需要主人的决定（二者选一）**：

1. **授权一个独立的 M6 激活实现阶段**（新指令、明确范围）：在 Runtime 内实现
   activation contract —— seed 消费一次性协议 + 与 `world_runtime` 初始化的
   单一 durable 事务边界 + 幂等拒绝 + 时间锚建立 + genesis/history 契约，
   并配套冻结门禁更新（`test_scheduler_world_seed_safety.py` 的 FORBIDDEN 集合
   必须随设计显式修订，不得绕过）；实现后重跑 M6.0 审计 → M6.1 → M6.2。
2. 或**维持世界未激活**（保持当前 `PREPARED_NOT_ACTIVATED`），不推进 M6。

```
M6_ACTIVATION = BLOCKED_PREFLIGHT
M6_WORLD_LIVE = FALSE
NEXT_ACTION   = AWAIT_OWNER_DECISION_ON_M6_ACTIVATION_IMPLEMENTATION
```

---

## 10. 返回字段（M6_WORLD_ACTIVATION_REPORT）

```
M6_WORLD_ACTIVATION_REPORT

PRE_ACTIVATION_HEAD = a1da81c4f77eb78323975537af329a72f2a7f815
LIVE_RUNTIME_HEAD   = 138a2c620f452f97900951877fd9baab7fef8aa9
                      （live tree hash 60e63db1fe969d32f56708c119c905af81752e83abdcb7ff1a50359bb11dc230）

SEED_CONSUMPTION_ATOMICITY      = NOT_PROVABLE（无实现可审计 → 按 §5 判 BLOCKED）
ACTIVATION_IDEMPOTENCE_DESIGN   = NOT_PROVABLE

FORMAL_DB_SHA256_PRE_ACTIVATION = 7754b1d4658ea94ce509ae7fb7c06c33c44f98782021b3708e6f29ce69102837
M6_ROLLBACK_PATH                = D:\MY SELF\IKUN\小光\incident_quarantine\m6_pre_activation_20260915_182700

ACTIVATION_ENTRYPOINT           = NONE（仓库内不存在；宿主声明 world_activation = LOCKED）
ACTIVATION_DURABLE_OUTCOME      = NOT_ATTEMPTED

WORLD_RUNTIME_ROWS              = 0
WORLD_RUNTIME_STATUS            = NOT_ACTIVATED

WORLD_SEED_STATUS               = PREPARED_NOT_ACTIVATED
WORLD_SEED_CONSUMED             = FALSE
WORLD_SEED_CONSUMPTION_COUNT    = 0
WORLD_SEED_FINGERPRINT          = cc0e4c0e16c7e2ec8cecb4ba871afc3af1a402e94732e645fceb4b1aca73771d
                                  （MANIFEST.sha256.txt 的 SHA256；seed 原值未读取/未输出）

INITIAL_BLESSED_TICK            = N/A（禁止自行假设；应由尚未实现的激活契约定义）
ACTIVATION_TIME_ANCHOR          = N/A

INITIAL_OFFICIAL_HISTORY_EVENTS = N/A（世界未激活 → 官方事件 0）

SCHEDULER_STATE_T0              = DORMANT
SCHEDULER_STATE_T5M             = DORMANT
SCHEDULER_STATE_T10M            = DORMANT
SCHEDULER_STATE_T15M            = DORMANT

CURRENT_TICK_T0                 = NULL
CURRENT_TICK_T5M                = NULL
CURRENT_TICK_T10M               = NULL
CURRENT_TICK_T15M               = NULL

ACTIVE_WRITER_COUNT             = 0
STALE_WRITER_MUTATIONS          = 0

HISTORY_ORPHAN_LINKS            = 0
HISTORY_CAUSAL_CYCLES           = 0
HISTORY_INVALID_REFS            = 0

BLIND_ACTIVATION_RETRY_COUNT    = 0

SECOND_ACTIVATION_ATTEMPT       = NOT_PERFORMED
ACTIVATION_IDEMPOTENCE_RUNTIME  = NOT_APPLICABLE

FIRST_LAUNCHER_STOP             = NOT_PERFORMED（未进入 M6.1）
SECOND_LAUNCHER_START           = NOT_PERFORMED
ACTIVATED_RESTART               = NOT_PERFORMED

TICK_AFTER_RESTART              = N/A
HISTORY_AFTER_RESTART           = N/A

PRIVATE_COMPANION_SOURCE_UNCHANGED = TRUE

M6_ACTIVATION = BLOCKED_PREFLIGHT
M6_WORLD_LIVE = FALSE

NEXT_ACTION = AWAIT_OWNER_DECISION_ON_M6_ACTIVATION_IMPLEMENTATION
              （授权独立 M6 激活实现阶段，或维持世界未激活）
```

**STOP** — 未消费 World Seed；未创建正式 `world_runtime` 行；未推进 blessed tick；
未运行 simulation；未生成正式 history；未进入 M6 激活。
