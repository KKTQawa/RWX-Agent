# RWX 工具（管理员/技术参考）

> 本文件面向评测组织者、管理员和工具维护者，**不是对局 Agent 的阅读材料**。对局 Agent 的入口是评测方 prompt、[START.md](../START.md) 和 [tools/README.md](../tools/README.md)；不要从 Agent 文档链到本文件。

Agent 入口：[tools/README.md](../tools/README.md) · 对局规则：[START.md](../START.md) · 命令手册：[help_zh.md](../help_zh.md) / [help.md](../help.md) · 服务器：[other/SERVER.md](../other/SERVER.md)

本目录的工具全部从本机回环地址连接 RWX 的 CLI / 事件 Socket；不涉及游戏服务器的 `5123` 端口。

## 0. 评测 / 并行：目录与端口约定

微操多 Agent 的专用启动、交接和材料收敛流程见
[server/PARALLEL_MICRO_EVALUATION.md](../server/PARALLEL_MICRO_EVALUATION.md)；本节的 `start-evaluation-run.ps1` 是完整对局启动器，不能替代微操启动器。

### 0.1 硬规则

- 评测默认由评测方启动游戏；Agent **不要运行 `gradlew`**，不要启动第二个游戏。
- 只用评测方给的 `<run>\rwx.cmd`；不要直接调用 `rwx-cli.py`，不要读共享端口文件。
- 只读写 `<run>`；不要写仓库里的 `agent-operation/tmp/`、`agent-tmp/`、`replays/`，也不要读别的 run。
- 不要按进程名查找/结束 java 进程；其他实例属于别的评测。
- 评测对局禁止截图。

### 0.2 默认共享路径 vs 每 run 路径

默认共享路径仅供评测方在本机单实例调试时使用。评测对局（即使只有一个 Agent）一律使用每 run 路径，不能让 Agent 回落到共享目录。

| 内容 | 默认（单实例） | 并行（每 run） |
|---|---|---|
| CLI 端口 | `X:\game\RWX\agent-operation\tmp\port` | `<run>\port` |
| 事件端口 | `X:\game\RWX\agent-operation\tmp\events-port` | `<run>\events-port` |
| 事件日志 | `X:\game\RWX\agent-operation\tmp\game-events-*.jsonl` | `<run>\events-*.jsonl` |
| 回放 | `X:\game\RWX\replays\` | `<run>\replays\` |
| 引擎证据 | `X:\game\RWX\evaluate\output\events-live\` | `<run>\events-live\` |
| 命令日志 | `X:\game\RWX\evaluate\output\commands-*.txt` | `<run>\commands\` |
| 日志 | `X:\game\RWX\logs\` | `<run>\logs\` |
| Agent 临时文件 | `X:\game\RWX\agent-tmp\` | `<run>\tmp\` |

`<run>` 建议放在仓库外，例如 `X:\game\RWX-multiagent\<id>`；它是该局唯一可自由读写的目录。

### 0.3 评测方的启动器必须做的事

每局一个 `<run>`，至少准备：

优先使用 [`../server/start-evaluation-run.ps1`](../server/start-evaluation-run.ps1)；它会拒绝复用已有 run、建立隔离目录、生成 `rwx.cmd` 并等待探活成功。下面的步骤仅用于维护/排错时核对启动器行为。

1. 新建空的、仓库外的 `<run>`；如需自定义地图，建 `<run>\mods` junction 指向 `X:\game\RWX\mods`。
2. 以 `<run>` 为工作目录启动，并显式指定端口、证据、命令日志、日志目录。先构建一次运行时目录：

```powershell
.\gradlew.bat :desktop:headlessDist
```

```powershell
# 工作目录必须是 <run>：回放写入 <run>\replays\
java -Xms256m -Xmx1536m -Dfile.encoding=UTF-8 `
  -Dorg.lwjgl.opengl.contextAPI=native -Dorg.lwjgl.system.stackSize=512 `
  --enable-native-access=ALL-UNNAMED --sun-misc-unsafe-memory-access=allow `
  -Dlaunch.dir=<run> `
  -Drwx.log.dir=<run>\logs `
  -Drwx.evaluate.dir=<run>\events-live `
  -Drwx.cli.recordingDir=<run>\commands `
  -Drwx.cli.terminal=false `
  -Drwx.assetsDir=X:\game\RWX\assets `
  -cp "X:\game\RWX\desktop\build\headless\lib\*" `
  io.github.rwx.DesktopMain --evaluate=2 --cli-port-file=<run>\port
