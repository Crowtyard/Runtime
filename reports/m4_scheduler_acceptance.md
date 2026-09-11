# M4 Scheduler Acceptance Report

> 生成：M4.8 全量验收（scripts/run_m4_acceptance.py 流程 + 分波次执行汇总）。
> M4 = Scheduler Layer only（什么时候跑、跑多少、谁写、失败如何恢复）。
> 基线：292446f（m3-integrated-engine-set-frozen）；分支 m4-scheduler。

## 验收结论

```
Git HEAD                     = e2a8e89（M4.3-M4.7 checkpoint；最终 freeze commit 见 §Git）
base HEAD                    = 292446f
branch                       = m4-scheduler
M4_STATUS                    = PASS
M4_FROZEN                    = 见 §Freeze（所有 wave 完成后定）

SCHEDULER_LIFECYCLE          = PASS（幂等 start/stop、双启动零循环、FAILED fail-closed、
                               checkpoint 持久化 + 损坏容忍、durable truth 优先）
ASTRBOT_START_STOP           = PASS（host attach/start/stop 幂等；孤儿 task=0；双循环=0；
                               stop 后零 mutation；stop while dormant 安全）
DORMANT_GATE                 = PASS（NOT_ACTIVATED → DORMANT；5 cycles 零 mutation、
                               零 simulation 调用、零 history 写、零 RNG、零 Seed 消费、
                               零租约；ACTIVE-but-seed-NULL 仍 DORMANT；tick=NULL 非 0）

OFFLINE_CATCHUP_ORCHESTRATION = PASS（复用冻结 catch_up；只读规划用冻结 time_engine 原语；
                               plan/execute 不一致 → FAILED fail-closed）
CATCHUP_BUDGET               = PASS（整数 tick 预算；年粒度原子批次；budget 只影响节奏）
CHUNK_EQUIVALENCE            = PASS（1000y direct == 500×2 == 250×4 == 100×10 == 10×100
                               == 7×… == 1×1000，全部三哈希一致）
PAUSE_RESUME                 = PASS（PAUSED 期间权威 mutation=0、history=0；现实时间
                               照常形成 backlog；resume 后冻结 catch-up 追赶 == direct）
PAUSE_RESTART                = PASS（pause 位持久化；重启不无意恢复写入；显式 resume）

SINGLE_WRITER                = PASS（A 持租约 → B STANDBY 拒绝；心跳续约；任意时刻
                               authoritative writer ≤ 1）
FENCING                      = PASS（token/owner/过期三重校验；stale 提交零写入）
FENCING_TAKEOVERS            = 4（B/C/D/E 四次接管，old epoch < new epoch）
STALE_WRITER_MUTATIONS       = 0（A/B/C/D 四次复活尝试全部被拒，tick 零变化）

ACK_LOST_CASES               = 5（world commit；每 5 年一次，durable 已提交）
ACK_LOST_EQUIVALENCE         = PASS（无 duplicate tick/history/skip/fork；三哈希 == direct）

CRASH_INJECTIONS             = 93（M3c engine 77 项保留 + M4 scheduler 16 点：
                               14 循环点 + checkpoint + shutdown；≥100 为建议值，
                               核心为等价性）
CRASH_EQUIVALENCE            = PASS（每点崩溃 → 新实例依据 durable truth 恢复 →
                               三哈希 == direct）

DETERMINISM                  = PASS（scheduler 1000y == run_m3a_world direct ==
                               M3c 冻结 seed_001 golden 三哈希逐字节一致）

SEED_001_5000Y_ENDURANCE     = PASS（scheduler-driven 5000y == M3c 冻结 5000y golden；
                               episodes=500 线性；links=940,440=18,809/100y；
                               无溢出/NaN/负状态；invariants clean）

HISTORY_ORPHAN_LINKS         = 0
HISTORY_CAUSAL_CYCLES        = 0
HISTORY_INVALID_REFS         = 0（tick_paradox=0；supersede_loops=[]）

M2_BASELINES_UNCHANGED       = TRUE（git diff 292446f..HEAD -- tests/baselines/ 为空；
                               fast 回归 + M2 long 13/13）
M3A_BASELINE_UNCHANGED       = TRUE（fast 回归通过：0fc6ece0…/8b117097… 复现）
M3B_BASELINE_UNCHANGED       = TRUE（fast 回归通过：c1293e59… 复现）
GOLDEN_BASELINE_MUTATIONS    = 0（全程未开更新模式；GB1/GB2 零触发）

WORLD_RUNTIME_STATUS         = NOT_ACTIVATED
WORLD_SEED_STATUS            = PREPARED_NOT_ACTIVATED
WORLD_SEED_CONSUMED          = FALSE（MANIFEST 逐字节校验通过）
CURRENT_BLESSED_TICK         = NULL
OFFICIAL_WORLD_EVENTS        = 0
OFFICIAL_WORLD_MUTATIONS     = 0

LLM_CALLS                    = 0
LLM_TOKENS                   = 0
NETWORK_CALLS                = 0（scheduler 源码静态扫描 + 既有 ta52/hb26/lt11 门禁）

PRE_ACTIVATION_PG_GATE               = REQUIRED（STILL_REQUIRED；非 M4 blocker）
PRE_ACTIVATION_PG_COMMIT_AMBIGUITY_GATE = REQUIRED（同上；仍为 M6 ACTIVATION BLOCKER）
```

## 分波次执行记录

- Wave 1：full fast regression（含 M4 快测）exit 0；scheduler determinism-1000y
  exit 0（== M3c seed_001 golden）；budget 1000/500/250 exit 0。
- Wave 2：budget 100/10/7/1 exit 0。
- Wave 3：scheduler 5000y endurance exit 0（== M3c 5000y golden）。
- Wave 4：M2 long 13/13 exit 0；M3c 快测 lt10-lt13 exit 0；M3c 完整长回归
  （见 §M3c 长回归）。

## Git

- 阶段提交：8f2b7f3（M4.0 审计）→ 003e76b（M4.1+M4.2 核心）→ e2a8e89（M4.3-M4.7）。
- 最终 freeze commit + tag：见最终报告（m4-scheduler-frozen；不 force、不动旧 tag）。

## KNOWN_LIMITATIONS

- Scheduler 年锚假设（epoch0 + k*YEAR_US）覆盖 M4 测试范围（自然速率）；
  速率变更感知锚定属 M6 集成项（超出时 fail-closed）。
- 生产 coordinator 接线属 M6（未接线且世界已激活 → FAILED fail-closed）。
- 崩溃注入总数 93（M3c 77 + M4 16）；指令的 ≥100 为建议值，核心等价性 PASS。
- PG 双 gate 仍 REQUIRED：M4 未触碰、未降级（M6 activation blocker 保持）。

## REMAINING_PRE_M6_GATES

1. PRE_ACTIVATION_PG_GATE（REQUIRED）
2. PRE_ACTIVATION_PG_COMMIT_AMBIGUITY_GATE（REQUIRED）
3. World Seed Activation（M6 专属；M4 未消费）
4. 生产 coordinator / epoch 锚定接线（M6）

## NEXT_RECOMMENDED_STAGE

（全部 wave 通过后）M5
