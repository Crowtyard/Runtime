# DEPRECATED_RUNTIME_TIME_MODEL（废弃登记）

> 依据：M0 TIME_MODEL_UNIT_BLOCKER（ACCEPTED）与 M1 Rational Tick Model
> （ACCEPTED）。本登记只记录 runtime_design 中被标注为旧时间模型的位置；
> **未改写任何原文，未修改 World Bible / Canon**。

## 现行权威时间模型
- 1 tick = 1 µy（micro-blessed-year，整数 canonical tick；年/月/日仅为投影/display）
- 1 real day = 1,000,000 blessed ticks
- 自然态有理速率 = 1,000,000 blessed ticks / 86,400,000,000 real µs
  （Bible WS-0201 原文口径「现实约 1 天 ≈ 福地约 1 年」）
- 速率历史：time_ratio_history（rate_numerator / rate_denominator，整数，
  effective-dated）；禁止用当前速率倒推历史。
- 旧「=365」「福地年.月」「world_runtime.time_ratio 唯一权威」模型
  **不得再作为实现依据**。

## 已标注位置（XIAOGUANG_CROW_KB/runtime_design/）
1. `04_time_engine.md`：文件头 DEPRECATED 横幅 + §1 逐条行内标注
   （年.月刻度 / =365 / time_ratio 唯一权威 / blessed_from_real 等旧换算函数名）。
2. `05_offline_catchup.md`：文件头 DEPRECATED 横幅 + §1 第 3 步与 §2
   「一个现实日离线 ≈ 365 福地年」行内标注。

## 扫描结论（2026-09-07）
- 其余 runtime_design 文档中出现的「365」均为非时间模型用途
  （06 号「不展示 365 条日报」= 展示条数），不构成计算真值残留。
- Runtime 生产代码（domain/services/database/config/plugin_shell）零
  「365.0 倍率」「ratio_value」「blessed_elapsed」「福地年.月」真值使用
  （HP10 静态测试强制）。
