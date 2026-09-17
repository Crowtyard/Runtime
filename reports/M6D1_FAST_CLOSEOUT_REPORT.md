# M6D.1 — FAST CLOSEOUT REPORT

**FAST_REGRESSION = PASS**
**M6D1_DETERMINISM_REPAIR = PASS**
**P2_B_FINAL_STATUS = OWNER_RATIFIED_FOR_SNAPSHOT_V1**
**NEXT_ACTION = RUN_M6D2_FINAL_INTEGRATED_VERIFICATION（已启动，见 §6）**

本轮无 production 改动（除已完成并接受的 M6D.1 ordering fix）、无 baseline 改动、
无人口参数改动、无第二次完整 pytest、无正式激活、无 Materializer。

---

## 1. Fast regression 结果（owner §25）

| 字段 | 值 |
|---|---|
| `FAST_REGRESSION` | **PASS**（进程 exit code 0；1025 个测试标记中 **0 个 `F`、0 个 `E`**） |
| `FAST_COLLECTED` | **1025** |
| `FAST_PASSED` | **983** |
| `FAST_EXPECTED_SKIPS` | **42** |
| `FAST_FAILED` | **0** |
| `FAST_ERRORS` | **0** |
| `FAST_UNEXPECTED_SKIPS` | **0** |

命令（canonical，未改动）：

```
pytest tests -q --ignore=tests/test_m3_integrated_long.py
```

运行方式：后台独立进程，`PYTHONHASHSEED` **未固定**（默认随机化），17:56:59 → 23:0x，
含已知重测 `test_budget_equivalence_1000y_long`（1000/500/250/100/10/7/1 七档）、
`test_scheduler_1000y_reproduces_frozen_seed001`、
`test_scheduler_5000y_endurance_reproduces_frozen`（>50 min）等。

### 1.1 计数口径（重要，避免"复述机器摘要"）

本机 pytest 的最终摘要行（`N passed, M skipped in Xs`）被外层 stdout 捕获吞掉
（多次实测：日志文件仅存进度行）。因此本报告**不引用**该摘要，而用两条独立可复核的口径：

1. **逐文件收集计数求和**：`pytest tests -q --collect-only --ignore=…` 输出 71 个文件
   的 `file: count`，机器求和 = **1025**，与进度标记总数 1025 一致 → `FAST_COLLECTED`。
2. **进度标记机器计数**：15 行进度标记（14×72 + 17）= **1025**；其中 `s` = **42**，
   `F`/`E` = **0** → `FAST_FAILED = FAST_ERRORS = 0`，`FAST_PASSED = 1025 − 42 = 983`
   （与 M6A.1 closeout 的 983 逐值吻合）。

### 1.2 skip 清单逐条对账（`FAST_UNEXPECTED_SKIPS = 0`）
 
| 族 | 数量 | 门禁条件（环境未设置即条件跳过） | 验证方式 |
|---|---|---|---|
| `BLR_FORMAL_DB_PATH` | **12** | 正式库守护测试（`…_formal_db_empty` / `…_integrity_ok` / `…_protected`） | 按 node id 精确运行 13 个受门禁测试 → 13 个 `s`；其中 `zz_formal_db_guard.py::test_pf20_…` 属 **canonical 命令不收集** 的文件（该文件不在 71 个收集文件内，`python_files` 默认模式不含 `zz_*.py`）→ 套件内计 **12** |
| `BLR_TEST_PG_DSN` (+`BLR_TEST_PG_ALLOW=1`) | **30** | PG 集成测试（functional gate 18 / commit-ambiguity 9 / recovery-portability 2 / M6A.1 zero-row concurrency 1） | 机器求和捕获到的 `SKIPPED [n]` 行 = 30，逐条含文件:行号 |
| **合计** | **42** | | 12 + 30 = 42 = 套件进度标记 `s` 总数 ✔ 完全对账 |

与 canonical 基线（M6A.1：12 + 29 = 41）的差值 **+1** 来源明确：
`tests/test_m6a1pg_zero_row_concurrency.py` 是 M6A.1 新增的 PG 门禁测试，
在无 DSN 环境下条件跳过 → 全部 42 个 skip 均为**既有条件门禁**，无新增/无意外跳过。

> 附带观察（非本轮引入、不影响裁决）：`tests/zz_formal_db_guard.py` 因文件名不在
> pytest 默认 `python_files` 模式内而**从未被收集**，其会话级守护不生效；同一保证
> 由套件内 12 个 `BLR_FORMAL_DB_PATH` 守护测试 + `scripts/audit_authoritative_db.py`
> 覆盖。作为**已存在的测试覆盖缺口**记录，本轮不修改。

## 2. Golden baseline

* `GOLDEN_BASELINE_MUTATIONS = 0`
* 依据：(a) 静态下界——所有 committed 基线来自 `mini_world`（`TEST-MAIN-A` order 0 /
  `TEST-SATELLITE-B` order 1，永不并列 → 新增并列键结构上不可能生效）；
  (b) targeted 实测——M2 家族 230 tests / exit 0，含 4 处
  `final_world_state_hash == golden[...]` 逐字节比对；
  (c) 套件跑完后 `git status tests/baselines` **零变更**（工作树整体亦为空）。

