# RWX 快速对局 rollout（RL 训练用）

这是一个**训练通道**，不是评测通道：一条命令跑完一局完全由 AI 驱动的 1v1 对局，尽量快，并落下可用于训练的
材料（结算、逐 tick 采样、可校验的回放）。评测口径、排行榜和 `evaluate/` 的评分链路都不在这里。

```powershell
Set-Location X:\game\RWX
.\gradlew.bat :desktop:headlessDist

# 一局 + 回放校验
.\agent-operation\tools_developer\start-rollout.ps1 `
  -Spec .\agent-operation\tools_developer\rollout-example.json `
  -Out X:\game\RWX-multiagent\rl-001 -Verify
```

实测（本机，River Battle 1v1，自定义 AI vs 原版 Hard，收入 ×2）：**842.7 游戏秒 / 52672 tick 在 6.2 s 内跑完**
（约 8500 tick/s，含启动共 9.1 s），回放校验 `desyncs=0`。真正能压到多快取决于地图规模与 AI 强度。

## 1. 为什么不是现成通道

| 现成路径 | 能做什么 | 为什么不能直接当 RL step |
|---|---|---|
| `--headless --map=… --ticks=…`（`HeadlessDesktopRunner`） | 直接载图、按 60 Hz 推进、定 tick 退出 | 只载图，不建战役室，**不能配置双方 AI / 收入 / 起始资金**；主循环固定 `LockSupport.parkNanos` 睡到 60 Hz |
| 评测 CLI（`rwx-battleroom-*` + `rwx-game-speed`） | 能建局、能配 AI、能录回放 | `rwx-game-speed` 放大的是单次 `GameLogic.update` 的步长（`f *= gameSpeed`），等于改模拟语义；后台事件采样按**墙钟** 250 ms，跑快就漏事件 |
| micro 受管实例 | 能逐 tick 同步推进 | 一局一进程一场景，且场景是手工摆的单位，不是完整对局 |

本通道的取法：**建局仍然走战役室**（地图 / 收入 / 起始资金 / 迷雾 / 胜利条件都是引擎自己的规则），
**推进改成逐原版 tick、不节流**——每个 tick 仍然是一次 `gameLoop(1f, 16)`，和实时对局 1× 时完全相同的一步。

## 2. 一条命令

```powershell
.\agent-operation\tools_developer\start-rollout.ps1 -Spec <spec.json> [-Out <dir>] [-MaxTicks N] [-Verify] [-Quiet]
```

- `-Out`：覆盖 spec 里的 `out`（同一份 spec 可以跑很多局，沙盒/批量时用它区分目录）。
- `-MaxTicks`：覆盖 `limits.maxTicks`，冒烟测试用（例如 `-MaxTicks 600` = 10 游戏秒）。
- `-Verify`：跑完再用 `--replay-check` 把回放按最大速度重放一遍，报告引擎的 checksum 失配数。
- `-Quiet`：不打印汇总。

也可以直接调 java（脚本只是包装）：

```powershell
java -Xmx1536m -Dfile.encoding=UTF-8 --enable-native-access=ALL-UNNAMED `
  --sun-misc-unsafe-memory-access=allow `
  -Drwx.assetsDir=X:\game\RWX\assets -cp "X:\game\RWX\desktop\build\headless\lib\*" `
  io.github.rwx.DesktopMain --no-steam `
  --rollout-config=<spec.json> --data-dir=<out>
```

退出码：`0` 决出胜负、`1` 参数/加载/引擎错误、`3` 到达 tick 或墙钟上限（未决胜）、`4` 回放校验不一致。

## 3. spec 字段

```json
{
  "schema": "rwx-rollout-v1",
  "map": "X:/game/RWX/mods/maps/[p2]River_Battle.tmx",
  "out": "X:/game/RWX-multiagent/rl-001",
  "record": true,
  "winCondition": "commandCenter",
  "perspective": { "mode": "team", "slot": 0 },
  "room": { "incomeMultiplier": 2.0, "startingCredits": 0, "fogMode": 2, "revealedMap": false,
            "startingUnits": 1, "noNukes": false, "seed": 1331, "aiDifficulty": 1 },
  "teams": [ { "slot": 0, "ai": "rwx.ai-hard-1income", "name": "A" },
             { "slot": 1, "ai": "rwx.original.hard",     "name": "B" } ],
  "limits": { "maxTicks": 60000, "maxWallSeconds": 180 },
  "sampling": { "everyTicks": 60, "includeUnitTypes": true }
}
```

