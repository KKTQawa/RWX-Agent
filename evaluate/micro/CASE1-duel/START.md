# CASE1-duel 参与说明
## 目标
操控己方机枪机甲，在本局结束前消灭全部敌方猛犸坦克。`win` 才算完成任务；`loss`、`draw`、`timeout` 和 `error` 均不算胜利。

机枪机甲承受伤害越少、存活率越高、用时越少，得分越高

## 已知单位属性

`rwx-micro-1-units --json` 会返回实时 HP、护盾、位置、武器冷却/预热，以及 `canHit` / `threatenedBy`；不返回单位的静态射程、伤害或移速。本局固定属性如下（距离为世界单位）：

| 阵营 | 单位 | HP / 护盾 | 射程与移动 | 攻击要点 |
|---|---|---|---|---|
| 我方 | 机枪机甲 | 600 / 800；护盾持续回复 | 射程 210；移速 0.6；可越过悬崖 | 对地，单发 55；弹药会追踪目标。 |
| 敌方 | 猛犸坦克 | 2600 / 无护盾 | 射程 190；移速 0.6；仅陆地通行 | 对地，单发 130；即时命中。 |

不需要据此手算装填、预热或护盾结算；以每次查询中的实际 HP、护盾、`canHit`、`threatenedBy` 和武器状态为准。

## 开始本局

正式受管评测由评测方提前启动 lobby，并提供单局 prompt 与 `<run>\rwx.cmd`。lobby 未加载场景、不记录 Replay、不消耗微操预算；严格按 prompt 操作：

1. 只用 `<run>\rwx.cmd` 发送命令，不启动游戏、不运行 `gradlew`，也不读取端口、日志、录像或其他 run。
2. 先用 `rwx-micro-lobby-status` 确认 `phase=lobby`，然后只发一次 `rwx-micro-lobby-enter` 进入预设场景。
3. 等待 `rwx-micro-1-state` 返回 `phase=briefing` 后，再观察单位和地图；准备好后用 `rwx-micro-1-begin` 开始。
4. realtime 赛道开始后连续进行；pause 赛道每次判断完成后用 `rwx-micro-1-next` 推进一回合。以 `state` 返回的赛道与阶段为准。
5. 本局只可调用 prompt 和命令手册列出的命令。不要暂停、调速、截图、重开、手动录制或退出游戏。
6. `state` 显示 `phase=ended` 或连接关闭时，本局已结束；不要重新开始或试图修复环境。

完整命令、参数与回执含义见 [commands.md](X:\game\RWX\evaluate\micro\CASE1-duel\commands.md)。不确定时先查询 `rwx-micro-1-help` 或 `rwx-micro-1-state`，不要猜测参数。

## 使用 `rwx.cmd`

`rwx.cmd` 不仅能单条发送命令；它是本局已绑定端口的 CLI 前缀。Agent 优先建立一次持久连接，整局复用：

```powershell
& "<run>\rwx.cmd" --stdio
```

等待 stderr 输出 `ready` 后，向 stdin 每次写入**一条** `rwx-micro-1-*` 命令并 flush；stdout 每条回复对应一行 JSON（先检查 `error`，再读取 `reply`）。必须读完本条回复、完成判断后再发下一条，不能并发复用同一连接。

已确定且不依赖中途观察的短序列可以写到 `<run>\tmp\commands.txt`，再批处理：

```powershell
& "<run>\rwx.cmd" --batch-file "<run>\tmp\commands.txt"
```

文件每行一条命令；空行和 `#` 注释会忽略。批处理不会根据前一条回复改变后续命令：pause 赛道只适合提交本回合已决定的操作后推进一次，realtime 赛道只适合很短的连续操作。不要预先批量推进多个回合，也不要以单条启动器反复替代持久连接。

### 回执、失败与恢复

- `--stdio` 的每行 stdout 是外层 JSON。`error=true` 表示游戏命令被拒绝；`error=false` 也仍要查看 `reply` 是否以 `partial:` 开头。`partial` 表示只有部分选择或子命令生效，不能当作完整成功。
- 若持久连接意外关闭，不要直接重发上一条会改变状态的命令。可以重新启动一次 `--stdio`，先用 `rwx-micro-1-state` 和单位查询确认现状，再决定下一步；无法连接或状态异常则报告评测方。
- 不必使用 `--interactive`、`--line` 或 `--session`：它们分别面向人工终端、单次带引号的调用和多消费者情报游标，均不改善本局的自动评测操作。不要启动事件订阅工具或读取事件端口。

## 参与边界

- 发生连接失败、非 briefing 状态或其他异常时，报告现象即可；不要重启、改端口或连接其他实例。
