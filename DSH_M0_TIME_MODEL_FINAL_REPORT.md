# DSH_M0_TIME_MODEL_FINAL_REPORT

> 触发：TIME_MODEL_UNIT_BLOCKER（M0 QA 报告审查意见）。
> 执行方：DSH（Runtime 唯一实现与维护方）。日期：2026-09-06。
> 前置：World Seed 仍为 NOT_ACTIVATED；本修正全程未推进世界。

---

## 1. 时间单位定义（量纲明确）

- 世界时间坐标：整数 **canonical blessed tick**。**1 tick = 1 micro-blessed-year
  （µy，1e-6 福地年）**。年/月/日只是 projection / display。
- 现实时间增量：**整数微秒（µ_real，real µs）**。
- 禁止浮点累计世界时间；禁止 float 作为长期世界时间规则的真值。

## 2. 自然态 rate 定义（Bible WS-0201）

- Canon 原文（`02_time_and_temporality.md` WS-0201【LOCAL_CANON】）：
  **现实约 1 天 ≈ 福地约 1 年（约 365 倍）**；换算参考：现实 1 小时≈福地 15 天。
- Runtime 正式速率（有量纲有理速率，整数分子/分母）：

  ```
  NATURAL_TIME_RATE = 1,000,000 blessed ticks / 86,400,000,000 real µs
  ```

  即：现实 86,400,000,000 µs（= 1 现实天）→ 1,000,000 ticks（= 1 福地年）。
  **24 real hours → 1,000,000 blessed ticks 严格成立。**
- "约 365 倍"仅作为 Bible 原文的派生展示语（`blessed_years_per_real_day` 返回精确
  Fraction(1,1) 供 display/审计），不进入核心计算、不入库。
- **对 Canon 的修改：无。** 本修正恰恰是把前序对 WS-0201 的误读（把"约 365 倍"当成
  "现实 1 天 = 365 福地年"）纠正回 Canon 原文语义。

## 3. 转换公式（单位推导）

```
ticks = (µ_real × rate_numerator) // rate_denominator
```

- µ_real：real microseconds（现实微秒）
- rate_numerator：blessed ticks（分子，单位 tick）
- rate_denominator：real microseconds（分母，单位 µs）
- 结果：blessed ticks
- 量纲校验：(µs × ticks) / µs = ticks ✓
- 舍入政策：整数向下取整（**floor**）；**同一速率的连续分段共享余数进位**
  （有理精确累加：24×1h 与 1×24h 结果完全一致，无累计 drift）；**跨速率分段进位重置**
  （余数量纲随速率变化，不得跨速率传递）。
- 已移除 `float.as_integer_ratio()` 路径；速率真值从数据库起就是 INTEGER + INTEGER。

## 4. 数据库字段

`time_ratio_history`（migration e9f4b7c2d8a6）：

| 字段 | 类型 | 含义 |
|---|---|---|
| rate_numerator | BigInteger NOT NULL | 分子：blessed ticks |
| rate_denominator | BigInteger NOT NULL | 分母：real µs |
| real_effective_from | UtcDateTime | 现实生效时刻（effective-dated） |
| blessed_effective_from_tick | BigInteger NULL | 福地生效 tick；NULL=未开始计（未激活） |
| reason / source | String | 审计来源（自然态行=BIBLE_V1_WS-0201_NATURAL_RATIO） |

- 已删除模糊的 `ratio_value FLOAT`。
- 每次时间速率改变 = 新增一条 effective interval 行；Offline Catch-up 必须按区间
  分段积分，禁止拿当前速率倒推历史。

## 5. Migration

`e9f4b7c2d8a6_m0_rational_time_rate`（down_revision = b2d4e8f9a6c3）：
add rate_numerator/rate_denominator（nullable）→ 数据转换（仅自然态行
reason LIKE `BIBLE_V1_WS-0201_NATURAL%` 且 ratio_value=365.0 → 1,000,000 /
86,400,000,000）→ 存在其它无法审计转换的行则**迁移失败**（绝不静默错转）→
设 NOT NULL → drop ratio_value。正式库已 upgrade head，数据转换实测成功。

## 6. 测试结果（14 项时间模型测试，全套 65/65 PASS）

| 测试 | 结果 |
|---|---|
| 1 real day → 1,000,000 ticks | ✅ 严格相等 |
| 3 real days → 3,000,000 ticks | ✅ 严格相等 |
| 12 real hours → 500,000 ticks | ✅ 严格相等 |
| 1 real hour → 41,666 µy（精确值 41,666.666…，政策 floor） | ✅ 子年刻度正确 |
| 24×1h == 1×24h（同速率进位） | ✅ 完全相等，无累计 drift |
| 12h Rate A(自然) + 12h Rate B(半速) 分段 | ✅ 750,000；整段按 B 倒推 =500,000 ≠ 750,000 |
| 同速率进位精度（2×1h → 83,333 vs 逐段 floor 83,332） | ✅ 进位生效 |
| 跨速率进位重置 | ✅ 62,499（无跨速率余数泄漏） |
| 派生展示（自然态 = Fraction(1,1)） | ✅ 仅 display |
| 速率校验（0/负/float 分子拒绝） | ✅ |
| naive/aware 归一化、零/负区间、投影、溢出余量 | ✅ |

全套回归：**65 tests / 65 PASS**（此前 60 项全部保留通过）。

## 7. 正式 DB 是否仍为空世界

**是。** 迁移后实测：全部业务表 0 行；`runtime_status=NOT_ACTIVATED`；
`world_seed_version=NULL`；`current_blessed_tick=NULL`；time_ratio_history 仅 1 行
自然态速率（numerator=1,000,000 / denominator=86,400,000,000，
blessed_effective_from_tick=NULL）；事件不可变触发器在位；integrity_check=ok；
迁移前已做 pre-migration 备份（integrity=ok）。

## 8. Fencing（M1 硬性门禁，已记录）

- 已在 `README.md`「M1 硬性门禁」与 `POSTGRESQL_COMPATIBILITY_CONTRACT.md` §8 记录：
  **M1 所有世界 Mutation Transaction 提交前必须校验当前 fencing token**（载体 =
  `runtime_lock.lease_token`）；旧 Writer 在租约失效并被新 Writer 接管后，即使恢复
  执行也**不得提交任何世界状态**。本项在 M1 实现，**World Seed Activation 前必须 PASS**。
- M0 侧已完成的配套：租约即时提交、token fencing release、renew 同 token 校验、
  过期 CAS 接管（`services/writer_lock.py`）；`services/atomic_tick.py` docstring 标注
  M1 提交路径接入点。

## 9. 结论

```
M0_TIME_MODEL_READY
```

（时间单位、速率真值、分段积分、舍入政策均已按量纲修正并实测；正式库为空世界；
对 World Bible Canon 未做任何修改。完成后停止，不进入 M1。）
