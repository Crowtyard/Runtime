# DSH_M2B_COMMIT_AMBIGUITY_HARDENING_FINAL_REPORT

> 执行方：DSH。任务：M2B_COMMIT_AMBIGUITY_HARDENING。
> 目标唯一：确认并正确覆盖真正的 COMMIT ACK LOST / AMBIGUOUS COMMIT
> OUTCOME。禁止重做 Resource/Economy Engine；禁止进入 M2c。
> 基线：M2B_RESOURCE_ECONOMY_ENGINE_READY（a6134ec，260/260）。

## 1. 审计结论：现有 R8 的真实语义
原 M2b 报告把 R8 写作「commit ack lost（after_checkpoint）」。审计
`services/simulation/coordinator.py` 崩溃注入点：`crash_after=
"after_checkpoint"` 在 **WORLD checkpoint 行写入 session 之后、DB
commit 之前** raise —— 异常发生在事务内，`WorldMutationContext.
__exit__` 回滚，**DB commit 从未发生**。因此其真实语义是 A
（异常在 commit 完成之前），**不是** COMMIT ACK LOST。

`existing_R8_actual_semantics = PRE_COMMIT_AFTER_WORLD_CHECKPOINT_STAGED`

## 2. 重命名（已执行）
- `tests/test_m2b_resource_economy.py` 崩溃矩阵参数化 id：
  `R8-pre-commit-after-world-checkpoint-staged`（原「R8：commit ack
  lost」注释删除）；RB42 注释同步更正。
- `runtime_design/M2B_RESOURCE_ECONOMY_ENGINE.md` §24 与
  `DSH_M2B_RESOURCE_ECONOMY_ENGINE_FINAL_REPORT.md` §26 同步更正，
  并注明真实 ACK LOST 由本任务的 CA 套件覆盖（KB 副本已同步）。

## 3. 真实 COMMIT ACK LOST 测试（CA2 实测）
注入方式（测试专用，不修改生产代码）：monkeypatch
`WorldMutationContext.commit` —— **先执行真实 durable commit，成功后
再抛 RuntimeError**，等价于「DB COMMIT SUCCESS + 调用方未收到确认」。

`true_commit_ack_lost_test = CA2（tests/test_m2b_commit_ambiguity.py）`

`db_state_after_commit_before_ack = COMMITTED`
- current_blessed_tick = 1,000,000（时钟已 durable 推进）
- last_committed_real_us = interval end（游标已 durable）
- simulation_run.status = COMMITTED（run 身份已 durable）
- remaining_reserve < 初始储量（开采已 durable）
- population ≠ 400（DEMOGRAPHY 已 durable）
- world_events > 0（TIME_ADVANCE + domain events 已 durable）
- TIME_COMMITTED ×1 + WORLD_COMMITTED ×1（双层 checkpoint 已 durable）

## 4. Restart 行为（CA3–CA12 实测）
同 world_id / simulation_version / real interval / run identity 重启：
catch_up 阶段 0 依据 committed clock cursor（world_runtime.
last_committed_real_us == interval end）+ committed simulation_run 行 +
authoritative WORLD_COMMITTED checkpoint 判定 ALREADY_COMMITTED，
返回 skipped=True / delta_ticks=0。

`restart_result = ALREADY_COMMITTED (skipped=True, delta_ticks=0)`
`duplicate_mutations = 0`（population/reserve/stock/cum 计数器全部
逐字段不变：CA3/CA4/CA5/CA6/CA7）
`duplicate_events = 0`（event uid 集合不变：CA8）
`duplicate_checkpoints = 0`（WORLD_COMMITTED 仍为 1、TIME_COMMITTED
仍为 1：CA9）
时间零追加推进：tick 恒 1,000,000（CA10）
`state_hash_match = TRUE`（CA11：重启后 world_state_hash == 首次
committed hash，无双链）
`event_stream_hash_match = TRUE`（CA12：event_stream_hash == 首次
committed hash，无双事件链）

