# evaluate/RL —— 配置驱动的 AI 与对局环境

这里放的是**训练/实验用的配置层**，不动评测口径：一个 AI 预设目录（`AI Hard-up/`）+ 若干环境文件（`env/`）
+ 一条启动脚本（`run-env.ps1`）。底层执行器是 `agent-operation/tools_developer/start-rollout.ps1`
（`--rollout-config`，逐原版 tick 不节流），本目录只负责「把两份 JSON 变成一局」。

```text
evaluate/RL/
├─ README.md                        本文件
├─ run-env.ps1                      环境文件 → 对局：解析、物化 spec、跑一局（可 -Verify 校验回放）
├─ AI Hard-up/                      AI 预设目录（=一个可注册的自定义 AI）
│  ├─ ai.json                       **默认配置**：继承原版 Hard 的一切，所有接管闸门关闭
│  └─ presets/
│     └─ hardup-aggressive.json     示例变体：打开全部接管闸门，用来说明每个参数怎么起作用
└─ env/
   ├─ duel-hardup-vs-hard.json      1v1：配置版 AI vs 原版 Hard（收入 ×2，迷雾开）
   ├─ duel-hardup-default-vs-hard.json  同上，但用默认 ai.json（= 与原版 Hard 等价，做对照）
   └─ ffa3-hardup-hard-veryhard.json    三人混战：配置版 + Hard + Very Hard（无迷雾）
```

## 1. 怎么跑

```powershell
Set-Location X:\game\RWX
.\gradlew.bat :desktop:headlessDist          # 代码或配置结构变过才需要

# 跑一局（默认读 env 里的 out 目录）
.\evaluate\RL\run-env.ps1 -Env .\evaluate\RL\env\duel-hardup-vs-hard.json -Verify

# 冒烟：只跑 10 游戏秒，不写 out
.\evaluate\RL\run-env.ps1 -Env .\evaluate\RL\env\duel-hardup-vs-hard.json -Out X:\tmp\rl-smoke -MaxTicks 600

# 只看解析结果，不启动引擎
.\evaluate\RL\run-env.ps1 -Env .\evaluate\RL\env\ffa3-hardup-hard-veryhard.json -DryRun
```

产物与退出码同 rollout 通道：`result.json`（结算 + 生效值 + 队伍态）、`samples.jsonl`（按 tick 采样）、
`replays/*.replay`、`replaces/*.check.json`（`-Verify`）。退出码 `0` 决胜、`1` 错误、`3` 未决胜（到上限）、
`4` 回放校验不一致。

## 2. 环境配置（`env/*.json`）

| 字段 | 含义 | 备注 |
|---|---|---|
| `name` | 这一组环境的显示名 | 只用于输出 |
| `map` | 地图：`.tmx` 路径（相对仓库根或绝对），或**地图名里的独特片段** | 片段在 `mods/maps` 里不区分大小写模糊匹配；匹配到多个会报错并列出候选 |
| `out` | 材料目录 | `-Out` 可覆盖 |
| `record` | 是否录 `.replay` | 训练批量可 `false`，抽样局再开 |
| `winCondition` | `commandCenter`（默认）/ `map` / `allUnitsAndBuildings` / `allBuildings` / `noConstructionOrTech` | 和其它评测一致用 `commandCenter` |
| `room.incomeMultiplier` | 收入倍率 | 最终再乘每个 AI 的收入倍率（Hard=1.4） |
| `room.startingCredits` | 起始资金 | `0` = 用地图默认 |
| `room.fogMode` | `0` 无雾 / `1` 一次性 / `2` 正常 | |
| `room.revealedMap` | 是否全图可见 | 与 `fogMode` 配合 |
| `room.startingUnits` | 起始单位档位 | 地图默认值是 `1` |
| `room.noNukes` | 禁核 | |
| `room.seed` | 随机种子（世界随机） | **不固定 AI 决策**，见 §5 |
| `room.aiDifficulty` | 未指定 AI 的槽位用的默认难度码 | |
| `slots[]` | **对局信息：每个位置放哪个 AI** | `slot` 从 0 开始，`0` 是被测量方；`ai` 写注册表 id 或数字码；`name` 仅供输出 |
| `slots[].aiConfig` | 该槽位使用哪个 AI 配置文件 | 一个进程只能有一份（见下）；不同槽位要不同参数时用 `ai.json` 的 `slots` 段 |
| `limits.maxTicks` / `maxWallSeconds` | 停止上限 | 两者先到先停 |

