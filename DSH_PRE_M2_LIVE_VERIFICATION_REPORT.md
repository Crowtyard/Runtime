# DSH_PRE_M2_LIVE_VERIFICATION_REPORT

> 执行方：DSH。对象：M1.1 插件壳在真实 AstrBot 环境的实载验收。
> 环境：本机 AstrBot Launcher 实例（**AstrBot v4.28.0-beta.1**，完整源码 +
> venv），以**隔离 ASTRBOT_ROOT** 运行（不触碰用户真实实例的 plugins/
> plugin_data/config；无平台适配器、无 LLM、无主动消息）。正式世界 = 权威库
> 的字节级拷贝（smoke 只读于副本）。
> 前置门禁：本阶段未修改 World Bible / Canon / 正式世界；未执行任何激活操作。

## 1. 验收序列与结果

| # | 步骤 | 结果 |
|---|---|---|
| 1 | 安装插件（复制到 data/plugins/astrbot_plugin_blessed_land_runtime） | ✅ |
| 2 | AstrBot 正常启动（v4.28.0-beta.1，WebUI :6185） | ✅ |
| 3 | 插件 initialize 成功（`Plugin astrbot_plugin_blessed_land_runtime (0.1.1) by DSH`，alembic 运行、无错误） | ✅ |
| 4 | plugin_data 路径正确（官方 `get_astrbot_plugin_data_path()` → data/plugin_data/<plugin>） | ✅ |
| 5 | authoritative DB 正确识别（blessed_land.sqlite；marker 由插件写入：path+checksum 7a222326…） | ✅ |
| 6 | Alembic head 正确（e6c0f4a1b3d9） | ✅ |
| 7 | GET /api/v1/plugins/extensions/<plugin>/status（HTTP 200：RUNNING/NOT_ACTIVATED/seed=false/tick=null/integrity=ok/全表 0） | ✅ |
| 8 | /diagnostics（m0=PASS m1=PASS time_engine=READY catchup=READY activation=LOCKED） | ✅ |
| 9 | /runtime-info（plugin/version/data_dir/db_path/authoritative_db/world_time_model） | ✅ |
| 10 | Plugin Page 真实加载：pages 发现（components[page: blessed-land]）→ entry config（content_path+asset_token）→ index.html 200（资源 URL 被官方重写）→ app.js 200 → style.css 200 → bridge-sdk.js 200 | ✅ |
| 11 | reload（POST /api/v1/plugins/reload → 200「重载成功」→ status 仍 RUNNING） | ✅ |
| 12 | AstrBot restart（kill → 重新启动 boot8 → status RUNNING/NOT_ACTIVATED/integrity=ok） | ✅ |
| 13 | disable / enable（PATCH /plugins/enabled → 停用成功（期间 API 不可用=预期）→ 启用成功 → status RUNNING） | ✅ |
| 14 | uninstall（DELETE /plugins/<id> → 200 卸载成功；插件目录删除） | ✅ |
| 15 | reinstall（复制回插件目录 + reload → RUNNING） | ✅ |
| 16 | 数据持久化：卸载后 plugin_data/blessed_land.sqlite 完好（184320 字节）；重装后世界状态不变 | ✅ |

## 2. LIVE_ACTIVATION_TRAP

全部 load/reload/restart/disable/enable/uninstall/reinstall/status/page 周期后：

```
smoke DB: runtime_status=NOT_ACTIVATED, seed=NULL, current_blessed_tick=NULL,
          last_committed_real_us=NULL, time_rate_remainder=0,
          全部业务表 0 行, TIME_ADVANCE=0
真实权威库（D:\MY SELF\AstrBot\data\plugin_data\...）: 同上
smoke 副本与权威库逐字节一致（sha256 相同）
```

**LIVE_ACTIVATION_TRAP = PASS** —— 任何插件 load/reload/restart 都不等于
"世界开始运行"；无 catch-up、无 TIME_ADVANCE、无 seed、无人物/人口/聚落/灾劫、
无自动激活。

## 3. 实载暴露并已修复的问题（修插件壳，不动世界数据）

1. **核心模块绝对导入在部署环境失败**（`No module named 'database'`）：
   AstrBot 以 `data.plugins.<插件名>.*` 导入，插件根不在 sys.path。
   → domain/services/database/config/plugin_shell 全部改为**插件包内相对导入**
   （零跨插件命名冲突；开发测试改用包限定导入）。125/125 PASS。
2. **官方 `Star.__init__(context, config)` 不保存 config 属性**（v4.28 实测）：
   → main.py 自行保存 `self.config`（AstrBotConfig dict-like）。
3. **v4.28 Web API 路由契约**：注册路由必须含插件名段（WebUI 调用
   `/api/v1/plugins/extensions/<plugin>/<route>`）；→ 注册
   `/<plugin>/status` 等 3 个路由；页面 debug 基址同步为
   `/api/v1/plugins/extensions/<plugin>`；PL16 测试同步。
4. 依赖安装：隔离环境无网络时 AstrBot 会尝试 pip 安装 requirements.txt
   （镜像 403）。正式部署联网即自动安装；离线部署需预置 alembic 到
   data/site-packages（已写入报告风险项）。

## 4. 结论

```
M1_1_LIVE_VERIFIED = TRUE
```

（AstrBot 真实实载 16 项全过 + LIVE_ACTIVATION_TRAP=PASS + 3 项实载修复已提交；
正式世界状态零变化；AstrBot Core / Private Companion / World Bible 零修改。）
