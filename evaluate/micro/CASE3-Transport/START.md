# CASE3-Transport 参与说明

## 目标
在基地岛生产本局目标的陆军，用运输单位送到左上角目标岛，使各类型的送达数量首次全部达标。`success` 才算完成任务；`timeout` 和 `error` 均不算胜利,这个任务没有敌人，因此最坏只会超时，不会失败

用时越少得分越高。

## 开始本局

正式受管评测由评测方提前启动 lobby，并提供单局 prompt 与 `<run>\rwx.cmd`。lobby 未加载场景、不记录 Replay、不消耗微操预算；严格按 prompt 操作：

1. 只用 `<run>\rwx.cmd` 发送命令，不启动游戏、不运行 `gradlew`，也不读取端口、日志、录像或其他 run。
2. 先用 `rwx-micro-lobby-status` 确认 `phase=lobby`，然后只发一次 `rwx-micro-lobby-enter` 进入预设场景。
3. 本 CASE 没有 `begin`：入场载入完成后场景立即以 1× 连续运行。用 `rwx-micro-3-state --json` 确认 `phase=running`，再用 `rwx-micro-3-goal --json` 读取本局目标。
4. 只使用 CASE3 已授权的 `rwx-micro-3-*` 与命令手册列出的只读观察命令。观察和操作期间时间继续推进；不要在生产、装载、航行或卸载尚未确认时假定已完成。
5. 本局只可调用 prompt 和命令手册列出的命令。不要暂停、调速、截图、重开、手动录制或退出游戏。
6. `state` 显示 `phase=ended` 或连接关闭时，本局已结束；不要重新开始或试图修复环境。

完整命令、参数与回执含义见 [command.md](X:\game\RWX\evaluate\micro\CASE3-Transport\command.md)。不确定时先查询 `rwx-micro-3-help` 或 `rwx-micro-3-state`，不要猜测参数。

## 使用 `rwx.cmd`

`rwx.cmd` 不仅能单条发送命令；它是本局已绑定端口的 CLI 前缀。Agent 优先建立一次持久连接，整局复用：

```powershell
& "<run>\rwx.cmd" --stdio
```

等待 stderr 输出 `ready` 后，向 stdin 每次写入**一条** `rwx-micro-3-*` 或本 CASE 授权的观察命令并 flush；stdout 每条回复对应一行 JSON（先检查 `error`，再读取 `reply`）。必须读完本条回复、完成判断后再发下一条，不能并发复用同一连接。

已确定且不依赖中途观察的短序列可以写到 `<run>\tmp\commands.txt`，再批处理：

```powershell
& "<run>\rwx.cmd" --batch-file "<run>\tmp\commands.txt"
```

文件每行一条命令；空行和 `#` 注释会忽略。批处理不会根据前一条回复改变后续命令，也不保证各条观察来自同一 tick；不要用它跳过需要重新判断的生产或运输阶段。

### 回执、失败与恢复

- `--stdio` 的每行 stdout 是外层 JSON。`error=true` 表示游戏命令被拒绝；`error=false` 也仍要查看 `reply` 是否以 `partial:` 开头。`partial` 表示只有部分子命令生效，不能当作完整成功。
- `ok: submitted requestId=N` 只表示请求已受理：生产、装载、移动、抵达和卸载都以之后的状态观察为准。
- 若持久连接意外关闭，不要直接重发上一条会改变状态的命令。可以重新启动一次 `--stdio`，先用 `rwx-micro-3-state`、`rwx-micro-3-goal` 和 `rwx-micro-3-fleet` 确认现状，再决定下一步；无法连接或状态异常则报告评测方。
- 不必使用 `--interactive`、`--line` 或 `--session`：它们分别面向人工终端、单次带引号的调用和多消费者情报游标，均不改善本局的自动评测操作。不要启动事件订阅工具或读取事件端口。

## 参与边界

- 发生连接失败、非 running 状态或其他异常时，报告现象即可；不要重启、改端口或连接其他实例。
