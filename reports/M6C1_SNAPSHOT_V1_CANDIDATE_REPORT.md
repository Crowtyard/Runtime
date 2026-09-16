# M6C.1 — SNAPSHOT_V1 CANDIDATE CONSTRUCTION 报告（M6C1_SNAPSHOT_V1_CANDIDATE_REPORT）

```
STAGE                              = M6C.1 SNAPSHOT_V1 CANDIDATE CONSTRUCTION
M6C1_STATUS                        = COMPLETED_WITH_BLOCKING_FIELDS
SNAPSHOT_V1_CANDIDATE              = PRODUCED（STATUS = CANDIDATE_NOT_APPROVED）
SNAPSHOT_V1                        = NOT_PRODUCED（需主人批准，Agent 无权升级）
MATERIALIZATION_ALLOWED            = FALSE
FORMAL_ACTIVATION_ALLOWED          = FALSE
MATERIALIZER_IMPLEMENTATION        = NOT_PERFORMED（owner §26 PROHIBITED）
BLOCKING_FIELDS_PRESENT            = TRUE → 停止（不得进入 materializer）
M6C1_READY_FOR_OWNER_REVIEW        = TRUE
M6C_READY                          = FALSE
M6D_READY                          = FALSE
FORMAL_WORLD_ACTIVATED             = FALSE
WORLD_SEED_CONSUMED                = FALSE
LIVE_DEPLOYED                      = FALSE
```

- 前置：`M6A_ACTIVATION_CONTRACT = ACCEPTED`、`M6B_ACTIVATION_BOOTSTRAP & EPOCH CLOSURE = STOP A / M6B_READY = FALSE`、
  `M6C.0 BOOTSTRAP CANON AUDIT = PASS / M6C_CANON_READY = FALSE`
- 本轮 owner 决定：`D-A / D-B1..D-B7 / D-C / D-C2 / D-D / D-E / D-F`（见候选文档 §3）
- 分支：`m5-query-companion`（未建 M6 frozen tag、未 amend / rebase / force）
- 变更类型：**docs + bootstrap-configuration + test**（未改冻结引擎、未加迁移）

---

## 1. 一句话结论

**候选**构造成功且**可独立复算**：本轮主人批准的两组约束（群体名额 `4000/3000/2500/2500`
与每聚落人口 `2000×4 + 500×8`）被 `RA-ALLOC-001 v1.0` **同时精确满足**（双边际零误差，
`matrix_sha256 = 8dfe3471…c457`），首个灾劫前兆时间由冻结引擎**派生**为 10 福地年
（不再需要主人拍年份），M6C.0 的一项误判阻塞（D-B3 职业/户统计）被**代码级撤销**。

但候选**仍存在 REQUIRED root 的 blocking field**：六个正式 profile registry 的**世界法则数值**
与四项世界层内容（S-2/S-4/S-5/S-7）没有可授权来源。按 owner §26 —— **停止**：
未写 materializer、未激活、未消费 Seed。剩余 owner 决策被收敛为 **10 项（OD-1..OD-10）**。

---

## 2. 交付物（本阶段落盘）

| 文件 | 作用 |
| --- | --- |
| `docs/world_creation/SNAPSHOT_V1_CANDIDATE.md` | 人读候选（S-1..S-10、规则、矩阵、行基数、引擎约束、registry 分类、OD 列表、未决项） |
| `docs/world_creation/SNAPSHOT_V1_CANDIDATE.json` | 机读候选（106 个带 `SOURCE_CLASS` 的值节点；`candidate_sha256 = d73cd502…f147`） |
| `services/activation/bootstrap_canon.py` | BOOTSTRAP CONFIGURATION 规则模块（`RA-ALLOC-001` / `RA-COHORT-001`；纯函数、无 DB、无引擎、无 RNG） |
| `scripts/build_snapshot_candidate.py` | 确定性生成器（`--check` 逐字节复现检查） |
| `scripts/validate_snapshot_candidate.py` | **独立**校验器（schema / 来源 / 阻塞披露 / 矩阵复算 / 合计 / 禁测 / 禁物化 / 红线） |
| `tests/test_m6c1_snapshot_candidate.py` | 23 项守卫测试（§29 六类要求全覆盖） |
| `docs/m6c_minimal_bootstrap_canon_audit.md`（ADDENDUM） | M6C.1 审计更正（D-B3）+ 新增引擎证据 |

---

## 3. 主人本轮决定的落地情况

