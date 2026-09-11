# M4 Scheduler Architecture Audit（M4.0 Preflight）

> 只读调查结果（2026-09 M4 开工）。基线：292446f（tag m3-integrated-engine-set-frozen），
> 分支 m4-scheduler。原则：复用冻结设施，不复制 Engine，不改变冻结语义，
> 适配 Scheduler 而非修改 Engine。

## 1. 现有设施清单（复用决策）

| # | 关注点 | 现有实现 | 文件 | 复用/新增 |
|---|---|---|---|---|
| 1 | 插件入口 | `BlessedLandRuntimePlugin`(AstrBot Star) initialize/terminate | main.py | 复用；terminate 时接 Scheduler 停 |
| 2 | 生命周期宿主 | `RuntimeHost` boot/shutdown/status/diagnostics | plugin_shell/runtime_host.py | 复用；附加 attach/detach scheduler |
| 3 | 冻结引擎调用 | `run_m3a_world`（年步进 + `next_tribulation_boundary` 拆分 + `catch_up` + `coordinator.run_step`） | services/simulation/m3a_runner.py | 只读复用其**年步进序列约定**；Scheduler 侧以 adapter 复刻年步循环（见 §3） |
| 4 | Offline catch-up | `catch_up()`：幂等/分段积分/run 生命周期/双 fenced 事务 | services/catchup.py | 复用（唯一权威推进入口） |
| 5 | 权威状态存储 | `world_runtime` 行（current_blessed_tick / last_committed_real_us / time_rate_remainder / current_time_ratio_id） | database/models_core.py, repositories.py | 复用；Scheduler 只读 |
| 6 | History 存储 | M3b 表 + `HistoryService`（只读查询） | services/history/ | 复用；写入经 coordinator history_builder（与 Scheduler 无关） |
| 7 | 事务/提交边界 | `WorldMutationContext`（commit 前重验 fencing token） | services/fencing.py | 复用 |
| 8 | 单写者/租约 | `WriterLease`：acquire(立即提交)/renew/release/CAS 接管；lease_token 即 fencing token 载体 | services/writer_lock.py | 复用 |
| 9 | 崩溃注入 | `coordinator.run_step(crash_after=…)` 注入点 + M3c `_run_m3_adversity` harness | services/simulation/coordinator.py, tests/test_m3_integrated_long.py | 复用；Scheduler 自身新增 operational 注入点（test-only） |
| 10 | ACK-lost | M3c `patched_commit`（durable commit 后抛异常） | tests/test_m3_integrated_long.py | 复用模式 |
| 11 | 可观测性 | `RuntimeHost.status()/diagnostics()/runtime_info()`（只读） | plugin_shell/runtime_host.py | 扩展：新增 scheduler 段（§18 字段） |
| 12 | 配置 | `Settings`(frozen dataclass) + `_conf_schema.json`(AstrBot schema) | config/settings.py, _conf_schema.json | 扩展：新增 scheduler 字段（integer ms/ticks）+ 严格校验 |
| 13 | 确定性测试时钟 | 现实时间注入（`EPOCH0_US + n*YEAR_US`），不依赖 time.sleep | tests/conftest.py, M3c harness | 复用模式：Scheduler 注入 `real_now_us_provider` |
| 14 | 激活守卫 | `require_world_activated()`（status==ACTIVE 且 seed 非空） | services/guard.py | 复用（Activation Gate 判定源） |
| 15 | 时间转换原语 | `time_engine.rate_at/segment_interval/Integrator`（整数/有理） | services/time_engine.py | 只读规划用（§4）；权威转换仍在 catch_up |

## 2. 关键机制结论（决定设计）

1. **引擎执行粒度 = 1 福地年/次 run_step**：`run_m3a_world` 逐年推进；`next_tribulation_boundary`
   返回的边界在冻结合成排期下恒为年边界（窗口=整数年周期、transition_tick=整数年偏移），
   因此每年恰好一次 `coordinator.run_step([year_start, year_end], step_index=year_index+1)`。
   Scheduler 不得改变此序列（RNG substream 以 blessed_start_tick 为键、step_index 进事件身份）。
2. **catch_up 是唯一权威推进原语**：幂等（同区间 COMMITTED run → skip）、fenced、含 run 生命周期。
   Scheduler 的"执行"就是按冻结序列调用 catch_up；绝不绕过。
