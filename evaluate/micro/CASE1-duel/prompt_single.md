# CASE1-duel 受管微操评测

你将作为评测 Agent 参与一场 CASE1-duel 微操实验。本机可能同时有其他评测；你只属于下面这一局，不能影响、读取或推断其他实例。

## 路径与连接

- 运行目录：`{{RUN}}`（下称 `<run>`）: X:\game\RWX-multiagent\micro-case1-01。
- 本局已由评测方启动并停在 lobby，尚未载入场景或开始录制。不要运行 `gradlew`、不要另开游戏、不要自行选择 task/seed/track。
- 所有游戏命令只能通过 `& "{{RUN}}\rwx.cmd" <CLI 参数或命令>` 发出。它已绑定本局端口；不要直接调用 `rwx-cli.py`、读取端口文件或寻找其他实例。优先执行一次 `& "{{RUN}}\rwx.cmd" --stdio`，整局复用该连接：每次写入一条命令并读完对应 JSON 回复后再发下一条，不能并发复用。已确定的短序列可写入 `{{RUN}}\tmp\commands.txt` 后调用 `--batch-file`；不要批量跳过需要观察的回合。连接中断时先重连并查询状态，不能盲目重发会改变状态的命令
- Shell 兼容：若通过 WSL/bash 调用，文件路径用 `/mnt/x/...`，命令用 `cmd.exe /c "X:\...\rwx.cmd" <参数>`。不要假设后台 `--stdio` 子进程能跨工具调用存活；若每次调用会清理子进程，改用单次调用或一次 `--batch-file` 完成短序列。
- 可读资料仅为 [START.md](X:\game\RWX\evaluate\micro\CASE1-duel\START.md) 及其中链接的 CASE1 命令说明。
- 你创建的文件只能放在 `<run>\tmp\`。`rwx.cmd`、`port`、`events-port`、`replays\`、`commands\`、`events-live\`、`logs\`、`micro-output\` 和 `micro-run.json` 均属启动器/运行时所有，不得读写、删除、改名或据此寻找其他 run。
- 不要按进程名查找或结束进程；其他 Java 进程属于其他评测。

## 执行流程

1. 先读 `START.md`；本局实例已经就绪，但仍在 lobby。
2. 用 `rwx-micro-lobby-status` 确认 `phase=lobby`，然后发出一次 `rwx-micro-lobby-enter`。这是你进入本局的唯一入口；不要自行传 task、seed 或其他参数。
3. 等待场景载入完成后，用 `rwx-micro-1-state` 确认 `phase=briefing`，再拟定开局计划。
4. 用 `rwx-micro-1-begin` 开局，之后只使用 CASE1 已授权的 `rwx-micro-1-*` 命令。realtime 赛道连续进行；pause 赛道只在完成本回合判断后用 `rwx-micro-1-next` 推进。以 `state` 返回的实际赛道和 phase 为准（赛道已经由评测方启动时选择）。
5. 不暂停、不调速、不 step、不 restart、不截图，也不进行长时间 sleep。录像与结果由微操运行时自动保存；不得使用完整对局命令、手动录制或 `rwx-exit`。
6. 结束后等待 `state` 显示 `phase=ended` 或连接自然关闭；不要重新开局、不要手动退出进程。

## 异常

若 wrapper 无法连接、lobby/briefing 状态不符，或游戏无响应，只报告现象即可。不要尝试修复运行目录、改端口、重启游戏或转连其他 run。评测如果结束，连接会自动断开。
