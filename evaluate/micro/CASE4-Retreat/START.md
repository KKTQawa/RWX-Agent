# CASE4-Retreat 参与说明

## 目标
摧毁左上角公开目标区域内的全部敌人，及时利用右下角维修湾恢复部队。`success` 才算完成任务；`defeat`、`timeout` 和 `error` 均不算胜利。

操作越灵活、部队存活率越高、用时越短得分越高

## 已知单位属性

`unit-list` / `unit-show` 可查询当前实体的类型、位置、HP、护盾和命令，但不返回移速、武器射程或伤害；以下是本 Case 固定的、对微操有用的属性。数值均为世界单位，HP 与射程不随 type 改变。

| 阵营 | 单位 | 关键属性 |
|---|---|---|
| 我方 | 虫王（`bugMeleeT31`） | 6000 HP、无护盾；只能攻击地面，近战射程 15，移速 1.4，可越过悬崖。 |
| 敌方 | 炮塔 | 均为固定地面防御、只能攻击地面。当前可见时可用 `unit-list` / `unit-show` 查其 HP 与位置。 |

敌方炮塔的类型组合、数量与坐标随任务 type 变化，仍只以当前可见信息为准；各类型的固定属性如下：

| 炮塔类型 | HP | 射程 | 微操含义 |
|---|---:|---:|---|
| T2 加农 | 1100 | 185 | 中近程直射。 |
| T3 加农 | 3900 | 320 | 长程直射，且会自修。 |
| 喷火 | 1600 | 155 | 短程范围伤害。 |
| T1 / T2 炮兵 | 1000 / 1800 | 350 / 460 | 最远程的范围伤害；优先留意。 |
| T1 / T2 闪电 | 1500 / 2700 | 210 / 250 | 即时命中，分别为较低/较高单发威胁。 |


## 开始本局

正式受管评测由评测方提前启动 lobby，并提供单局 prompt 与 `<run>\rwx.cmd`。lobby 未加载场景、不记录 Replay、不消耗微操预算；严格按 prompt 操作：

1. 只用 `<run>\rwx.cmd` 发送命令，不启动游戏、不运行 `gradlew`，也不读取端口、日志、录像或其他 run。
2. 先用 `rwx-micro-lobby-status` 确认 `phase=lobby`，然后只发一次 `rwx-micro-lobby-enter` 进入预设场景。
3. 等待 `rwx-micro-4-state --json` 返回 `phase=briefing` 后，再观察地图、己方单位与当前可见敌情；准备好后用 `rwx-micro-4-begin` 开始。
4. 本 CASE 只有 realtime 赛道：开局后 1× 连续运行，观察、思考和传输期间游戏继续推进。没有 `next`、暂停或调速。
5. 本局只可调用 prompt 和命令手册列出的观察与战斗命令。不要暂停、调速、截图、重开、手动录制或退出游戏。
6. `state` 显示 `phase=ended` 或连接自动关闭时，本局已结束；不要重新开始或试图修复环境。本局任务单位全部损失会立即判负并正常退出，随后 `port` 消失或连接关闭是收尾，不是环境故障。

完整命令、参数与回执含义见 [command.md](X:\game\RWX\evaluate\micro\CASE4-Retreat\command.md)。不确定时先查询 `rwx-micro-4-help` 或 `rwx-micro-4-state`，不要猜测参数。

## 使用 `rwx.cmd`

`rwx.cmd` 不仅能单条发送命令；它是本局已绑定端口的 CLI 前缀。Agent 优先建立一次持久连接，整局复用：

```powershell
& "<run>\rwx.cmd" --stdio
```

等待 stderr 输出 `ready` 后，向 stdin 每次写入**一条**命令并 flush；stdout 每条回复对应一行 JSON（先检查 `error`，再读取 `reply`）。必须读完本条回复、完成判断后再发下一条，不能并发复用同一连接。

已确定且不依赖中途观察的短序列可以写到 `<run>\tmp\commands.txt`，再批处理：

```powershell
& "<run>\rwx.cmd" --batch-file "<run>\tmp\commands.txt"
```

文件每行一条命令；空行和 `#` 注释会忽略。批处理不会根据前一条回复改变后续命令，也不保证各条观察来自同一 tick；不要用它跳过需要重新判断的交战或撤退阶段。

### 回执、失败与恢复

- `--stdio` 的每行 stdout 是外层 JSON。`error=true` 表示游戏命令被拒绝；`error=false` 也仍要查看 `reply` 是否以 `partial:` 开头。`partial` 表示只有部分单位或子命令生效，不能当作完整成功。
- `ok: submitted` 只表示命令已受理：移动、抵达、开火、摧毁和维修都以之后的状态观察为准。本局任务是近战虫王，没有护盾（`shield`/`maxShield` 恒为 0），战损只看 HP 变化。
- 若持久连接意外关闭，不要直接重发上一条会改变状态的命令。可以重新启动一次 `--stdio`，先用 `rwx-micro-4-state` 和 `rwx-game-unit-list --owner self --full --json` 确认现状，再决定下一步,如果仍然无效，那么报告评测方，很可能是对局已经结束自动断开。
- 不必使用 `--interactive`、`--line` 或 `--session`：它们分别面向人工终端、单次带引号的调用和多消费者情报游标，均不改善本局的自动评测操作。不要启动事件订阅工具或读取事件端口。

## 参与边界

- 发生连接失败、非 briefing/running 状态或其他异常时，报告现象即可；不要重启、改端口或连接其他实例。
