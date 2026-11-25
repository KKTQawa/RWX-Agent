# CASE3-Transport 命令手册

> 本文定义 Case 级命令契约。`rwx-micro-3-*` 为本 Case 的受限接口；底层原生运输/卸载调用必须由实现者核实。若当前引擎没有文档化的独立卸载命令，应在源码中找到真实原生机制后封装，不得伪造原生命令或直接修改单位内部状态。

## 0. Lobby（仅在受管评测载入场景前）

受管实例先停在没有地图、没有录像、没有预算的 lobby。此时只允许：

```text
rwx-micro-lobby-status
rwx-micro-lobby-enter
rwx-ping
```

先用 `rwx-micro-lobby-status` 确认 `phase=lobby`，再只调用一次 `rwx-micro-lobby-enter`。该命令没有参数；它会载入评测方预设的 task、seed 和赛道。本 CASE 没有 `begin`：入场载入完成后场景立即以 1× 运行，用 `rwx-micro-3-state` 确认 `phase=running` 后按本手册操作。

## 1. 命令总览

| 类别 | 命令 | 用途 |
|---|---|---|
| A | `rwx-micro-3-state [--json]` | 时间、资金、阶段、剩余预算和总体状态 |
| A | `rwx-micro-3-goal [--json]` | 本局目标类型、数量、目标岛达成进度 |
| A | `rwx-micro-3-production [--json]` | 工厂、队列、生产中单位和已完成单位 |
| A | `rwx-micro-3-fleet [--json]` | 运输单位位置、HP、容量、货舱与可用席位 |
| A | `rwx-game-map-show ...` | 地形、岛屿与迷雾观察 |
| A | `rwx-game-unit-list ...` | 单位/建筑列表 |
| A | `rwx-game-unit-show --id <id>` | 单体详情 |
| A | `rwx-game-unit-actions --unit <id> [--json]` | 工厂真实生产动作及队列信息（只读） |
| B | `rwx-micro-3-produce --factory <id> --unit <targetType> [--count N]` | 生产本局目标单位 |
| B | `rwx-micro-3-load --transport <id> --units <id,...>` | 将指定目标陆军装入运输单位 |
| B | `rwx-micro-3-move --transport <id> --x X --y Y` | 移动本局运输单位 |
| B | `rwx-micro-3-unload --transport <id>` | 在运输单位当前位置卸载货舱内单位 |
| C | `rwx-micro-3-help [--list|章节编号]` | 帮助 |
| C | `rwx-ping` | 探活 |

所有命令只在 `CASE3-Transport` 注册。除此表以外的通用游戏命令一律不应默认开放。

## 2. 通用约定

- A 只读，不进入 Replay；B 通过 Case 授权后调用真实引擎命令并进入 Replay；C 不改变战局（help/ping 除外）。
- 本 Case 启动后立即处于 `running`，没有 `begin`、pause、step 或 speed。
- 每条观察包含 `status`、`tick`、`gameMs`、`wallMs`。`wallMs` 使用 run 初始化时的单调墙钟原点；`gameMs` 使用引擎 tick 时间。
- `ok: submitted requestId=N` 仅表示请求已受理，不代表生产、装载、移动、抵达或卸载已经完成。
- 文本错误以 `error:` 开头；普通参数/状态错误为 `invalid_request`，明确越权为 `violation`。两者均不进入 Replay。
- 不接受任意 action ID、任意单位类型、任意建筑类型或任意坐标之外的隐藏参数；坐标仅允许用于本局运输单位移动，并受地图范围和运输单位身份校验。

## 3. 观察命令

受管实例的 `rwx.cmd --stdio --line "rwx-micro-3-fleet --json"` 直接返回一行 JSON。解析观测使用
`data`，`reply` 保留原始回执。连续的短命令可用 `--stdio --batch-file <run>\tmp\commands.txt`，
每条命令一行输出。以上方式可在分开的工具调用内使用，受管实例共享本局告警游标。
需要动态观察时，在同一次工具调用内启动 `rwx.cmd --stdio`，向 stdin 逐行写入并在继续前读完对应 stdout。

### 3.1 `rwx-micro-3-state [--json]`

建议字段：`task`、`seed`、`phase`、`tick`、`gameMs`、`wallMs`、`credits`、`incomePerSecond`、`remainingGameMs`、`remainingWallMs`、`transportAliveCount`、`targetReached`、`outcome`。

### 3.2 `rwx-micro-3-goal [--json]`

`targetIsland` 含 `area`、`boundsTiles` 与 `center`（世界坐标）。`requirements[]` 每项给出
`type`、`required`、`delivered`、`remaining` 和每单位的 `seats`。`seatsRequired` 为总需求席位，
`seatsRemaining` 为尚未送达的总席位。返回 `deliveredCounts` 和 `targetReached`。

只在进入对局后公开目标配置。`delivered` 只计存活、未装载且真实位于目标岛草地格集合内的我方陆军。

### 3.3 `rwx-micro-3-production [--json]`

`factories[]` 每项含 `factoryId`、`factoryType`、`alive`、`busy`、`queueSize` 和原生队列
`queue[]`。`queue[]` 按顺序列出每项的 `unitType` 与 `count`，含正在生产的队首。用
`producedCounts` 确认已生产数量。

