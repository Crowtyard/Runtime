# DSH_M1_1_ASTRBOT_PLUGIN_SHELL_MIGRATION_FINAL_REPORT

> 执行方：DSH。任务：M1.1_ASTRBOT_PLUGIN_SHELL_MIGRATION（架构迁移/打包/集成壳，非 M2）。
> 原则：WRAP / MIGRATE，不 REWRITE；正式世界保持 NOT_ACTIVATED。

## 1. Golden Baseline
- 迁移前重跑原 M1 套件：**103/103 PASS**；冻结 git tag **`m1-golden-baseline`**（@ f6cc39f）。
- 已知基线提交：127523f / a135942 / 0e49a94 / 717fd76 / 6d586a7 / f6cc39f（全部保留）。

## 2. 原 Runtime 路径
`D:\MY SELF\IKUN\小光\XiaoguangBlessedLandRuntime\`（M1 验收工程，DB 为 world.db）。

## 3. 新插件路径（部署形态）
`<AstrBot>/data/plugins/astrbot_plugin_blessed_land_runtime/`（本仓库根即插件包；
与 `astrbot_plugin_private_companion` 平级，物理独立）。

## 4. Plugin Directory Structure
```
(插件根)
├── metadata.yaml / main.py / __init__.py / _conf_schema.json / requirements.txt
├── README.md / ARCHITECTURE.md / alembic.ini / pyproject.toml
├── plugin_shell/{paths.py, runtime_host.py}          ← 外壳/宿主（域核心无 astrbot 依赖）
├── domain/ services/ database/(9 migrations) config/  ← M1 核心原样保留
├── scripts/{init_db.py, backup_now.py, migrate_db_to_plugin_data.py}
├── pages/blessed-land/{index.html, app.js, style.css}
└── tests/（103 M1 回归 + PL1-22 插件壳 + stub_astrbot harness）
```
说明：核心目录保持 M1 顶层结构（避免无谓 import 重构）；壳/核心边界由测试强制
（domain/services/database/config 零 astrbot import；main.py 是唯一 AstrBot 感知模块），
结构偏差已记录于 ARCHITECTURE.md。

## 5. metadata.yaml
name=astrbot_plugin_blessed_land_runtime；display_name=小光福地 Runtime；
desc=为小光福地提供长期世界时间、状态、历史与离线演化基础设施；author=DSH；
version=0.1.1；astrbot_version=">=4.22.0"；pages=[{name: blessed-land}]。
**不伪造 repo URL**（无 repo 字段）。

## 6. Plugin Lifecycle（main.py）
- `class BlessedLandRuntimePlugin(Star)`；`__init__(context, config)`；
  `initialize()`：解析 plugin_data → 建目录 → 定位权威 DB → alembic head →
  完整性/不变量审计 → 初始化引擎 → 注册只读 API；**不推进世界/不自动 catch-up/
  不激活 seed**。
- `terminate()`：释放引擎/连接；零世界推进、零历史。
- 热重载：A terminate → B load 同一 DB；无重复迁移/重复播种/状态改变（PL8-10 实测）。

## 7. Runtime Core 迁移方式
WRAP/MIGRATE：domain/services/database/config 与 9 个 migration 原样保留；
唯一核心改动 = init_db 的 migrate/seed 逻辑抽出为 `services/db_lifecycle.py`
（语义不变，供 scripts 与 runtime_host 复用）——**核心逻辑修改清单仅此一项**。

## 8. Persistent Data Path
`<AstrBot data>/plugin_data/astrbot_plugin_blessed_land_runtime/`
{blessed_land.sqlite, backups/, exports/, runtime_state/authoritative_db.json, logs/}。
解析：官方 `get_astrbot_plugin_data_path()`（等价回退 `data/plugin_data`）；
禁止硬编码绝对路径（PL6/PL7 实测）。

## 9. Authoritative DB Migration（scripts/migrate_db_to_plugin_data.py）
实测执行：源库审计（integrity=ok、head=e6c0f4a1b3d9、NOT_ACTIVATED 空世界、
checksum 7a222326…）→ pre-migration 备份 → 复制 staging → 目标校验（integrity/head/
checksum/世界审计）→ 原子 os.replace 提升 → 写 authoritative_db.json →
旧 DB 保留 rollback copy（`world.db.rollback_pre_plugin_migration`，绝不自动删除）。
新权威 DB：`D:\MY SELF\AstrBot\data\plugin_data\astrbot_plugin_blessed_land_runtime\blessed_land.sqlite`。
防双权威：runtime 只按 marker 打开唯一 DB；旧库已移出仓库根并命名 rollback。

## 10. DB Integrity（真实 plugin_data 端到端实测）
integrity=ok；head=e6c0f4a1b3d9；不可变触发器在位；boot/status/diagnostics 前后
世界快照**逐字节一致（unchanged=True）**。

## 11. Alembic History
9 个 migration 原样保留；不 squash、不 reset、未新增无谓 migration（schema 无变更）。

## 12. Hot Reload
PL8/PL9/PL10 实测：两轮 load→terminate 与重启等价后 world_runtime=1 行、
time_ratio_history=1 行、alembic_version=1 行、integrity=ok、
current_blessed_tick/last_committed_real_us 仍 NULL、0 run、0 事件。

## 13. Runtime Update Isolation
PL12 实测：插件代码目录整体删除→DB 完好；重装新版代码→再次 boot 世界状态不变。

## 14. Private Companion Update Isolation
PL11 实测：创建/整体删除/重装 fake companion 均不影响 Runtime 状态；
源码静态扫描确认零 `private_companion` 引用（无 import/路径耦合）。

## 15. Plugin Page
metadata `pages:` + `pages/blessed-land/{index.html, app.js, style.css}`；
JS 使用官方桥 `window.AstrBotPluginPage`（兼容 parent 桥与 debug_http），
`bridge.apiGet("/status"|"/diagnostics")`；只读基础设施控制台（Runtime/时间/Writer/
Database/World/Diagnostics 六卡片）；页面文案明确"后台术语不会成为小光角色认知"。
无独立 FastAPI/Flask/固定端口/UI patch。

## 16. Web API（只读）
`context.register_web_api` 仅注册 3 个 GET：/status、/diagnostics、/runtime-info；
响应包络 `{"success": true, "data": {...}}`；status 含 plugin_status/runtime_version/
world_status/seed_present/current_blessed_tick/natural_rate/db/writer/entity_counts
（PL5 实测）。**无 POST、无 activate/advance/seed/create/delete/reset 端点（PL16/17）。**

## 17. Plugin Config
`_conf_schema.json` 仅 4 项：runtime_enabled / diagnostic_log_level /
backup_retention / page_refresh_interval。无 activation switch / 速率编辑器 /
tick 编辑器 / seed 编辑器 / 强制 catch-up / 删库 / 重置 / 人口编辑（PL2 断言）。

## 18. AstrBot Public API Usage（审计结论）
全部经公开插件 API：`astrbot.api.star.Star/Context`、`Context.register_web_api`、
`astrbot.api.AstrBotConfig/logger`、官方路径助手 `astrbot.core.utils.astrbot_path.
get_astrbot_plugin_data_path()`（与官方数据目录同源；含等价回退与测试覆盖）。
**未调用 astrbot.dashboard 私有实现**；main.py/plugin_shell 之外的层零 astrbot 依赖
（测试强制）。API 形状以本机 AstrBot 安装（D:\MY SELF\AstrBot，>=4.22 系）pyc 内省
+ Private Companion 6.2.3 实际插件用法双源校准。

## 19. Private Companion Interface Research（只读，未修改任何文件）
- 审计对象：本机可得最新版 `astrbot_plugin_private_companion` 备份 6.2.2/6.0.0 源码。
- `_external_schedule_material_context(...)` 与「外部插件提供的今日实况」逻辑在
  6.2.2 备份中**不存在**（应存在于更新的线上版本，本机不可得 → 无法直接审计其签名）。
- 6.2.2 的跨插件数据模式：a) `context.get_registered_star(plugin_name)` 探测其他插件
  （半公开，仅取元数据）；b) 直接构造其他插件 plugin_data 文件路径读取私有数据
  （screen_companion 日记、livingmemory DB 等，underscore 私有耦合）；c) 无公开
  Plugin Registry / Context Provider 契约。
- **结论：NO_PUBLIC_CONTRACT**。Runtime 不得依赖 Private Companion 私有方法/私有数据；
  未来世界上下文注入走官方 hook（on_llm_request + extra_user_content_parts）与
  Runtime 自建公开 Query Layer（M2+，只读）。

## 20. Activation Time Trap Test
test_activation_time_trap：NOT_ACTIVATED 世界在 boot/reload/status/diagnostics
反复操作后 last_committed_real_us=NULL、current_blessed_tick=NULL、0 run、
0 TIME_ADVANCE；静态断言 runtime_host 不含 catch_up 调用。现实经过的时间不得
在未激活期间累积成未来福地历史；激活纪元属 M2 Activation Transaction。

## 21. M1 103-Test Regression
**103/103 PASS**（迁移后全套 125 tests 中的 M1 部分，语义未削弱）。

## 22. M1.1 New Test Matrix（22 项全 PASS）
PL1 插件可发现 ✅｜PL2 元数据/配置加载 ✅｜PL3 无 Private Companion 初始化 ✅｜
PL4 Page 被发现 ✅｜PL5 状态 API ✅｜PL6 DB 位于 plugin_data ✅｜PL7 源码目录无权威 DB ✅｜
PL8 重载保库 ✅｜PL9 重载不推进 ✅｜PL10 重启等价 ✅｜PL11 Companion 替换隔离 ✅｜
PL12 代码替换隔离 ✅｜PL13/14/15 Page/status/diagnostics 零写 ✅｜
PL16 无激活端点 ✅｜PL17 无手动推进端点 ✅｜PL18-22 正式世界审计（NOT_ACTIVATED/
seed NULL/tick NULL/业务全零/历史为零）✅｜另含：禁用配置不建库、备份落在 plugin_data、
核心层零 astrbot 依赖。**全套 125/125 PASS。**

## 23. Formal DB Audit（迁移后真实 plugin_data 库）
integrity=ok｜head=e6c0f4a1b3d9｜触发器在位｜世界审计全部通过（见 §10）。

## 24. World Seed Status
`WORLD_RUNTIME_STATUS = NOT_ACTIVATED`；`seed = NULL`；`current_blessed_tick = NULL`。

## 25. World History Status
`official_world_events = 0`；persons=0；population=0；settlements=0；
tribulations=0；timeline=0；simulation_run=0；simulation_checkpoints=0。
Official World History = **NOT_STARTED**。

## 26. AstrBot Core modifications
**无**（仅只读内省审计；未提交任何 patch）。

## 27. Private Companion modifications
**无**（仅只读调研 Desktop 备份源码）。

## 28. Known Risks
1. 真实 AstrBot 运行实例不在此机器：插件未在 live 实例实载（以官方 API 内省 +
   真实插件 6.2.3 用法双源校准 + stub 集成测试覆盖）；上线首载需观察 initialize 日志。
2. `_external_schedule_material_context` 属更新版本未审计项（本机不可得）；
   结论 NO_PUBLIC_CONTRACT 以 6.2.2 可审计代码为准。
3. `register_web_api` 的精确挂载前缀以 companion 实测惯例
   `/<plugin_name>/page<route>` 对齐（WebUI 桥自动处理）；debug 模式已提供直连回退。
4. Plugin Page 由 WebUI 前端渲染（前端不在本机 checkout），页面资源按官方
   metadata `pages` 约定组织，上线需在 WebUI 验证渲染。
5. 旧 DB 的 rollback copy 保留于仓库根（world.db.rollback_pre_plugin_migration），
   已在 .gitignore 排除；若确需恢复，用迁移脚本反向复制并核对 checksum。

## 29. Git commits（迁移后）
```
9a485f8  DSH M1.1 AstrBot plugin shell migration: metadata/main/_conf_schema, …   ← M1.1 提交
f6cc39f  docs: finalize M1 report commit references        ← m1-golden-baseline
6d586a7  DSH M1 time engine & offline catch-up
717fd76  DSH M0 TIME_MODEL_UNIT_BLOCKER fix
0e49a94  docs: finalize QA report commit references
a135942  DSH M0 independent QA
127523f  M0 Foundation: prior-agent delivery baseline
```

## 30. Workspace clean status
`git status` = clean（world.db* 与 backups/*.db 由 .gitignore 排除）。

## 最终值
```
WORLD_RUNTIME_STATUS = NOT_ACTIVATED
seed                 = NULL
current_blessed_tick = NULL
official_world_events= 0
persons              = 0
population           = 0
settlements          = 0
tribulations         = 0
```

## 验收门禁
[PASS] M1 Golden Baseline preserved｜[PASS] 103 original tests｜[PASS] AstrBot plugin
load（stub 集成）｜[PASS] plugin_data persistence｜[PASS] Plugin Page｜[PASS] Web API｜
[PASS] Hot Reload｜[PASS] Runtime Update Isolation｜[PASS] Private Companion Update
Isolation｜[PASS] Formal DB migration｜[PASS] Formal DB integrity｜[PASS] NOT_ACTIVATED
preserved｜[PASS] seed=NULL｜[PASS] blessed_tick=NULL｜[PASS] no world history created｜
[PASS] no Private Companion code dependency｜[PASS] no AstrBot Core modification｜
[PASS] no M2 feature｜[PASS] workspace clean

---

```
M1_1_ASTRBOT_PLUGIN_SHELL_READY
```

（完成后立即停止。不进入 M2。）