## 5. Fencing 接管（CA13 实测）
A commit 成功 → ACK lost → A 死亡（租约过期，不释放）→ B CAS 接管
（新 fencing token）→ B 收到同 interval 请求：
- B 的 catch_up 返回 skipped=True（ALREADY_COMMITTED），不重跑。
- tick/population/reserve/stocks/events/checkpoints/双哈希全部与 A
  首次 committed 一致。
- committed run 行保留 A 的 writer_id/fencing_token —— 幂等识别
  完全基于 durable DB evidence，与当前 token 无关。

## 6. Fencing 变更不破坏幂等（CA13 附证）
fencing token 由 A → B 变化后，同区间重放仍 0 mutation / 0 events /
0 checkpoints / 0 time advance —— 幂等身份（world_id +
simulation_version + real interval + status=COMMITTED + committed
clock cursor + WORLD_COMMITTED）与 fencing token 解耦。

## 7. CA1：现有 R8 语义实证
`test_ca1_existing_r8_true_semantics_pre_commit`：
- 源级断言：矩阵 id 已更名为 `R8-pre-commit-after-world-
  checkpoint-staged`，不再自称 ack lost。
- 语义实证：after_checkpoint 注入后 DB 状态 = tick 0 / 0 events /
  0 checkpoints（durable 全空）—— 与 CA2（durable 全在）形成对照。

## 8. SQLite / PostgreSQL 语义登记
`PG_gate_status = PRE_ACTIVATION_PG_COMMIT_AMBIGUITY_GATE = REQUIRED`
（登记于 runtime_design/M2B_RESOURCE_ECONOMY_ENGINE.md §28 +
DSH_M2B_RESOURCE_ECONOMY_ENGINE_FINAL_REPORT.md §35 + 本报告）：
真实 COMMIT ACK ambiguity 是数据库事务层问题；当前以 SQLite 实跑
CA1–CA13，**不声称 PostgreSQL 已验证**；未来 PG 部署的 Pre-
Activation Gate 必须重跑同类场景。

## 9. 回归
- 新增 CA1–CA13 全部 PASS。
- 原 260/260 全保留（R8 仅改名，注入值 after_checkpoint 不变；
  生产代码零改动 —— 本次为纯测试/文档硬化）。
- 全套件见报告末 TOTAL 段（含正式库守护开启运行）。
- 正式 DB 零测试世界：FORMAL_AUDIT_M2B 复跑 PASS（NOT_ACTIVATED /
  seed=NULL / tick=NULL / 全表 0 / head=b7d2f4e9c1a5 / integrity ok；
  sha256 不变）。

## 10. 变更清单
- `tests/test_m2b_resource_economy.py`：R8 改名（param id + 注释）。
- `tests/test_m2b_commit_ambiguity.py`（新增）：CA1–CA13。
- `runtime_design/M2B_RESOURCE_ECONOMY_ENGINE.md`：§24 语义更正 +
  §28 登记 PG gate（KB 副本已同步）。
- `DSH_M2B_RESOURCE_ECONOMY_ENGINE_FINAL_REPORT.md`：§26/§35 更正。
- 本报告（新增）。

---

```
existing_R8_actual_semantics = PRE_COMMIT_AFTER_WORLD_CHECKPOINT_STAGED
true_commit_ack_lost_test = CA2（post-durable-commit 注入，tests/test_m2b_commit_ambiguity.py）
db_state_after_commit_before_ack = COMMITTED（tick=1,000,000 / run=COMMITTED / 事件与双层 checkpoint 全 durable）
restart_result = ALREADY_COMMITTED（skipped=True, delta_ticks=0）
duplicate_mutations = 0
duplicate_events = 0
duplicate_checkpoints = 0
state_hash_match = TRUE
event_stream_hash_match = TRUE
PG_gate_status = PRE_ACTIVATION_PG_COMMIT_AMBIGUITY_GATE = REQUIRED
TOTAL_TESTS = 273
TOTAL_PASS = 273

M2B_COMMIT_AMBIGUITY_HARDENED
```

（完成后 STOP：不进入 M2c。等待主人下一条明确批准。）