| 决定 | 落地 |
| --- | --- |
| `D-A` SNAPSHOT 流程 | 候选按该流程产出；`SNAPSHOT_V1` 未生成（等主人批准） |
| `D-B1` WS-0406 胜出 | 候选 S-3 = 12（4 主 + 8 卫星）；旧草案标 `SUPERSEDED_FOR_FORMAL_BOOTSTRAP`（原记录保留） |
| `D-B2/B3` 12 聚落 / 工作名 | `MAIN-01..04`、`SAT-01..08`，全部 `WORKING_NAME_ONLY`（候选 JSON 中逐槽位标注） |
| `D-B4/B5/B6` 12000 / 群体名额 / 每聚落人口 | 全部以 `OWNER_APPROVED` 节点记录，且**合计自校验**（12000 = Σ行 = Σ列） |
| `D-B7` 确定性分配 | `RA-ALLOC-001 v1.0` 实现并被独立复算（无 RNG / 无浮点 / 无 hash(seed)） |
| `D-C / D-C2` 正式 registry + 禁回落 | 六 registry 字段级分类；`PRODUCTION_TEST_PROFILE_FALLBACK = FORBIDDEN` 写入候选与校验器 |
| `D-D` 确定性派生 | 4 条规则（ALLOC/COHORT/MORTALITY/TRIB）+ 1 条结构规则；全部带版本、输入、输出、舍入、tie-break |
| `D-E` 灾劫周期 10/50/100 | 以 `OWNER_APPROVED` 记录，并派生首个窗口 tick |
| `D-F` 首个前兆时间 | **已解决**：`RA-TRIB-001` 派生 = tick 10_000_000（10 福地年）；"窗口前导期"概念在冻结引擎中**不存在**（NOT_FOUND） |

---

## 4. 关键工程结论（新增证据）

1. **两阶段分配是必需的**：一维最大余额无法同时满足已批准的行/列约束
   （按容量比例逐行分配会给出 `MAIN = 2001 ≠ 2000`）。故规则 = 列内最大余额（锁列）
   + 列内搬运最小偏离修复（锁行）；列内搬运不改列和 → 双边际精确。
2. **首个前兆可派生**：`PRECURSOR` 阶段**始于**窗口 tick T（`entered_tick = T`），
   引擎**没有** pre-T 前导期 → "首个前兆时间"不是选择题，而是 `RA-TRIB-001` 的输出；
   仍待批准的是 `precursor_steps`（T 之后的持续时长）。
3. **D-B3 阻塞撤销**：`occupation_group` 无引擎读取（仅影响 snapshot 行序与 state hash），
   `household_stats` 零读零写且不在投影内 → 主人**不需要**为职业结构与户统计口径裁决。
4. **新增 bootstrap 义务（EC-4）**：`population_groups` **无**任何唯一约束，而同一 bucket
   的两行会重复计数、缺行会静默丢人口（违 P_INV_12）→ "每 `(species, settlement)` 恰好
   覆盖 `0..N-1` 各一行"必须由物化器自行保证。
5. **新增危险项（EC-5）**：`population_capacity` 若等于初始人口 → 出生率被 logistic 收缩
   归零（人口永久冻结）→ 该值必须显式裁决（OD-4）。
6. **中性态有引擎定义**：`economic_pressure_state` / `ecology_feedback_state` /
   `settlement_social_state` 的 server default（0 / `NONE` / 分母 1 / 凝聚力 1_000_000）
   可直接作为"引擎定义中性初始态"引用，无需主人逐个给值。

---

## 5. 剩余阻塞（最小集：10 项）

```
OD-1  S-2 异人种族组合（species 身份；名额已批准）
OD-2  S-4/S-5/S-6/S-7/S-8/S-9 世界层内容（S-1/S-3/S-10 已解决）
OD-3  人口世界法则数值（cohort_buckets / fertile / birth / mortality / emigration / weights）
OD-4  每聚落人口容量法则（NULL 或 > 初始人口的数值）
OD-5  S-4 产业（production_recipes）
OD-6  资源集合与正式 resource profile
OD-7  初始经济状态（库存 / per_capita_demand / pressure 行）
OD-8  生态世界法则数值（正式 EcologyProfile）
OD-9  社会世界法则数值（正式 SocialProfile 阈值）
OD-10 灾劫正式 profile 数值 + 去除 `profiles or TEST_PROFILES` 静默回落
```

细节、证据与可选项见 `docs/world_creation/SNAPSHOT_V1_CANDIDATE.md` §9。
**不阻塞**项（S-6/S-8、`ecological_regions` 业务键、迁移权重按聚落区分）见同文 §10。

---

## 6. 校验与测试证据