`slots` 就是"1号位、2号位…"：`slot 0` 是结算视角（`outcome=win/defeat`），槽位数决定房间里建几个 AI。

**一个进程一份 AI 配置**：AI 定义在进程启动时注册一次，所以同一进程里所有同一 id 的 AI 用同一份文件；
`run-env.ps1` 会在多个槽位给出不同文件时直接报错，并提示改用 `ai.json` 的 `slots` 段按队伍覆盖。

## 3. AI 配置（`AI Hard-up/ai.json`）

### 3.1 生效机制

这个 AI 注册为 `rwx.ai-rl-hard`（code 20），实现只用引擎已经暴露的钩子：
`AiDefinition`（收入/节拍/保留哪些原版阶段）、`overrides*()` 四个接管闸门、`onEconomy/onUnitProduction/
onBuildingProduction/onUpgrades/onTactics` 回调。**不需要改任何引擎源码**；加一个预设=加一个 `ai.json` 文件。

默认文件的行为：`extendsOriginal=true` + 四个原版阶段全开 + 所有 `overrides` 为 `false` + 收入 1.4 + 节拍 25/80/250
→ 决策逻辑与原版 Hard 完全相同（同一组原版阶段、同一收入；只是本机的随机源不同，局内结果不会逐 tick 相同）。`env/duel-hardup-default-vs-hard.json` 就是拿它和 Hard 对打的对照实验。

### 3.2 参数（全部带 `value` / `original` / `min` / `max` / `note`）

| 段 | 参数 | 当前 | 原版 | 范围 | 作用 |
|---|---|---:|---:|---|---|
| `definition` | `incomeMultiplier` | 1.4 | 1.4 | 0.1–3.0 | 经济倍率（再乘房间倍率） |
| | `originalPhases.{initialization,economy,tactics,strategy}` | 全 true | 全 true | 布尔 | 保留哪些原版阶段（关掉=不再跑那段原版决策） |
| | `cadence.{economy,tactics,strategy}` | 25/80/250 | 同 | 10–120 / 30–300 / 90–900 | **自定义回调**的节拍；原版计时器不受影响 |
| `overrides` | `buildingProduction` | false | — | 布尔 | 造什么由 `building.priority` 决定（选址/选人仍走原版） |
| | `unitProduction` | false | — | 布尔 | 出兵种类由 `units.weights` 决定 |
| | `upgrades` | false | — | 布尔 | 何时升级由 `upgrades` 段决定 |
| | `transportWaiting` | false | — | 布尔 | 接管运输前集结等待 |
| | `economyMaintenance` | false | — | 布尔 | 由 `economy` 段决定补采掘机/回收/维修/重定向 |
| | `tactics` | false | — | 布尔 | 给没有指令的战斗单位补进攻/后撤 |
| `building` | `attemptIntervalFrames` | 180 | 270 | 60–900 | 两次建造尝试间隔 |
| | `bankCredits` | 0 | 1300 起分档 | 0–6000 | 低于该资金不尝试 |
| | `priority[]` | 提取器→工厂→炮塔→防空→制造仪 | — | 任意类型名 | 依次尝试，第一个「没到上限且能建」的生效 |
| | `maxPerType{类型:数量}` | 见文件 | — | `-1`=不限 | 到达上限就跳过该类型（升级后的 T2/T3 计入同族） |
| `units` | `reserveCredits` / `maxPerCycle` / `reinforcement` | 0 / 2 / false | 0 / 12 / — | | 留底资金 / 每周期最多几单 / 是否调用原版补员 |
| | `weights{类型:权重}` | 见文件 | 原版近似均匀随机 | >0 | 按权重确定性地抽出兵种类（同 tick 同队结果固定） |
| `upgrades` | `bankCredits` / `intervalFrames` / `maxPerCycle` | 1200 / 180 / 1 | 4100 / 900 / 1 | | 升级门槛/间隔/每次几个 |
| `tactics` | `intervalFrames` | 60 | 编队 800 | 20–600 | 补令节拍 |
| | `retreatHpPercent` / `resumeHpPercent` | 30 / 60 | 50 / 60 | 10–70 / 20–95 | 后撤与回归（必须滞回） |
| | `stagingDistance` | 600 | 720 | 200–1600 | attack-move 目标点离敌人多远 |
| | `focusFire` / `attackMove` | false / true | — | 布尔 | 点杀 or 推进 |
| `economy` | `harvesters` / `reclaim` / `retargetHarvesters` / `repairBuildings` | 全 true | 原版自己做 | 布尔 | 只在 `overrides.economyMaintenance=true` 时生效 |
| `slots` | `{"0": {...}, "1": {...}}` | 空 | — | — | 按队伍覆盖上面任意字段（浅合并到同名字段） |

