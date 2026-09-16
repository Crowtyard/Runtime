# M6C.1C — FINAL NUMERIC CANON PACKET 报告

```
M6C1C_FINAL_NUMERIC_CANON_PACKET

STAGE                        = M6C.1C FINAL NUMERIC CANON DECISION PACKET
STATUS                       = AWAITING_OWNER_FINAL_NUMERIC_CANON_SELECTION

NUMERIC_OD_P1   = [P-A / P-B / P-C + capacity NULL/1.25/1.5/2]
NUMERIC_OD_RE1  = [RE-A lean / RE-B balanced / RE-C reserve-heavy + 7-node minimal topology]
NUMERIC_OD_E1   = [E-A 98% / E-B 95% / E-C 90% equilibrium; ppp = 1; sensitivity solved]
NUMERIC_OD_S1   = [S-A / S-B / S-C percentage-scaled thresholds]
NUMERIC_OD_T1   = [T-A mild / T-B moderate / T-C severe intensity + risk envelopes]

OWNER_NUMERIC_DECISION_COUNT = 5（<= 5）
ALL_REQUIRED_FIELDS_COVERED  = TRUE
UNTRACKED_BLOCKING_FIELDS    = 0

RA_COHORT_001   = CANDIDATE_RESULT：v1.1（补末位开区间尾部项 1/q）+ 出生率对引擎步序数值求解；
                  三候选第 1 年净增长 −26…−58（≤0.5%），100 年漂移 ≤0.6%
RA_MORTALITY_001= CANDIDATE_RESULT：等价于"每 bucket 恒死亡概率"（三候选 1/60、1/100、1/300）；
                  年龄带压缩形式仍可保留，但本阶段证明恒值即可得到驻定解，故 M6C.1B 的年龄带压缩为可选
RA_STRUCT_001   = APPROVED（本阶段未改其语义；OD-5 的区数用它派生）

FORMAL_DB_AUTHORITY        = PASS
FORMAL_WORLD_RUNTIME_ROWS  = 0
FORMAL_WORLD_STATUS        = NOT_ACTIVATED
FORMAL_WORLD_SEED_CONSUMED = FALSE
SNAPSHOT_V1                = NOT_APPROVED
MATERIALIZER_ALLOWED       = FALSE
NEXT_ACTION                = AWAIT_OWNER_FINAL_NUMERIC_CANON_SELECTION
```

## 1. 交付物

| 文件 | 作用 |
| --- | --- |
| `docs/world_creation/M6C1C_FINAL_NUMERIC_CANON_PACKET.md` | owner 阅读版：5 个数值决策 + 后果表 |
| `docs/world_creation/M6C1C_NUMERIC_PACKET_DATA.json` | 机读：全部实际字段值、包络、拓扑、轨迹 |
| `scripts/m6c1c_sweep.py` | 扫描/推算脚本（frozen 方程逐步复算；无 DB、无 Seed、无 RNG） |
| `tests/test_m6c1c_numeric_packet.py` | 14 项守卫（结构、范围内、无测试档、轨迹存在、无爆炸/灭绝、无 DB 能力） |

## 2. 本阶段三个真实发现（均已修正并写入 packet）

1. **RA-COHORT-001 v1.0 漏掉末位开区间 bucket 的尾部累积**（`(1-q)^(N-1)/q`）→ 提出 **v1.1**；
   不修则初始分布高估壮年、低估老年，驻定出生率被算错。
2. **解析式出生率会导致 +400%/年爆炸**：必须对**引擎步序**（年龄推进 → 死亡 → 出生，
   `population.py:284-339`）数值求解（bisection）；本包三候选均用数值解。
3. **任何有限 `population_capacity` 都是强人口刹车**：`factor = (capacity − pop)/capacity`
   用的是当前空位；实测 P-A 在 r = 1.25 时 300 年只剩 3,451 人（无容量法则为 10,272）
   → **建议 capacity = NULL**。

## 3. 五个数值决策（摘要；完整后果见 packet）

| OD | 决策形状 | 推荐 | 关键后果 |
| --- | --- | --- | --- |
| P1 | 寿命上限 / 死亡率 / 生育区间 / 驻定出生率（四族共享） | **P-A（60 年，N=61）** | 100 年 11,981；300 年 10,272；cohort 行数 2,928 |
| RE1 | 初始库存 = N 年需求；产能 = M × 年需求（+ 7 节点最小拓扑） | **RE-B（N=2, M=1.5）** | 无短缺；100 年库存 133,500；节点 7（少一个即该资源永久零产出） |
| E1 | ppp = 1，反解 sensitivity 命中质量目标 | **E-B（95%）** | 100 年质量 953,075（95.3%）；`carrying_capacity` 仅登记（无引擎消费） |
| S1 | 阈值 = 聚落人口百分比 | **S-B** | MAIN 10 人/户、200 户、机构门槛 120；SAT 2 人/户、250 户、门槛 30 |
| T1 | 每 tier intensity + 六项风险比例 | **T-B** | 10 年 7 人 / 50 年 96 人 / 100 年 450 人；周期与首个前兆不变 |

## 4. 覆盖与不变量

```
M6C.1B OD-2 → P1 ；OD-3/OD-4 → RE1 ；OD-5 → E1 ；OD-6 → S1 ；OD-7 → T1
OD-8 = APPROVED（沿用） ；OD-9 = 已吸收（habitat_quality=FULL_QUALITY + RE1/E1 + 引擎 server default）
OD-1 = 已由 owner 批准（A：Hairy Men/Rockmen/Mermen/Mushroommen；Human=0）
→ UNTRACKED_BLOCKING_FIELDS = 0
```

## 5. 测试

```
pytest tests/test_m6c1c_numeric_packet.py              → 14 passed
pytest tests/test_m6c1b_owner_decision_packet.py       → 15 passed
pytest tests/test_m6c1b_authoritative_db_guard.py      → 19 passed
pytest tests/test_m6c1_snapshot_candidate.py           → 26 passed
（合计 74；未修改 simulation production semantics → 未跑 canonical full regression）
```

## 6. 限制（必须随候选一起读）

```
PROJECTION_EVIDENCE_CLASS = ANALYTIC_REIMPLEMENTATION_OF_FROZEN_STEP_EQUATIONS
ENGINE_RUN_VERIFICATION   = DEFERRED_TO_NEXT_STAGE
```

轨迹来自逐步复算（逐条引用源码行），**不是** coordinator + 真实 DB 的运行结果；
所选候选在进入 SNAPSHOT_V1 前必须用真实引擎（临时库 + synthetic bootstrap）复算一次，
并核对 4 / 100 / 300 年的实际人口、库存、质量与灾劫包络。所有候选标记
`NOT_CANON_UNTIL_OWNER_APPROVAL`。

## 7. 未做

```
未实现 materializer      未激活世界      未消费 Seed      未写正式库      未部署 live
未读取 stale legacy DB 作为 world truth（正式库一律经 authoritative resolver）
未从 TEST_PROFILES / 测试夹具 / 演示常量抄任何数值
```

```
STOP。不得实现 materializer。不得激活世界。等待主人对 P1/RE1/E1/S1/T1 的数值裁决。
```