```

关键点：

- 工作目录必须是 `<run>`：回放路径是 cwd 相对的 `replays/`。
- `--cli-port-file` 必须每局不同，否则客户端会连到同一个 primary。
- `-Drwx.evaluate.dir` / `-Drwx.cli.recordingDir` 必须显式给，否则会回落到仓库共享目录。
- 名字叫 `headlessDist`，但里面是完整 desktop jar；要 GUI 就不要加 `--headless` 和 `-Djava.awt.headless=true`。

3. 写 `<run>\rwx.cmd`：

```bat
@echo off
python "X:\game\RWX\agent-operation\tools\rwx-cli.py" --port-file "%~dp0port" --timeout 60 %*
```

5. 等 `<run>\port` 出现并 `rwx-ping` 返回 `pong`，再通知 Agent 开始。

事件接收器也要把端口和输出指到 `<run>`：

```powershell
python X:\game\RWX\agent-operation\tools\rwx-game-events-to-jsonl.py `
  --port-file "<run>\events-port" `
  --observe-output "<run>\events-observe.jsonl" `
  --combat-output "<run>\events-combat.jsonl"
```

## 1. 工具清单

| 工具 | 环境 | 用途 |
|---|---|---|
| `rwx-cli.py` | Python 3.9+，跨平台 | 单次、批量、交互、持久标准流客户端；推荐入口 |
| `rwx-cli.sh` | Bash + Python 3 | Python 客户端的 Bash 包装 |
| `rwx-cli.ps1` / `rwx-cli-lib.ps1` | Windows PowerShell 5.1+ / 7 | .NET 客户端；支持默认/环境变量端口文件、进程/日志发现 |
| `rwx-game-events-to-jsonl.py` | Python 3 | 订阅实时事件 Socket，按类型写 JSONL |
| `benchmark-rwx-cli.py` | Python 3 | 串行往返基准（只查询） |
| `test_rwx_cli.py` | Python 3 | CLI 协议回归测试 |
| `test_game_events_to_jsonl.py` | Python 3 | 事件接收器回归测试 |
| `verify-managed-room.py` | Python 3 | 托管房间验证（服务器侧） |
| `experimental_scripts/*.js` | 原宿主接口 | 算法参考，不是当前 CLI 可直接运行的插件 |
| `legacy/` | — | 历史工具，当前评测不使用、不维护 |

## 2. Python 客户端

### 2.1 调用方式

```powershell
python X:\game\RWX\agent-operation\tools\rwx-cli.py rwx-ping
python X:\game\RWX\agent-operation\tools\rwx-cli.py --port-file X:\game\RWX-multiagent\r1\port rwx-game-state --summary
python X:\game\RWX\agent-operation\tools\rwx-cli.py --stdio
python X:\game\RWX\agent-operation\tools\rwx-cli.py --batch-file commands.txt
python X:\game\RWX\agent-operation\tools\rwx-cli.py --interactive
python X:\game\RWX\agent-operation\tools\rwx-cli.py --list
```

- **选项必须放在命令名前**（`argparse` 的 `REMAINDER`；放后面会被当成命令参数）。
- 默认超时 60 秒；长单机操作可 `--timeout 120`。
- `--stdio`：启动时向 stderr 打印 `ready`，stdin 每行一条命令，stdout 每条一个 JSON：`{"error": bool, "reply": "..."}`。
- `--batch-file`：UTF-8，每行一条命令，支持引号，忽略空行和 `#` 注释。
- `--interactive`：人工逐条输入；`exit` / `quit` / `:q` 退出。

### 2.2 端口选择

优先级：

1. `--port` / `--port-file`
2. 环境变量 `RWX_CLI_PORT_FILE`
3. 仓库默认 `agent-operation/tmp/port`
4. 默认文件旁的 `port.instances/*.port`

候选必须通过 `rwx-ping`。显式端口文件失效时直接报错，**不会**自动切换其他实例；默认文件存在多个有效实例时也会报错，要求显式选择。

### 2.3 退出码

| 退出码 | 含义 |
|---|---|
| `0` | 成功 |
| `2` | 发现、连接或参数失败 |
| `3` | PowerShell 客户端连接失败 |
| `4` | RWX 返回 `error:` |

回执成功只表示“请求被接受”，不代表游戏效果已经应用。超时/断线后先查询状态，不要盲目重发可能已经执行的命令。

## 3. PowerShell / Bash 客户端

```powershell
.\agent-operation\tools\rwx-cli.ps1 -List
$env:RWX_CLI_PORT_FILE = 'X:\game\RWX-multiagent\r1\port'
.\agent-operation\tools\rwx-cli.ps1 rwx-game-state --summary
.\agent-operation\tools\rwx-cli.ps1 -Batch 'rwx-game-brief','rwx-game-unit-list --owner self --full'
.\agent-operation\tools\rwx-cli.ps1 -BatchFile .\commands.txt
.\agent-operation\tools\rwx-cli.ps1 -Interactive
```