### 3.3 `reference`：写死在引擎里的参数

`ai.json` 的 `reference` 段把原版控制器里**写死**的旋钮也列全了（路径压力阈值、基地/前哨半径与数量、
建筑评分与存款门槛、选址尝试次数、生产预算、出兵门槛、兵种比例、编队容量、攻击延迟、后撤阈值、
运输轮询、升级预算、核行为……），每项带 `value/min/max/where/applied:false`。

这些**不能**靠配置文件生效：它们散在 `AIController`/`BaseZone`/`AIStrategyNode`/`UnitGroup`/`TransporterGroup` 里，
没有读取配置的入口。列出来是为了统一口径（想调哪个就先知道它在哪、原值多少、合理范围），真要接线就得改官方文件
（按 `.agent-memory/UPSTREAM.md` 登记）。这也是"尽可能不改源码"这条约束的边界：**能改的已经全部在 §3.2 里了**。

## 4. 新增一个 AI 预设

1. 新建目录 `evaluate/RL/<你的预设名>/ai.json`，从 `AI Hard-up/ai.json` 复制后改。
2. 环境文件里给槽位写 `"ai": "rwx.ai-rl-hard"`，并用 `"aiConfig": "evaluate/RL/<你的预设名>/ai.json"` 指定文件
   （命令行启动时也可 `-Drwx.rl.aiConfig=<绝对路径>`）。
3. 跑一局看 `samples.jsonl` / `result.json` 是否按预期变化；配置里出现未知 AI id 时，报错会列出全部可用 id。

## 5. 实测与已知边界

- 实测：同一张图、同一环境，**默认配置**（全闸门关）= 与 Hard 等价；**aggressive** 在 200 游戏秒内建出
  2 座陆工厂 + 1 座空工厂、6 座建筑、10 个单位，而默认配置同期是原版节奏（8 单位/5 建筑）。两局回放都
  `desyncs=0`。
- **关掉 `originalPhases.economy` 会让基地记账/统计停摆**：此时"接管建造"几乎造不出东西（实测只剩指挥中心）。
  正确用法是**保留 economy 阶段**，只打开 `overrides.buildingProduction` 等决策闸门——接管的是"决定什么"，
  不是"维护基地的那套循环"。
- **同一份配置两次 rollout 不是逐 tick 可复现**：`room.seed` 只固定世界随机，原版 AI 决策用未播种的
  `Math.random()`。不影响回放一致性。
- 一进程一局（引擎限制），批量靠多进程 + 独立 `-Out`；启动约 2–3 秒。
- 本目录只做训练/实验，不进评测账本；评测口径请走 `agent-operation/server/PARALLEL_EVALUATION.md`。
