# M6C.2 — Pre-implementation reconnaissance findings

**MILESTONE**: M6C.2 — PRODUCTION SNAPSHOT_V1 MATERIALIZER IMPLEMENTATION
**STATUS**: RECON COMPLETE / IMPLEMENTATION STARTING
**OWNER RATIFICATION**: `SNAPSHOT_V1 = APPROVED`, `MATERIALIZER_IMPLEMENTATION_ALLOWED = TRUE`
（`FORMAL_WORLD_MATERIALIZATION_ALLOWED / FORMAL_ACTIVATION_ALLOWED /
WORLD_SEED_CONSUMPTION_ALLOWED = FALSE`）

---

## §0 Ratification provenance（已记录）

```
SNAPSHOT_V1_APPROVAL_HEAD      = 557e1bf
                                 (docs: close M6D3 extended baseline refreeze verification)
FORMAL_DB_ALEMBIC_HEAD         = a9d4f2b7c1e8
FORMAL_WORLD_DB_SHA256         = 7754b1d4658ea94ce509ae7fb7c06c33c44f98782021b3708e6f29ce69102837
FORMAL_WORLD_RUNTIME_ROWS      = 0
CURRENT_BLESSED_TICK           = NULL
FORMAL_WORLD_STATUS            = NOT_ACTIVATED
WORLD_SEED_STATUS              = PREPARED_NOT_ACTIVATED
WORLD_SEED_CONSUMED            = FALSE

ORIGINAL_M3A_M3B_REFREEZE_COUNT       = 12
M3_INTEGRATED_REFREEZE_COUNT          = 7
AUTHORIZED_BASELINE_REFREEZE_COUNT_TOTAL = 19
UNAUTHORIZED_BASELINE_MUTATIONS       = 0
```

（正式世界在开始/结束时各由 authoritative resolver 复核，sha256 未变。）

---

## §1 Recon 结论：production 已具备 canonical 原语

`services/activation/bootstrap_canon.py`（production，非 test）已实现：
`RA-ALLOC-001`（`allocate` / `verify_allocation` / `render_matrix` /
`allocation_digest`）、`RA-COHORT-001` 机制原语（`cohort_survivor_weights` /
`apportion_largest_remainder` / `cohort_counts`）、owner 批准常量
（12000 / 4 MAIN × 2000 / 8 SAT × 500）、`dumps_canonical`。

`allocation_digest(RA-ALLOC-001 矩阵) =
8dfe3471c1ff9d9c93646df18e4f55335cb93ca634c4afc96a17c86b5b28c457`
—— 与 owner 已批准的 `matrix_sha256` **逐字节一致**；列合计
`(2000×4, 500×8)`、行合计 `(4000, 3000, 2500, 2500)` 均由
`verify_allocation` 强制。

⇒ Materializer 无需 import `tests.*` / synthetic fixture（§20 可直接满足）。

## §2 Recon 发现（实现前必须解决）：RA-COHORT-001 v1.0 vs **v1.1**

production `bootstrap_canon.cohort_counts` 标注 **v1.0**，其语义为"存活曲线在
**全部 bucket** 上分配、末桶不聚合"；而 owner §4 正式批准的
`RA-COHORT-001 v1.1`（= 已批准 payload 实际使用、且与引擎
`bucket_of(age) = min(age, N-1)` 的 **开区间末桶** 语义一致）把
"年龄 ≥ N-1" 的存活者**聚合进末桶**。

同一输入（61 buckets、mortality 1/60）实测差异（`scripts/_m6c2_cohort_equivalence.py`）：

| cell total | v1.0（production 现状） | v1.1（owner 已批准） |
|---|---|---|
| 666 | `[17,17,17,16,…,7,7,7,6,6]`（61 桶，末尾 6） | `[11,11,11,11,10,…,4,4,4,4,243]`（末桶聚合 243） |
| 167 | `[4,4,4,4,…]`（末尾 2） | `[3,3,3,3,…,1,1,1,1,61]`（末桶 61） |