## 3. 确定性 gate 汇总（M6D.1）

| gate | 结果 | 证据 |
|---|---|---|
| `PYTHONHASHSEED_INDEPENDENCE` | **PASS** | 0 / 1 / 42 / default(+0 repeat) 五个独立进程：逐年 Y1..Y10、T50、T100 的 state/event hash 与人口逐字节一致（`ea4094a1…` / `178e53ca…`，T50 12009 / T100 12160，`identity_ok = True`） |
| `INTEGRATED_HASH_SEED_GATE` | **PASS** | 真实八相引擎，`PYTHONHASHSEED` 0 vs 1：T1/T4/T10/T50/T100 的 state hash、完整聚落×资源台账、生态压力/质量载荷全同（T100 `f5bf7322…`） |
| production 路径 trace 级验证 | **PASS** | 无任何测试钩子：实体顺序规范（MAIN-01 Hairy Men 起），`FIRST_DIFFERENT_ENTITY_POSITION = None`、`FIRST_DIVERGENT_RNG_CALL_INDEX = None`、`STATE_HASH_EQUAL = True` |
| 5-seed 稳健性（`birth_rate` 未改） | **PASS** | T300 = 12360 / 12490 / 12058 / 12223 / 12564，5/5 落在 `[11400,12600]`，上界余量 36（仅记录，未重新调参） |

## 4. Owner 裁决落库（本轮记录）

```
DEMOGRAPHY_BIRTH_RATE        = 53/1000        （不得重新 calibration）
P2_B_NUMERIC_PROFILE         = OWNER_APPROVED
RA_DEMOGRAPHY_STATIONARY_001 = APPROVED_CALIBRATION_METHOD
P2_B_POST_FIX_MULTI_SEED     = PASS
P2_B_FINAL_STATUS            = OWNER_RATIFIED_FOR_SNAPSHOT_V1
RA_COHORT_001_V11            = APPROVED_FOR_SNAPSHOT_V1
RA_MORTALITY_001             = APPROVED_FOR_SNAPSHOT_V1
M6D1_DETERMINISM_REPAIR      = PASS
```

`coordinator.py:475` 结论（owner §2 已接受）：
`KNOWN_EVENT_ORDER_SITE_FIXED = N/A / FALSE_POSITIVE_CORRECTED` —— AST 实测为
生成器（`GeneratorExp`），非 `tuple(set(...))`；coordinator 未做任何修改。

pre-fix 长期产物降级（owner §8）：`reports/M6C1D_*_PREFIX.json` 及本轮归档的
pre-fix 300y 数值一律 `STATUS = DIAGNOSTIC_NON_AUTHORITATIVE`，保留不删，
最终 Snapshot 不引用其数值。

## 5. 正式世界红线（本轮复核）

```
AUTHORITATIVE_DB_RESOLUTION = PASS      NON_AUTHORITATIVE_DB_DETECTED = False
FORMAL_DB_SHA256            = 7754b1d4658ea94ce509ae7fb7c06c33c44f98782021b3708e6f29ce69102837
FORMAL_WORLD_RUNTIME_ROWS   = 0         FORMAL_WORLD_STATUS = NOT_ACTIVATED
CURRENT_BLESSED_TICK        = None      FORMAL_WORLD_SEED_CONSUMED = FALSE
SNAPSHOT_V1 = NOT_APPROVED              MATERIALIZER_ALLOWED = FALSE
```

## 6. NEXT_ACTION

`RUN_M6D2_FINAL_INTEGRATED_VERIFICATION` —— 依 owner §7 直接进入，未再次请求 Owner。
harness 已就绪并已通过小规模 smoke 验证：

* `scripts/_m6d2_integrated.py`（真实 production synthetic activation path →
  `WORLD_SEED_ACTIVATED` genesis → test-only bootstrap → 八相全管线 + **真实
  `HistoryLinkBuilder` 接线** → 逐年推进 → T0/T10/T50/T100/T300 采集）
* `scripts/_m6d2_driver.py`（RUN1/RUN2 连续 300y 独立进程、`PYTHONHASHSEED` 不固定；
  RUN3a 0→100y（seed 0）+ RUN3b 100→300y（seed 42）新进程重启）

smoke 结果（2y）：`via = activation`、`SELF_CHECK = True`、
`WORLD_SEED_ACTIVATED_GENESIS_COUNT = 1`、`TEST_PROFILE_USAGE_COUNT = 0`、
T0 会计恒等式成立、社会域活跃（`HOUSEHOLD_FORMED = 1220` / `INSTITUTION_FOUNDED = 12`）；
**重启等价 smoke = PASS**：连续 2y 与「1y(seed 0) + 1y(seed 42) 两进程」state/event hash
逐字节相同。