```
python scripts\build_snapshot_candidate.py            → WROTE + candidate_sha256 d73cd502…f147
python scripts\build_snapshot_candidate.py --check     → REPRODUCIBLE（逐字节无漂移）
python scripts\validate_snapshot_candidate.py          → PASS
    attributed_nodes = 106 / owner_approved = 19 / derived = 18 / neutral = 31 / blocked = 19
    matrix_sha256 = 8dfe3471c1ff9d9c93646df18e4f55335cb93ca634c4afc96a17c86b5b28c457
    materialization_allowed = False
pytest tests\test_m6c1_snapshot_candidate.py           → 24 passed
pytest tests\test_m6c_bootstrap_canon_guard.py         → 6 passed（M6C-G01..G06 未回退）
```

§29 六类要求 → 测试映射：

| §29 要求 | 测试 |
| --- | --- |
| 候选 schema 校验 | `m6c101`–`m6c105`、`m6c114`–`m6c118` |
| 人口/聚落/群体合计 | `m6c106`、`m6c107` |
| 确定性分配 | `m6c108`、`m6c109`、`m6c110`、`m6c111`、`m6c112` |
| 无 TEST registry | `m6c118`、`m6c119` |
| 无 materializer | `m6c120`、`m6c105`（无 `SNAPSHOT_V1.*` 已批准工件） |
| 无生产变更 | `m6c121`、`m6c122`、`m6c123` |

（完整回归：M6A/M6B/M6C 系列合并运行结果见 §8。）

---

## 7. 本阶段明确未做的事（owner §26/§28）

```
未实现 materializer（未新增任何物化函数/类；M6C-G03 门禁仍通过）
未激活正式世界            未消费正式 Seed        未读正式 Seed 原值
未写正式库                未新增 alembic 迁移     未改冻结 M2/M3 语义
未把测试 profile 改名当正式 profile          未接任何测试 registry 到正式路径
未使用 RNG / hash(seed) 生成世界内容          未部署 live
未生成 SNAPSHOT_V1（校验器显式禁止 SNAPSHOT_V1.md/json 存在）
```

---

## 8. 回归结果（M6 全系列合并运行）

命令：`pytest tests/test_m6_activation_*.py tests/test_m6b_*.py tests/test_m6c*_*.py
tests/test_m6_world_seed_safety.py -q`

```
RESULT            = PASS（exit code 0）
COLLECTED         = 140
PASSED            = 140
FAILED            = 0
ERRORS            = 0
覆盖              = M6A(5 文件) + M6B(3 文件) + M6C 门禁(6) + M6C.1(23) + seed safety
说明              = 未新增/未修改任何既有测试；未改冻结引擎；未新增迁移
```

`GOLDEN_BASELINE_MUTATIONS = 0`（未触碰 `tests/baselines/**`）。

---

## 8b. 正式红线：本阶段结束时**只读实测**（不只是继承断言）

工具：`sqlite3` `mode=ro` 只读连接（不写、不建 sidecar）+ `Get-FileHash`。

```
FORMAL_DB_PATH（权威）  = C:\Users\<user>\.astrbot_launcher\instances\<instance-id>\
                          core\data\plugin_data\astrbot_plugin_blessed_land_runtime\
                          blessed_land.sqlite
FORMAL_DB_SIZE          = 544768 B      SIDECARS = -wal 0 B / -shm 32768 B
FORMAL_DB_SHA256        = 7754b1d4658ea94ce509ae7fb7c06c33c44f98782021b3708e6f29ce69102837
                        → 与 M6.0–M6C 基线**逐字一致**（未漂移）
world_runtime           = 0 行（canonical：0 行 == 世界未激活）
非空业务表              = 0（唯一非空表 alembic_version = a9d4f2b7c1e8）
```

**新发现（重要，防误判）**：`D:\MY SELF\AstrBot\data\plugin_data\...\blessed_land.sqlite`
是一份**非权威过期副本**（mtime 2026-09-10、sha256 `e0c5d32f…8203`、**`world_runtime = 1` 行**）。
live 实例库位于 **launcher instance 路径**。若红线检查指向该副本，会得到
"world_runtime = 1" 的**假阳性违规**。候选已把该陷阱写入
`formal_world_redline_measurement.decoy_warning`，并由校验器强制要求
（路径必须含 `instances`、必须实测 0 行、必须披露诱饵），测试 `m6c103b` 钉住。

---

## 9. 停止点

```
STOP。不得实现 Materializer。不得激活正式世界。不得消费正式 Seed。
等待主人对 OD-1..OD-10 的裁决 → 若全部落地，则本候选可升级为 SNAPSHOT_V1。
```
