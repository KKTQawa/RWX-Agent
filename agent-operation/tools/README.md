# Agent 工具说明

本页只说明 `agent-operation/tools/` 中工具的用途、调用方式和工具自身的最小限制。

- 工具实现、测试和维护说明：不属于评测 Agent 文档，勿从本页继续查阅开发者目录。

## 1. 工具清单

| 工具 | 用途 | 输出 |
|---|---|---|
| `rwx-cli.py` | 通过 RWX CLI 发送命令；支持单次、批处理、交互和持久连接 | 文本或 JSONL |
| `rwx-game-events-to-jsonl.py` | 订阅实时事件 Socket，将事件分成观察和战斗两份滚动 JSONL | 两个 JSONL 文件；诊断写 stderr |

## 2. `rwx-cli.py`

### 2.1 单次命令

正式评测中使用评测方提供的 `<run>\rwx.cmd`。它只替换 `python rwx-cli.py` 这个可执行前缀并绑定当前对局端口；后面的 CLI 参数和游戏命令均原样保留，不能直接运行脚本。

```powershell
& "<run>\rwx.cmd" rwx-ping
& "<run>\rwx.cmd" rwx-game-state --summary
```

### 2.2 批处理和持久连接

```powershell
& "<run>\rwx.cmd" --batch-file "<run>\tmp\commands.txt"
& "<run>\rwx.cmd" --interactive
& "<run>\rwx.cmd" --stdio
```

- `--batch-file`：按文件顺序发送命令，每行一条；空行和以 `#` 开头的行会跳过。
- `--interactive`：从标准输入逐行读取命令并逐行输出回复。
- `--stdio`：从标准输入逐行读取命令，并为每条回复输出一个 JSON 对象；适合由其他程序持续驱动。
- `--line "<命令>"`：将一整行作为一次命令发送。

### 2.3 情报游标

```powershell
& "<run>\rwx.cmd" --session agent-a --stdio
& "<run>\rwx.cmd" --session agent-a rwx-game-state --summary
```

`--session` 为调用方绑定独立的自动情报游标。值必须是 1–64 个 `A-Z`、`a-z`、数字、`-`、`_`、`.` 或 `:`；同一调用方在单次、批处理、交互和 `--stdio` 模式中应保持同一个值。只有多个消费者共用一局时才需要分别指定。

## 3. `rwx-game-events-to-jsonl.py`

该工具只订阅实时事件，不发送游戏命令。它把有效的事件更新写入两份滚动文件：

- `game-events-observe.jsonl`：`new`、`info`。
- `game-events-combat.jsonl`：`damaged`、`destroyed`、`losses`。

基本用法：

```powershell
python rwx-game-events-to-jsonl.py --port-file "<run>\events-port" --observe-output "<run>\tmp\game-events-observe.jsonl" --combat-output "<run>\tmp\game-events-combat.jsonl"
```

选项：

- `--port <port>`：直接指定事件端口；会覆盖 `--port-file`。
- `--port-file <path>`：指定事件端口文件。
- `--observe-output <path>` / `--combat-output <path>`：指定两份 JSONL 输出路径。
- `--info`：订阅 `info` 事件；默认只订阅 `new`、`damaged`、`destroyed`、`losses`。
- `--allies`：额外接收友军的击杀和损失事件。
- `--retry-seconds <seconds>`：断线后的重试间隔。

程序会在连接断开后重连，并依据输出文件中的会话和序号继续接收。`gap`、`overflow`、解析错误等诊断只写入 stderr；出现缺口时应使用 CLI 的 `rwx-game-events` 补查，不能把 JSONL 当作完整历史记录。

## 4. 共同约定

- 工具与 RWX CLI 使用 UTF-8。
- JSONL 模式是一行一个 JSON 对象；不要把 stderr 混入 stdout 或 JSONL 文件。
- 工具只负责传输/订阅和文件输出，不解释游戏策略，也不替代 `rwx-help`。
- 正式对局中遵守 `<run>` 隔离：工具产生的批处理文件、日志和 JSONL 输出只放在 `<run>\tmp\`；端口、回放和证据由评测环境管理。