| 字段 | 含义 |
|---|---|
| `map` | `.tmx` 路径。绝对路径优先；相对路径先按工作目录、再按 `out` 目录找。 |
| `out` | 材料目录；不存在会自动创建。`-Out` 可覆盖。 |
| `record` | 是否录 `.replay`（默认 `true`）。RL 大规模训练可关掉，抽样局再打开。 |
| `winCondition` | `commandCenter`（默认，评测口径：一队指挥中心全灭即结束）/ `map` / `allUnitsAndBuildings` / `allBuildings` / `noConstructionOrTech`。 |
| `perspective` | 胜负从谁的视角写：`{"mode": "team"\|"individual", "slot": N}`。`slot` 是队伍槽位（引擎里 `teamId` = 槽位 = spawn-1），缺省 `-1` = 引擎的 player team。`team` = 同色队伍全灭才算输（训练用这个）；`individual` = 自己这一队出局就算输。整节缺省 = player team + individual，与历史行为一致。 |
| `room` | 战役室规则：收入倍率、起始资金、迷雾、起始单位、禁核、随机种子、加入 AI 的默认难度。字段缺省用引擎默认。 |
| `teams` | `slot` → `ai`。**`ai` 可以写数字难度码（`1` = 原版 Hard）或注册表 id**（`rwx.original.hard`、`rwx.ai-hard-1income`…）。必须包含 `slot 0`（被测量方）；槽位数决定战役室创建几个 AI。 |
| `limits` | `maxTicks` / `maxWallSeconds`，两者先到先停。 |
| `sampling` | 每 `everyTicks` 采一行；`includeUnitTypes` 让每行带兵种计数。 |

**自定义 AI 可插拔**：`core/src/main/java/com/corrodinggames/rts/game/ai/custom/` 下新增一个
`AiStrategy` + 在 `CustomAiCatalog.definitions()` 注册（`AiDefinition.custom(code, id, …)`，`code >= 4` 且永不复用），
spec 里写它的 id 或 code 就能上场；不需要改本通道的任何代码。

## 4. 产物

```
<out>/
├─ result.json          这一局的结算（见下）
├─ samples.jsonl        逐 tick 采样，一行一个采样点
├─ replays/<name>.replay  引擎写的回放（record=true 时）
├─ replays/<name>.replay.check.json  -Verify 的校验报告
├─ spec.json            本次实际使用的 spec（含 -Out/-MaxTicks 覆盖后的值）
└─ rollout.log / rollout.err.log     进程日志
```

`result.json`（`schema: rwx-rollout-result/1`）关键字段：

| 字段 | 说明 |
|---|---|
| `outcome` | `victory` / `defeat`（对 `perspective` 指定的队伍而言）/ `max-ticks` / `wall-limit` |
| `perspective` | 实际使用的视角：`mode`、请求的 `slot`、解析出的 `teamId`，以及 `allies` / `enemies` 的队伍 id 列表（同色 = 盟友，`PlayerTeam.d`；异色 = 敌方，`PlayerTeam.c`） |
| `decisive` | 是否真正决出胜负 |
| `winnerTeam` | 决胜时的获胜队伍 id（未决胜为 `null`） |
| `ticks` / `gameMs` / `wallMs` / `ticksPerSecond` | 推进了多少 tick、游戏时间、纯模拟墙钟、吞吐 |
| `specTeams` | spec 里声明的槽位 → AI id/code |
| `teams` | 引擎里的实际队伍：`teamId`、`name`、`side`（阵营）、`aiDifficulty`（= 实际 AI 码）、`defeated`、`units`、`credits`、`commandCenters`（存活指挥中心和地图标记的等效目标数） |
| `room` / `winCondition` / `map` | 实际生效的规则与地图 |
| `effective` | 从引擎读回的**实际生效值**（收入倍率、起始资金、迷雾、起始单位、禁核、随机种子）；与 `room` 不一致就说明引擎没采纳该规则 |

`samples.jsonl` 每行：

```json
{"tick":60,"gameMs":944,"teams":{"0":{"name":"Player","side":0,"credits":4022.5,"units":2,
 "buildings":1,"hp":4170.0,"shield":0.0,"types":{"builder":1,"commandCenter":1}},"1":{…}}}
```

采样是**按 tick** 的（不是墙钟），所以跑快跑慢得到的是同一条序列。

## 5. 结算口径

视角由 `perspective` 决定（`slot` 解析成队伍，缺省 `-1` = 引擎的 player team）：

- **`individual`**：`slot` 这一队出局 → `defeat`；只有视角队就是 player team 时才参考引擎的
  `hasWonGame` / `hasLostGame`（那两个 flag 只对 player team 有意义）。
