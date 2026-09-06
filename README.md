# 小光福地 Runtime（astrbot_plugin_blessed_land_runtime）

独立 AstrBot 插件。为小光福地提供长期世界时间、状态、历史与离线演化基础设施。

职责边界：

- **Blessed Time**：整数 canonical tick（1 tick = 1 µy）；有量纲有理速率
  （自然态 1,000,000 ticks / 86,400,000,000 real µs，即现实约 1 天 ≈ 福地约 1 年）。
- **Offline Catch-up**：按 time_ratio_history 真实时间边界分段积分（整数、无 float）。
- **Single Writer + Fencing**：commit 前 fencing token 重验；崩溃/接管安全。
- **World State / Event History / Checkpoint**：不可变事件历史（DB 触发器）、
  持久化 checkpoint、备份/恢复。
- Population / Society / Ecology / Tribulation 模拟属未来里程碑（当前未激活）。

**Private Companion**（`astrbot_plugin_private_companion`）负责小光角色陪伴。
二者是 **Sibling Plugins**，不是 Parent / Child Plugins；本插件不依赖、不访问它。

## 世界数据存储

世界数据库位于 AstrBot 插件数据目录（**不在插件源码目录**）：

```
data/plugin_data/astrbot_plugin_blessed_land_runtime/
├── blessed_land.sqlite
├── backups/
├── exports/
└── runtime_state/authoritative_db.json
```

更新/替换插件代码不会覆盖世界存档；删除 Private Companion 也不影响本插件。

## 当前世界状态

```
WORLD_RUNTIME_STATUS = NOT_ACTIVATED
seed = NULL
current_blessed_tick = NULL
正式业务世界表 = EMPTY（persons/population/settlements/resources/tribulations/events 全 0）
Official World History = NOT_STARTED
```

本插件只提供只读管理控制台（Plugin Page `blessed-land`）与只读 Web API
（GET /status /diagnostics /runtime-info）。**不提供任何激活/推进/生成端点。**

## 开发

```bash
python -m pytest tests/            # 125 tests（M1 103 项回归 + M1.1 插件壳 PL1-22）
python scripts/init_db.py          # 开发环境初始化（正式权威 DB 已迁至 plugin_data）
python scripts/migrate_db_to_plugin_data.py --help   # 正式 DB 安全迁移工具
```

- 依赖：SQLAlchemy>=2.0、alembic>=1.13（requirements.txt）。
- 迁移历史：Alembic 9 个 migration，不 squash 不 reset。
- Golden Baseline：git tag `m1-golden-baseline`。
- 架构边界与 LLM 禁写原则：见 `ARCHITECTURE.md`。
