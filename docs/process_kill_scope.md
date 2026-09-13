# 进程终止作用域规则（M5.1 误杀事故后新增）

事故：2026-09-12 22:30，诊断脚本以「杀掉所有 python 进程」作为收尾清理，
把主人当时**正在运行的 live AstrBot 实例**一并终止。

## 规则

1. **禁止按进程名批量终止**（任何测试 / 诊断 / 脚本）：
   * `Stop-Process -Name python`、`Get-Process python | Stop-Process`
   * `taskkill /IM python.exe`、`pkill python`、`killall python`
   * 任何形式的「遍历所有 python 进程再逐个 kill」
2. **只允许操作**：显式 PID **+** 已核实的父子进程树 **+** 已知的测试实例。
3. **启动任何测试实例之前**先做外来实例检测；一旦发现非测试的 AstrBot 进程
   （主人的 live 实例），必须 `ABORT TEST`，**绝不允许清理它**。
4. 清理只能终止本脚本自己拉起的那棵树；对本脚本之外的进程一律不碰。

## 实现与回归

* 唯一实现：`scripts/process_scope.py`
  * `assert_no_foreign_python(allowed=[...])` → 检测到外来 python 进程即抛
    `ForeignProcessError`（ABORT 语义）；
  * `process_tree(root_pid)` / `kill_tree(root_pid)` → 只处理指定 PID 的进程树
    （显式 PID、叶子优先），返回被终止的 PID；
  * `live_python_guard_exit()` → CLI 脚本用：外来实例存在时打印并 `sys.exit(9)`。
* 回归：`tests/test_process_kill_scope.py`
  * 静态：仓库内任何**代码行**出现进程终止命令，必须带显式 PID（`-Id` / `/PID`）
    且不得按名终止（注释与 docstring 中的反面示例不计）；
  * 行为：守卫必须 ABORT；`kill_tree` 只杀自己的树——同时存在“旁观者”进程时，
    旁观者必须存活（即 2026-09-12 事故形态的回归）。

## 与 AstrBot live 实例的关系

`BLR_*` / Runtime 的测试与诊断脚本**永不**以主人的 live 实例为目标：

* 需要独占环境时，先 `assert_no_foreign_python()`；有实例在跑就退出，等人为处理；
* 诊断实例一律使用独立端口（例如 6189），避免与 6185 上的实例争用；
* 数据目录隔离：诊断只用 `tmp_path` / 独立实例目录，绝不指向 `plugin_data` 之外。