结论（无需 Owner 追加裁决，依 §4/§11 既有批准）：
**M6C.2 必须实现 v1.1**（§11 明确要求使用 RA-COHORT-001 v1.1），
做法是在 `bootstrap_canon` 内把末桶聚合语义补齐、`RULE_COHORT_VERSION` 升为
`"1.1"`，并在 provenance 记录"v1.0 标签下的截断语义被 v1.1 批准所取代"。
影响面：仅 bootstrap cohort 分配（mini_world 基线不经过该规则 ⇒
**不改变任何已批准 Golden Baseline**；§34 `AUTHORIZED_BASELINE_SET_UNCHANGED = TRUE`）。

## §3 Recon 发现：resource registry 8 vs DB 行 7（口径记录，避免误读）

owner §12：正式 registry **8 profiles**（7 消费类 + `RESOURCE_SLOT_08` registry-only）、
消费类 **7**、生产节点 **7**、库存 **84**；M6D.3 参考运行实测
`RESOURCE_PROFILE_ROWS = 7`、`RESOURCE_NODE_ROWS = 7`、`RESOURCE_STOCK_ROWS = 84`。

⇒ 采取的口径：`RESOURCE_SLOT_08` **进入 registry 声明（`materialized: false`）**，
不落 DB 行、不建节点/库存/需求；DB 内 profile 行 = 7。
只有这一口径能与 §27/§28/§29（参考运行 hash 与 300y 数值必须逐值复现）自洽。

## §4 权威 bootstrap payload 来源（已定位）

逐行构造的权威参考：`tests/m6c1d_runner.py::write_bootstrap_rows`（test-only，M6D.3
参考运行即由此出生）。Materializer 将把**同一 row payload** 搬进 production，
数据来源改为 **frozen SNAPSHOT_V1.json**，不 import tests。

实测参考构建规模：settlements 12、population_groups 12×4×61 = 2928、
resource profiles 7 / nodes 7 / stocks 84、production_state 84、recipes 7、
ecology zone 1（`ZONE-01`）/state 1/feedback 1、social 24、tribulation schedules 3
（REGULAR 10 / MAJOR 50 / CENTENNIAL 100，first omen tick 10,000,000）。

## §5 后续执行顺序（M6C.2 计划）

1. §1–§4：生成 `docs/world_creation/SNAPSHOT_V1.md` / `SNAPSHOT_V1.json`
   （approved header、rule versions、registry 8/7 口径、无 blocking 字段）、
   `SNAPSHOT_V1_APPROVAL.md` + `SNAPSHOT_V1_SHA256`。
2. §5–§23：`services/activation/materializer.py`（唯一 high-level 入口
   `materialize_snapshot_v1(...)`，仅由 activation transaction 调用；含
   `BOOTSTRAP_DEPENDENCY_GRAPH`、snapshot hash guard、pristine-world 前置断言、
   formal profile fail-closed），并接入 `activate_formal_world` 同一事务。
3. §24–§32：crash matrix（settlement/population/resource/economy/ecology/social/
   tribulation 各点 pre-commit fault → durable zero）、并发 activation、
   bootstrap determinism（跨进程 + PYTHONHASHSEED 0/42/default）、
   snapshot↔materialized equivalence、300y 参考复现（POP/HABITAT/EPISODES/
   CASUALTIES/SHORTAGE + `FINAL_STATE_HASH 8870f2a9…` /
   `CANONICAL_HISTORY_HASH 72853761…`）、300y×2 + restart 等价、history integrity、
   PG smoke（不触碰 stayops-postgres）。
4. §34–§35：回归（materializer / activation / crash / M2 / M3 / M6 / history /
   determinism / restart / PG）+ canonical fast regression；
   `BASELINE_MUTATIONS = 0`。
5. §36：三个独立 commit（feat / test / docs），无 amend/rebase/force、无 freeze tag。