### 3.4 `rwx-micro-3-fleet [--json]`

`transports[]` 返回位置、生命、容量、已用及剩余席位和原生 `order`。`cargo[]` 为已上舱 ID，
`cargoDetails[]` 含其 `id`、`type` 和 `seats`。`pendingBoarding[]` 用同样的字段列出正执行
上舱指令且尚未上舱的陆军，`unloading` 表示原生卸载动作已激活。

### 3.5 地图与单位观察

复用完整游戏只读能力：

```text
rwx-game-map-show [--spawns] [--x X --y Y] [--half-width W --half-height H] [--unit-land | --unit-air | --unit-underwater | --unit-building]
rwx-game-unit-list --owner self|enemy --full --json
rwx-game-unit-show --id <id>
rwx-game-unit-actions --unit <factoryId> --json
```

完整游戏手册中的 `map-show` 默认显示地图中心 17×17 单字符 ASCII 地形图并自动按迷雾遮罩；可用坐标和窗口尺寸裁剪，加 `--unit-*` 时每格变成 5 字符实体编码图。`unit-list` 默认有血量筛选，完整盘点应显式使用 `--full`。地图地形图不等于单位位置图；v1 不承诺陆军/空军单位地形叠加图，单位位置以 unit-list 为准。

## 4. 操作命令

### 4.1 生产

`rwx-micro-3-produce --factory <id> --unit <targetType> [--count N]`

- `factory` 必须是本局预置且归我方所有的指定工厂。
- `unit` 必须属于当前任务目标清单，且必须是该工厂实际可生产的单位。
- `count` 为正整数。提交时检查整批费用，目标缺口扣除已生产、已入队和已提交待入队的数量。
- 禁止生产额外单位、其他类型、建筑或升级工厂。
- `ok: submitted requestId=N requested=K` 表示已提交 K 个生产请求。使用 `production` 核对入队和完成。

### 4.2 装载

`rwx-micro-3-load --transport <id> --units <id,...>`

- transport 必须是本局存活运输单位；units 必须是本局已生成、存活、未装载的目标陆军。
- 容量按引擎真实**席位权重**计算：`dropship`最多可容纳 4 席、`experimentalDropship`最多可容纳 12 席。
  `mechFlame`、`mechLightning`、`mechLaser` 各单位占 **2** 席，`experimentalTank`、`experimentalHoverTank` 占 **5** 席，
  其余目标单位占 1 席。
  超出当前剩余容量或单位不符合条件时拒绝提交。受理后由原生上舱指令接近并装载，
  用 `pendingBoarding` 与 `cargoDetails` 确认进度和实际上舱。

### 4.3 移动

`rwx-micro-3-move --transport <id> --x X --y Y`

只允许移动本局运输单位。坐标必须在地图范围内，且应为引擎可接受的飞行目的地。禁止用此命令控制陆军或非运输单位。命令被受理不代表已经到达。

### 4.4 卸载

`rwx-micro-3-unload --transport <id>`

在运输单位当前位置启用原生卸载动作：运输单位停在非液体的可落地地形后，**每 30 帧卸下一个单位**。
卸载是一段持续过程，命令被受理不代表货舱已空；以 `rwx-micro-3-fleet --json` 的货舱变化和
`rwx-micro-3-goal --json` 的送达计数确认结果。卸载落点由引擎决定，不接受坐标参数。

## 5. 禁止行为

至少在 Case CLI、Gateway、通用游戏服务入口和引擎命令提交/Replay 录制边界共同拦截：

- 建造任何建筑，包括资源制造仪、工厂、炮塔或其他建筑。
- 生产目标清单以外的单位，或超过目标缺口生产。
- 升级、回收、修理或拆除建筑。
- 直接移动、攻击、停止、巡逻或其他方式操控目标陆军。
- 操控非本局运输单位、非本局工厂或敌方实体。
- 通过 `rwx-game-order-*`、通用 action、底层 Command 或其他入口绕过受限命令。
- 暂停、步进、加速、重启、投降。

违规证据至少含 `violationId`、`requestId`、原始请求/命令、actor、target、`tick/gameMs/wallMs`、`violationType`、`reason`、`rejected=true`。违规命令不得进入游戏执行层或 Replay。

## 6. 错误与生命周期

普通错误示例：`unknown_factory`、`unknown_target_type`、`factory_cannot_produce_type`、`unit_not_ready`、`unit_already_loaded`、`insufficient_capacity`、`transport_busy`、`invalid_destination`、`not_running`。

越权示例：`non_target_production`、`build_not_allowed`、`non_transport_control`、`non_case_actor`、`generic_orders_not_allowed`、`unauthorized_native_command`。

生产生命周期至少记录 `issued → accepted → queued → started → completed/spawned`，以及 `failed/cancelled/superseded/timeout`。运输生命周期至少记录 `load_issued → loaded`、`move_issued → moving → arrived`、`unload_issued → unloading → unloaded`。实际事件阶段必须以引擎可观测事实为准；不能可靠识别的阶段写 `unknown`，不得推断。

