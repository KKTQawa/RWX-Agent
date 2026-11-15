# 进行 RWX 游戏

本机默认按多 Agent 并行运行；即使只有你这一局，也必须遵守 `<run>` 目录隔离。评测方已经启动游戏，你只负责本局对局，不要启动、重启或另开游戏。

仓库根目录是 `X:\game\RWX`。你可以在其他工作目录执行命令，但相对路径要换成绝对路径。评测方给你的运行目录 `<run>` 可能不在仓库内，例如 `X:\game\RWX-multiagent\<id>`。

## 0. 命令与文档

- `rwx-help`：完整手册；`rwx-help 5.5` 看指定章节；`rwx-help --list 2` 列出标题。
- CLI 支持底层命令和部分自动化/智能微操（`automation` 类指令），可减少重复管理。
- 中文命令手册：[help_zh.md](help_zh.md)；英文：[help.md](help.md)。
- 工具与评测常用命令：[tools/README.md](tools/README.md)。
- 战术：[strategy/strategy.md](strategy/strategy.md)、[strategy/strategy_human.md](strategy/strategy_human.md)。

## 1. 连接

评测方会给你运行目录 `<run>` 和 `<run>\rwx.cmd`；所有游戏命令都用它：

```powershell
& "<run>\rwx.cmd" rwx-ping
& "<run>\rwx.cmd" rwx-skirmish
& "<run>\rwx.cmd" rwx-battleroom-show --settings
```

- `<run>\rwx.cmd` 已经绑定本局端口：只把 `python rwx-cli.py` 的可执行前缀替换成它，后面的 CLI 参数和游戏命令原样保留（例如 `& "<run>\rwx.cmd" --stdio`）；不要直接调用 `rwx-cli.py`，不要读 `agent-operation/tmp/port` 或 `events-port`。
- 你自己创建的脚本、批处理文件和笔记只放 `<run>\tmp\`；不要写仓库的 `agent-tmp/`、`replays/` 或别的 run。
- 不要按进程名查找/结束 java 进程；其他实例属于别的评测。
- 如果评测方只给了端口文件、没有 `rwx.cmd`，先向评测方确认；不要自己改用默认端口。
- 命令回执只表示请求被接受，不代表动作完成；重要操作后先查询状态。

## 2. 规则

- 胜利条件：摧毁敌方队伍(所有)指令中心(大多数情况一个阵营只有一个指令中心，但是一个队伍可能有多个阵营，例如2 3阵营都属于B队伍)；我方队伍的所有指令中心被摧毁则立即判负。指令中心全灭 = 对局结束，之后命令与操作不计入评分。
- 评测目标：取胜的同时，延迟要低。例如我方军队长时间被偷袭而没有反应，就是延迟高的表现。胜利的基础上，延迟越高，得分越低。
- 你可以使用规则允许的**所有方式**来获取战局信息、取得胜利；及时花费资金、关注战报。
- 正式对局：**禁止改源码、暂停、调速、step、restart**；全程 1x 实时。
- 对局中禁止截图；用 `rwx-game-state`、单位列表、地图查询获取信息。
- 可以投降提前结束：`rwx-game-surrender`、`rwx-exit`；不要硬杀进程。
- 录像必须从 tick 0 开始：用 `rwx-battleroom-start --record`。开局后执行 `rwx-game-replay-status`，确认 `recording: true`；结束时再查一次，然后 `rwx-exit` 收尾。
- Agent 已无法操作时，不要从菜单退出或杀进程（回放会缺 `end` 块）；优先报告评测方，由其用 `rwx-game-abort` 收尾。只有评测方明确要求时才自己执行 `rwx-game-abort` 后 `rwx-exit`。

## 3. 目录与临时文件

本机默认并行运行，共享目录会被其他实例同时写，**不要用**。所有本局文件只放在 `<run>`：

| 内容 | 路径 |
|---|---|
| 启动器入口 | `<run>\rwx.cmd`（只调用，不编辑） |
| CLI / 事件端口 | `<run>\port` / `<run>\events-port`（运行时管理，不读写） |
| 回放、命令与证据 | `<run>\replays\`、`<run>\commands\`、`<run>\events-live\`（游戏写入，不改动） |
| 你的临时脚本 / 日志 | `<run>\tmp\`（唯一自由读写位置） |

不要读写：

- 仓库下的 `agent-operation/tmp/`、`agent-tmp/`、`replays/`、`evaluate/output/`；
- 其他 `<run>` 目录。

`<run>` 下的回放、命令与证据由游戏自动生成；它们不需要你读取才能参赛。需要确认录制时，使用 `rwx-game-replay-status`，不要检查或修改文件。

其余目录由评测方管理，不要动。

## 4. 提示

- 优先用 `--stdio` 持久连接，减少每条命令的启动开销。
- 断线/超时先 `rwx-ping` 并查状态，不要直接重发操作命令。
- 需要子智能体时，不要让它另开游戏实例。
