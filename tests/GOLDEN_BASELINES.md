# Golden Baseline 政策（TEST_INFRA_HARDENING）

> 本文件描述 `tests/baselines/` 下 golden baseline 的不可变策略与更新流程。
> 只属于测试基础设施约束，不改变任何 simulation semantics。

## 规则

1. **普通 pytest 只读 golden**：任何测试运行都不得改写 `tests/baselines/`
   下的 committed golden baseline。candidate artifact 只允许写入
   `tmp_path`（`tests/golden_baseline.py::write_candidate`）。

2. **candidate ≠ golden → FAIL**：artifact 测试生成 candidate 后，必须与
   committed golden 做确定性字段深度比较（`assert_deterministic_equal`）。
   任何确定性差异直接失败，绝不自动覆盖 baseline 后 PASS（GB10）。

3. **telemetry 不参与确定性比较**：`wall_seconds`、`wall_seconds_queries`、
   `query_latency_ms`、`performance`、`db_size_mb`、`db_growth` 等
   机器/耗时相关字段在比较前深剥离（GB3）。

4. **effective hash schema version**：artifact 中的
   `world_state_hash_schema_version` 必须记录“实际计算该 final hash 使用
   的 schema version”（M2b=3 / M2c=4 / M2d=5 / M3a=6），绝不引用代码库
   当前最高活值（GB4–GB8）。未来引入 v7/v8 不会漂移旧 milestone 标签。

5. **更新必须显式 opt-in**：唯一合法写 golden 的路径是
   `python scripts/update_baselines.py`（内部设置
   `BLR_UPDATE_GOLDEN_BASELINES=1` 并只运行 artifact 测试）。普通
   `pytest` 永远不启用更新模式（GB9）。

6. **更新流程 = 人工 review + 独立 commit**：
   - `python scripts/update_baselines.py`
   - `git diff tests/baselines/`（人工审查，确认 diff 仅为预期字段）
   - `git add tests/baselines/ && git commit -m "test: refresh golden baselines (explicit update)"`

## 守卫机制

| 守卫 | 层级 | 机制 |
|---|---|---|
| GB1 | 会话 | `tests/conftest.py` sessionstart 记录 `tests/baselines/` 全目录 sha256 快照，sessionfinish 比对，有差异则 exitstatus=1 |
| GB2 | 模块 | 各 artifact 测试模块通过 `golden_bytes_guard` autouse fixture 在**每个测试**前后校验其 golden 文件字节不变 |
| GB3–GB8 | 语义 | `tests/test_golden_guards.py` 校验 telemetry 剥离与 effective hash schema 标签 |
| GB9 | 流程 | `dump_artifact` 在非更新模式下直接 RuntimeError |
| GB10 | 语义 | `assert_deterministic_equal` 只比较不写 |

## 文件

- `tests/golden_baseline.py` —— 共享 helper（比较/剥离/effective 版本/守卫工厂）
- `tests/test_golden_guards.py` —— GB1–GB10
- `scripts/update_baselines.py` —— 唯一显式更新入口