- **`team`**：同色的所有队伍（`PlayerTeam.d`，含自己）都出局才算 `defeat`——队友还活着就不算输。
- 两种模式下 `victory` 一致：敌方（`PlayerTeam.c`）所有队伍都出局。
- 出局 = `isTeamVictory` / `isTeamDefeated` / `isTeamDefeatedTech` / `isTeamWipedOut`，
  或者已无可战单位（`getUnitCount(true, false) <= 0`，用来兜住标志位晚一个检查周期的情况）。
- 否则继续，直到 `limits` 上限 → `max-ticks` / `wall-limit`。

`team` 与 `winCondition=commandCenter` 同时启用时，按两边全队的存活指挥中心判定。地图标记的等效目标也计入。对局在一方最后一个目标被摧毁时结束，`teams[].commandCenters` 记录各队终局的目标数。

## 6. 回放可信性

- 录制在**第一个 tick 之前**由引擎自己的 `ReplayEngine` 开始，结束走 `ReplayEngine.e()`（flush + 写 `end` 块 +
  等写线程结束），不是杀进程；`end_meta` 里能看到 `frames` / `time` / `commandCount`。
- `--replay-check=<file.replay>` 用同一条 `gameLoop` 路径把回放重放（不节流），逐 tick 比对引擎自己写的 checksum，
  结果落到 `<file>.check.json`：

```powershell
java ... io.github.rwx.DesktopMain --no-steam --replay-check=X:\...\replays\rollout-….replay
# RWX_REPLAY_CHECK replay=rollout-….replay consistent=true desyncs=0 ticks=65682 finished=true frames=55190
```

- 一批训练的推荐做法：平时 `record:false` 只收 `result.json` + `samples.jsonl`；每 N 局抽一局 `record:true` 并 `-Verify`，
  校验不过就把这一批的回放策略当噪声源排查。
- 回放里保存了 `seed`（spec 的 `room.seed`），重放端恢复同一随机序列。

## 7. 已知边界

- **同一 spec 两次 rollout 不会逐 tick 相同**：`room.seed` 固定的是**世界**随机（地图载入、资源/散布、弹道散布），
  而原版 AI 在自己的决策里用未播种的 `Math.random()` / `new Random()`（`AIController` 的选单位与建策略、
  `AIStrategyNode` 的建筑落点角度/半径）。实测同 spec 两局：种子与开局完全相同，约 tick 120–180 起经济曲线分叉
  （一局 51410 tick 判负、另一局打到 60000 tick 上限）。这是原版行为，**不影响回放一致性**（回放记录的是命令与
  checksum，不是 RNG）。要可复现的对照就固定同一盘回放；要把训练变成逐 tick 可复现，需要把那几处 `Math.random()`
  改成引擎的确定性随机源——那是改动原版 AI 行为的决定，会波及既有评测基线，本通道不擅自做。
- **一进程一局**：引擎一个进程只允许一个 `GameEngine`，所以每局一个 JVM（启动约 2–3 s）。批量训练请并发多个进程，
  每个进程用独立的 `-Out`。
- `slot 0` 是"被测量方"：结算、`outcome` 都以它为准；`winnerTeam` 也按它的视角给。
- 队伍显示名由引擎按 AI 难度生成（`AI - Hard`），spec 里的 `name` 只出现在 `specTeams`，不会改游戏内队伍名。
- 不写 `evaluate/` 的证据格式（`events-live/`、telemetry JSONL）；需要评测口径请走
  [`PARALLEL_EVALUATION.md`](../server/PARALLEL_EVALUATION.md) 或 micro 流程。
- 极快推进时 CPU 是唯一瓶颈；同时开多个进程时按 `-Xmx` 与核数算好并发，别让墙钟上限误伤。
- 只支持本地战役室（1v1 或 N 人 AI 对 AI），不支持联机、存档续局、回放当输入。

## 8. 排查

| 现象 | 原因 / 处理 |
|---|---|
| `Unknown AI '<x>'`，报错里列出所有 id | `ai` 写错了；用列出的注册表 id 或数字码。 |
| `Battle room was not applied` / `Slot N is not running AI …` | 建局没按 spec 生效（例如异步载图绕过了战役室）。本通道用同步 pending-map 路径，出现即代码回归，请报告。 |
| `outcome=max-ticks`、`decisive=false` | 对局没打完；提高 `limits.maxTicks` / `maxWallSeconds`，或换 `winCondition`。 |
| 回放校验 `desyncs>0` | 这份录制不可信：先确认没有别的进程改写同一个 `out`，再复跑；稳定复现就按 UPSTREAM 的回放 desync 流程排查。 |
| `Missing runtime distribution` | 先 `.\gradlew.bat :desktop:headlessDist`。 |