- `-Port`：直接指定端口；并行时从 `<run>\port` 读出数字后用它，或先设置 `RWX_CLI_PORT_FILE`。
- `-Id` / `-ProcessName` / `-Log`：Windows 上的进程/日志发现；并行时不要用，容易选错实例。
- 这个脚本没有 `-PortFile` 参数；要用端口文件就设置 `RWX_CLI_PORT_FILE`。
- `-Batch` / `-BatchFile` / `-Interactive`：复用一条连接。

Bash：

```bash
bash agent-operation/tools_developer/rwx-cli.sh rwx-game-state --summary
bash agent-operation/tools_developer/rwx-cli.sh send 'rwx-game-step --seconds 30' 120
```

## 4. 连接协议

- 单次请求：UTF-8 `命令名<TAB>参数列表<LF>`；每个参数先 UTF-8，再 Base64，以英文逗号连接。无参数也发 `rwx-ping\t\n`。写完后半关闭写端，读到 EOF。
- 持久连接：先发 `!!framed\n`，读取 `0x1E ready 0x1E`；之后每次请求读一个 `0x1E<回复>0x1E` 帧。回复内的 RS 会被替换成空格；空回复是两个连续 RS。
- 服务端每条连接内顺序执行；不同客户端可同时连接。引擎只有 8 个工作线程，空闲持久连接也占用线程。
- 不要假定一次 `recv` 就有完整帧；处理 TCP 分片、EOF、超时和 UTF-8 解码错误。

## 5. 事件 JSONL

CLI 启动后还会开一个独立的本地事件 Socket：

| 项目 | 内容 |
|---|---|
| 监听 | `127.0.0.1` |
| 就绪日志 | `RWX_EVENTS_READY` |
| 默认端口文件 | `agent-operation/tmp/events-port` |
| 默认观察日志 | `agent-operation/tmp/game-events-observe.jsonl` |
| 默认交战日志 | `agent-operation/tmp/game-events-combat.jsonl` |
| 每文件上限 | 最新 500 条 |

并行时：

```powershell
python X:\game\RWX\agent-operation\tools\rwx-game-events-to-jsonl.py `
  --port-file "<run>\events-port" `
  --observe-output "<run>\events-observe.jsonl" `
  --combat-output "<run>\events-combat.jsonl"
```

参数：

| 参数 | 作用 |
|---|---|
| `--port-file` / `--port` | 指定事件 Socket |
| `--observe-output` | `new` / `info` 日志 |
| `--combat-output` | `damaged` / `destroyed` / `losses` 日志 |
| `--info` | 增加信息事件 |
| `--allies` | 切换友军击杀/损失 |

- 接收器只把 `kind=update` 写盘；`hello`、`event`、`remove`、`cursor`、`gap`、`overflow`、`parse_error` 只输出到 stderr。
- 断线自动重连；每个订阅者独立游标，最多 16 个订阅。
- 游戏端缓存最多 180 游戏秒 / 1000 条；超出后历史无法恢复。

## 6. 测试与基准

```powershell
python X:\game\RWX\agent-operation\tools\benchmark-rwx-cli.py --port-file <port> --count 30
python -m unittest discover -s X:\game\RWX\agent-operation\tools -p test_rwx_cli.py -v
python -m unittest discover -s X:\game\RWX\agent-operation\tools -p test_game_events_to_jsonl.py -v
```

基准只做查询，不改变游戏状态；结果受机器负载和游戏状态影响，不是性能保证。

## 7. 服务器托管验证

`verify-managed-room.py` 用于托管房间/代理房主流程的服务器侧验证：

```powershell
python X:\game\RWX\agent-operation\tools\verify-managed-room.py --host-wsl Ubuntu-22.04 --rounds 2
```

详细用法见脚本头部注释；服务器部署见 [other/SERVER.md](../other/SERVER.md)。


## 9. 历史工具

`legacy/` 只保留不再维护的历史工具；当前评测不使用。不要在新的评测流程里引用。

## 10. 故障排查

| 现象 | 处理 |
|---|---|
| `No live RWX CLI` | 游戏没启动、端口文件失效，或你在并行环境里没用自己的 `<run>\port` |
| `Multiple RWX instances` | 显式 `--port-file`；不要依赖默认文件 |
| `error: too many concurrent CLI clients (limit 8)` | 减少空闲持久连接 |
| 回执 `error:` | 按原因改参数，不要原样重发 |
| 断线/超时 | 先重连并查状态，再决定是否重发 |
| WSL 连不上 Windows 回环 | 在 WSL 内跑 Linux RWX，或通过 `powershell.exe` 调 Windows 客户端并转换路径 |
