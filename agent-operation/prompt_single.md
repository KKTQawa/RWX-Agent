# RWX 完整对局评测

你将作为一名评测者参与一场 RWX 完整对局的评测。本机可能有其他评测在并行运行，你只属于下面这一局。

## 路径与连

* 运行目录：{{RUN}}（下称 <run>），X:\\game\\RWX-multiagent\\run-0010。
* 游戏已由评测方启动，不要自己启动，不要运行 gradlew。
* 所有游戏命令都通过 `\& "{{RUN}}\\rwx.cmd" <CLI 参数或命令>` 发出（已绑定本局端口）：它只替换 `python rwx-cli.py` 的可执行前缀，后面的参数和命令原样保留，例如 `\& "{{RUN}}\\rwx.cmd" --stdio`。不要直接调用 rwx-cli.py，不要读写任何共享端口文件。
* 可读：

  * X:\\game\\RWX\\agent-operation\\START.md及其内容中链接的相关文档
* 你自己创建的文件只可读写 `<run>\\tmp\\`。`<run>\\rwx.cmd`、`port`、`events-port`、`replays\\`、`commands\\`、`events-live\\` 和 `logs\\` 是启动器/游戏所有，不能编辑、删除、改名或用来寻找别的实例。
* 其他没有显示指名的文件目录。
* 不要按进程名查找或结束进程，机器上其他 java 进程属于别的评测。

## 对局配置

* 评估档位：2（管理员固定）,你无需管其含义，几乎不会影响你的评测
* 地图 '水田2P'；income x2
* 1v1：你 vs 1 个 AI medium
* 录像必须从 tick 0 开始；没有录像本局作废
* 允许投降提前结束：`rwx-game-surrender`、 `rwx-exit`

## 流程

1. 先读 START.md，了解命令与规则。
2. 按照要求配置房间，开始前用 `rwx-battleroom-show`
3. 拟定开局计划，避免开局延误战机。地图只能进入游戏之后通过命令查看。
4. `rwx-battleroom-start --record` 后立即 `rwx-game-replay-status`，必须看到 `recording: true` 和 `.replay` 文件，否则立即停止退出并报告"录像未开始"。
5. 全程 1x 实时，不暂停、不调速、不 step、不 restart，不截图，不长时间sleep(例如30s 40s 等)
6. 结束时依次执行： `rwx-game-replay-status` → `rwx-exit`（只调用一次）。

## 异常

ping 不通、卡死、超时或环境异常时，根据手册退出游戏，报告即可

