# DSH_M2_PREFLIGHT_HARDENING_PATCH_FINAL_REPORT

> 执行方：DSH。阶段：M2_PREFLIGHT_HARDENING_PATCH（仅修复/澄清 Preflight
> 基础契约）。禁止进入 Population Engine 实现；M2a 不批准。
> 基线：M2_PREFLIGHT_READY（c8954da），148/148。

## 1. Event UID before/after
- **before**：`sha256(world|simver|interval|engine|seq)[:12]`（48-bit，且不含
  event_type）—— 碰撞抵抗不足，不可作长期正式事件 ID。
- **after**：`EVENT_UID_SCHEMA_VERSION=1`；
  `sha256("v1|world_id|simulation_version|interval_start|interval_end|
  engine_id|event_type|stable_local_sequence")` 的 hex 前 **32 字符（128-bit）**。
  禁止 UUID4 / wall clock / DB autoincrement / 随机值。

## 2. Event UID schema
- 实现：`services/simulation/event_stream.py::deterministic_event_uid`
  （coordinator 与 M1 catch_up 的 TIME_ADVANCE 事件共用）。
- 语义身份包含 event_type：同引擎同 seq 不同事件类型 → 不同 identity（HP3）。
- 重试幂等双防线不变：M1 区间 skip + 确定性 uid 唯一约束。
- TIME_ADVANCE 基础设施事件同样确定性 uid（engine_id="TIME", seq=0）——
  事件流哈希因此可覆盖全事件流。

## 3. Event Stream Hash contract（EVENT_STREAM_HASH_SCHEMA_VERSION=1）
- 增量链：`h_0 = H("event-stream-v1|world_id|simulation_version")`；
  `h_i = H(schema|world|simver|h_{i-1}|step_i 的 domain events（发射顺序）)`。
- 每事件 canonical 字段：event_uid/blessed_tick/event_type/source/cause/
  effect/severity/scope（无 wall-clock/行 id）；Diagnostic Log 永不进入。
- 存储：M2 世界 checkpoint `meta.event_stream_hash`（+ prev_event_stream_hash）；
  StepReport 同步携带。

## 4. world_state_hash vs event_stream_hash semantics
- world_state_hash（v2）= 权威状态摘要（状态等价判定；不含事件/历史）。
- event_stream_hash = 截至某 run 的机器级 Domain Event Stream 确定内容+顺序证明。
- 分离不变量（HP4/HP6 实测）：最终 State 相同而事件序列不同 →
  state hash 相同、event hash 必不同；相同 replay → 两哈希都相同（HP5）。

## 5. 120 runs / 240 checkpoints 根因
每个 committed simulation step 恰好产生 2 个 checkpoint：
1 个 M1 **TIME_COMMITTED**（kind="CATCHUP"，时间引擎层：现实游标/进位的最低
限度恢复）+ 1 个 M2 **WORLD_COMMITTED**（kind="M2_PREFLIGHT"，世界语义层：
world_state_hash v2 + event_stream_hash + 引擎版本）。120 steps × 2 = 240 为
契约内预期，**非重复写入**。

## 6. Final checkpoint semantics
- checkpoint_kind 冻结：`TIME_COMMITTED`（M1 层）/ `WORLD_COMMITTED`（M2 层，
  meta.checkpoint_kind + phase="COMMITTED"）。
- 两 checkpoint 均有必要：时间层保证时钟快速恢复，世界层保证模拟语义恢复。

## 7. Recovery authoritative checkpoint rule
恢复一律取 `complete=True` 且 `checkpoint_kind=WORLD_COMMITTED` 的最新 M2
checkpoint（`latest_authoritative_world_checkpoint`，按 kind 过滤，CATCHUP 行
不参与世界语义恢复）。HP7：N=5 steps → 严格 5+5；HP8：权威行 = 3,000,000 tick
的 WORLD_COMMITTED（6 行 complete 中只取 3 行世界层）。

## 8. Deprecated time-model annotations
- `XIAOGUANG_CROW_KB/runtime_design/04_time_engine.md`：文件头
  DEPRECATED_RUNTIME_TIME_MODEL 横幅 + §1 逐条行内标注（年.月刻度 / =365 /
  time_ratio 唯一权威 / 旧换算函数名）。
- `05_offline_catchup.md`：文件头横幅 + §1.3 与 §2「一个现实日离线 ≈ 365
  福地年」行内标注。
- 仓库登记：`runtime_design/DEPRECATED_RUNTIME_TIME_MODEL.md`（现行权威模型 +
  标注位置 + 扫描结论；其余文档的「365」均为展示条数等非时间模型用途）。
- 未修改 World Bible / Canon；未改写任何原文档正文（只加标注）。

## 9. Regression results
**159/159 PASS**（148 原套件全保留 + 11 新增 HP：HP1 ≥128-bit、HP2 确定性、
HP3 event_type 参与身份、HP4 双哈希分离、HP5 同 replay 双哈希同、HP6 事件序列
不同 → event hash 不同、HP7 checkpoint 计数契约、HP8 权威恢复规则、HP9 废弃
标注在位、HP10 生产代码零旧公式、+增量链单元测试）。
正式库守护（PF20 会话级 checksum）运行中实测。

## 10. Formal DB audit
sha256 不变（7a2223266fd136cf…）；NOT_ACTIVATED；seed=NULL；tick=NULL；
cursor=NULL；16 张业务/基建表全 0；TIME_ADVANCE=0；M2 checkpoint=0。
**FORMAL_AUDIT=PASS**（World Seed 包零消费）。

## 11. Git commit
- `<HARDENING>` DSH M2 preflight hardening: 128-bit event uid, event stream
  hash, checkpoint kinds, deprecated time-model annotations, HP1-10 tests
  （叠于 c8954da / 83e0097 / …；tag m1.1-live-verified 保留）。
- KB 侧：04/05 标注 + M2_PREFLIGHT_ENGINE_CONTRACT.md 同步副本（KB 非 git，
  已随本报告登记）。

## 12. Workspace clean
`git status` = clean（world.db*、backups/*.db 由 .gitignore 排除）。

---

```
M2_PREFLIGHT_HARDENED
```

（完成后 STOP：不进入 M2a、不实现 Population Engine、不进入 M3、不激活
World Seed。等待主人下一条明确批准。）