3. **batch 边界只能在年边界**（否则会改变 RNG/事件身份 → 破坏确定性等价）。
   因此 budget 以 blessed tick 表达，实际批次 = 整年数量；`catch_up_max_ticks_per_cycle` 语义：
   每 cycle 至多推进 floor(budget/1e6) 年（≥1 年原子粒度）。文档化于配置。
4. **现实时间→tick 转换归属 catch_up**；Scheduler 的"规划"= 用冻结
   `time_engine` 原语做**只读预演**（Integrator/rate_at/segment_interval）得到
   due_ticks 与批次边界；执行后断言 durable tick 推进量 == 规划值，不一致 → FAILED
   （fail-closed，禁止猜测世界真值）。
5. **Pause 不发明时间规律**：PAUSED = Scheduler 不提交新 tick；现实时间照常形成
   backlog（由冻结 M1 语义决定）。resume 后正常 catch-up。
6. **operational 状态不写世界 DB**：Scheduler 状态/暂停位/checkpoint 写入
   plugin_data/runtime_state/ 下 JSON 文件（atomic tmp+replace，与 authoritative_db.json
   同风格）。不新增 alembic migration（保持正式库 45 表与 EXPECTED_SCHEMA_HEAD 不变；
   checkpoint != authoritative world state，§16）。
7. **Operational 计时用 monotonic**；real-time anchor（catch_up 的 now_real_us）由
   注入的 provider 提供（生产=epoch µs 墙钟经既有 time_service；测试=确定性注入）。
8. **正式世界 DORMANT 路径零租约**：NOT_ACTIVATED → 不 acquire WriterLease、不调用
   catch_up、不读时间积分、零 mutation（Activation Gate 在一切 authoritative mutation 之前）。

## 3. 目标架构

```
RuntimePlugin (main.py, 只读 API 不变)
 └─ RuntimeHost (plugin_shell/runtime_host.py)
     ├─ 现状：boot/status/diagnostics/backup（复用）
     └─ 新增：attach_scheduler(config) / detach_scheduler() + asyncio 循环任务
         └─ services/scheduler/RuntimeScheduler（核心，astrbot-free）
             ├─ SchedulerState（STARTING/DORMANT/STANDBY/RUNNING/PAUSED/
             │                 CATCHING_UP/RECOVERING/STOPPING/STOPPED/FAILED）
             ├─ ActivationGate（读 world_runtime 判定；未激活→DORMANT）
             ├─ CatchUpPlanner（冻结 time_engine 只读预演 → due/batch/boundary）
             ├─ YearStepAdapter（复刻 m3a_runner 年步序列：
             │     next_tribulation_boundary 拆分 + catch_up + coordinator.run_step）
             ├─ WriterCoordinator（WriterLease 持有/续约/释放/接管响应）
             ├─ RecoveryCoordinator（crash/ACK/commit-ambiguity → 读 durable truth，
             │     fail-closed）
             ├─ SchedulerCheckpoint（runtime_state JSON；非世界真值）
             └─ SchedulerObservability（get_scheduler_status()；DORMANT 时 tick=NULL）
```

禁止事项（M4）：改 services/simulation/**、services/time_engine、catch_up、
fencing、writer_lock、history 的任何语义；动 World Seed；激活正式世界；引入 LLM/网络；
修改 private companion。

## 4. 后续阶段映射（M4.1–M4.8）

- M4.1 core+lifecycle：state machine、start/stop（幂等）、run_cycle 骨架、observability 雏形。
- M4.2 activation gate：DORMANT 判定 + 正式状态安全回归测试（零 mutation/零租约）。
- M4.3 catch-up：CatchUpPlanner（冻结原语预演）+ YearStepAdapter + budget；
  chunk equivalence（1000=500+500=250×4=100×10=10×100=7×…=1×1000，年粒度）。
- M4.4 pause/resume：runtime_state JSON 持久化 + restart-while-paused。
- M4.5 writer/fencing：复用 WriterLease；takeover/stale 拒绝测试（≥4）。
- M4.6 recovery：crash 注入点（scheduler-specific ≥15 项，累计 M3c 77 → ≥100）、
  ACK-lost（≥5，含 scheduler checkpoint）、commit-ambiguity fail-closed。
- M4.7 observability：status snapshot 全字段（§18）。
- M4.8 acceptance：M0-M3 全量回归 + scheduler 套件 + 5000y endurance + 基线/世界/seed 检查。
