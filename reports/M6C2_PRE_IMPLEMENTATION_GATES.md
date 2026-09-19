# M6C.2 — PRE-IMPLEMENTATION GATES（A/B/C/D/E）

**STATUS**: GATES CLOSED → production Materializer implementation may proceed
**RED LINES（不变）**: `FORMAL_WORLD_MATERIALIZATION_ALLOWED = FALSE`、
`FORMAL_ACTIVATION_ALLOWED = FALSE`、`WORLD_SEED_CONSUMPTION_ALLOWED = FALSE`、不得部署 live

---

## A. Snapshot Deployment Availability Gate — CLOSED

唯一 deployment builder = `scripts/build_deployment_package.py`（M5.1，zip 根暴露
metadata.yaml/main.py；`PACKAGE_DIRS` 只含 config/database/domain/services/
plugin_shell/pages；`EXCLUDE_DIR_PARTS` 含 **docs**）。

审计结论（修复前）：

```
SNAPSHOT_V1_DEV_PATH       = docs/world_creation/SNAPSHOT_V1.json
SNAPSHOT_V1_DEPLOYED_PATH  = （无；docs/ 被整体排除）
DEPLOYMENT_PACKAGE_INCLUDES_SNAPSHOT_V1 = FALSE
```

⇒ 直接假定"dev checkout 有 = live package 有"会**不成立**（owner §A 的担忧成立）。

## B. Single-source 方案 — 采用**方案 1**（精确 whitelist），GATE CLOSED

`scripts/build_deployment_package.py` 新增：

```python
SNAPSHOT_WHITELIST = ("docs/world_creation/SNAPSHOT_V1.json",)
SNAPSHOT_V1_APPROVED_SHA256 = "592d23e2…3aa8b1"   # 部署完整性断言（非第二份 payload）
```

* `docs/` 目录**仍整体排除**；只有这一个 approved JSON 被显式加入；
* 未在 `services/...` 复制第二份 payload ⇒ 不存在两个可编辑真值源；
* builder 自校验新增：`DEPLOYMENT_PACKAGE_INCLUDES_SNAPSHOT_V1`、
  `SNAPSHOT_V1_SHA256_IN_PACKAGE`、`SNAPSHOT_V1_PACKAGE_INTEGRITY`
  （从 zip 内读取字节并与 approved SHA256 比对）。

实测（构建到临时路径，未部署）：

```
SNAPSHOT_V1_DEPLOYED_PATH               = docs/world_creation/SNAPSHOT_V1.json
DEPLOYMENT_PACKAGE_INCLUDES_SNAPSHOT_V1 = TRUE
SNAPSHOT_V1_SHA256_IN_PACKAGE           = 592d23e2606ef9ff223aa264c64176a82a7f87bc1521d80e33152ffbaf3aa8b1
SNAPSHOT_V1_PACKAGE_INTEGRITY           = PASS
METADATA_VISIBLE_AT_EXPECTED_ROOT = True   MAIN_VISIBLE_AT_EXPECTED_ROOT = True
NESTED_ROOT = False   FORBIDDEN_CONTENT = False   FILE_COUNT = 107
PACKAGE_STRUCTURE_VALID = True

SNAPSHOT_MACHINE_TRUTH_COUNT = 1
```

⇒ Materializer 可**同时**在 dev checkout 与 live package 中按同一相对路径解析：
`<plugin_root>/docs/world_creation/SNAPSHOT_V1.json`（zip 根即 plugin root）。

## C. Snapshot Hash Guard 规格（将在 Materializer 内实现）

```
必须校验（任一不满足 → FAIL CLOSED）:
  artifact path = <plugin_root>/docs/world_creation/SNAPSHOT_V1.json
  header.version  = "SNAPSHOT_V1"
  header.status   = "APPROVED"
  sha256(file bytes) = 592d23e2606ef9ff223aa264c64176a82a7f87bc1521d80e33152ffbaf3aa8b1
禁止任何 fallback：CANDIDATE / hard-coded dict / test fixture / 旧 snapshot。
```

## D. RA-COHORT v1.1 Caller Audit — CLOSED

审计范围：`services/**`、`plugin_shell/**`、`config/**`、`database/**`、
`domain/**`、`pages/**`、`main.py`。

```
EXISTING_PRODUCTION_CALLERS_AFFECTED_BY_V1_1 = 0
```

`cohort_counts` / `cohort_survivor_weights` / `apportion_largest_remainder` /
`RULE_COHORT_*` 在 production 中**只出现在 `services/activation/bootstrap_canon.py`
自身**（定义 + 规则声明）；`main.py` 无引用；无任何 formal simulation caller。
⇒ 仅记录，无需针对既有 caller 的 targeted regression；M2/M3 baseline 未被触及
（`AUTHORIZED_BASELINE_SET_UNCHANGED = TRUE`）。

## E. TEST_FIXTURE_REFERENCES 字段口径 — 已修正

```
TEST_FIXTURE_REFERENCES = PENDING_MATERIALIZER_IMPLEMENTATION
```

Materializer 完成后执行 **AST/import scan**：禁止 production Materializer（及其在
`services/activation` 内的 production 导入闭包）出现
`tests.*` / `m6c1d_runner` / synthetic fixture registry / `TEST_PROFILES` /
`TEST-SPECIES` / `mini_world`。扫描实际 PASS 后才可写
`TEST_FIXTURE_REFERENCES = 0`。

（备注：仓库其它 production 模块如 `services/simulation/mini_world.py`、
`population.py::TEST_SPECIES_PROFILE` 属既有 test-harness 夹具，另有
`TEST_PROFILE_USAGE_COUNT` 门禁覆盖；本条扫描只针对 Materializer 闭包，
不扩大既有范围。）
