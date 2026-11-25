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
│  └─ presets/                     4 个示例，都是当前口径（36 旋钮 + 21 权重；只换权重、不换流程）
│     ├─ hardup-takeover.json       接管基线：闸门开、数值全是原版字面量 → 应与内置 Hard 打平
│     ├─ hardup-tuned.json         真实产物 = cma-h5 gen300（60 局验证 57.5% vs Very Hard）
│     ├─ hardup-aggressive.json     示例变体：闸门全开 + 明显偏离原版的数值，用来看参数怎么起作用
│     └─ hardup-veryhard.json       换基类示例：只改 meta.base → 行为应等于内置 Very Hard
└─ env/
   ├─ duel-hardup-vs-hard.json      1v1：配置版 AI vs 原版 Hard（收入 ×2，迷雾开）
   ├─ duel-hardup-default-vs-hard.json  同上，但用默认 ai.json（= 与原版 Hard 等价，做对照）
   └─ ffa3-hardup-hard-veryhard.json    三人混战：配置版 + Hard + Very Hard（无迷雾）
```

## 1. 怎么跑

```powershell
Set-Location X:\game\RWX
.\gradlew.bat :desktop:headlessDist          # 代码或配置结构变过才需要

# 跑一局完整对局：一直跑到分出胜负（指挥中心被清空），产物落在 evaluate/RL/out/<环境 name>/
.\evaluate\RL\run-env.ps1 -Env .\evaluate\RL\env\duel-minimal.json -Verify

# 临时改 seed / 收入倍率，不改文件（对局本身仍是完整的）
.\evaluate\RL\run-env.ps1 -Env .\evaluate\RL\env\duel-hardup-vs-hard.json -Seed 4242 -Income 1.5

# 调试用：只跑一小段看流程通不通（-MaxTicks 只用于排查，不是完整对局）
.\evaluate\RL\run-env.ps1 -Env .\evaluate\RL\env\duel-hardup-vs-hard.json -Out X:\tmp\rl-smoke -MaxTicks 900

# 只看解析结果（含最终 seed/收入/输出目录），不启动引擎
.\evaluate\RL\run-env.ps1 -Env .\evaluate\RL\env\ffa3-hardup-hard-veryhard.json -DryRun
```

默认**跑完整对局**：`limits.maxTicks=216000`（1 小时游戏时间）与 `maxWallSeconds=600` 只是防挂死的安全上限，正常对局会在指挥中心被清空时自然结束并记 `outcome=win/defeat`。只有 `-MaxTicks` 或环境里显式调小才会计为 `max-ticks`（那属于调试，不算一局）。
退出码：`0` 决胜、`1` 错误、`3` 未决胜（到上限）、`4` 回放校验不一致。产物清单见下一节。

## 2. 输出位置（每局一个目录，全部在仓库内）

默认落在 **`evaluate/RL/out/<环境 name>/`**，可用 `-Out <dir>` 或环境文件里的 `out` 覆盖；`out/` 已在 `.gitignore`（第 13 行 `out/`），不会进版本库。

```text
evaluate/RL/out/duel-hardup-vs-hard/
├─ result.json          结算 + effective（实际生效的 seed/收入/迷雾）+ 各队伍态 + ticks/gameMs/wallMs
├─ samples.jsonl        **可选**（见 sampling）：每 N tick 一行资金/单位/建筑/HP/兵种直方图；环境里不写 sampling 就不生成
├─ events-live/         **可选**（见 telemetry）：评测级逐帧遥测 telemetry.jsonl + economy.log
├─ replays/
│  ├─ rollout-<时间>.replay               回放（record=true 才有）
│  └─ rollout-<时间>.replay.check.json    -Verify 时写入：consistent / desyncs / ticks
├─ env-resolved.json    环境文件 → rollout spec 的物化结果（看清 seed/收入等最终取了什么）
├─ spec.json            启动器写回的有效 spec
├─ rollout.log          引擎 stdout（`rollout.err.log` 为 stderr）
└─ mods/maps/           这一局用到的自定义地图副本
```

脚本跑完会在终端再打一遍上面这份清单；`result.json.effective` 是核对"配置真的生效了吗"的地方（`incomeMultiplier`、`seed`、`fogMode`…）。

## 3. 环境配置（`env/*.json`）

数值统一写成 `{ "value": …, "original": …, "min": …, "max": …, "note": "…" }`（写裸数字也兼容）：
`run-env.ps1` 取 `value`、按 `min/max` 校验，并把生效值写进 `env-resolved.json`。

| 字段 | 含义 | 原版/当前 | 范围 |
|---|---|---|---|
| `name` | 环境名，同时决定默认输出目录 | — | — |
| `map` | 地图：`.tmx` 路径，或名字片段（**官方 `assets/maps/*` 与自定义 `mods/maps` 都会查**；`Lake (2p)`、`River_Battle`、`10p环湖绝对平衡` 都行） | — | — |
| `out` | 输出目录（相对仓库根或绝对） | `evaluate/RL/out/<name>` | — |
| `record` | 是否录 `.replay` | `true` | 布尔 |
| `winCondition` | `commandCenter`（默认）/ `map` / `allUnitsAndBuildings` / `allBuildings` / `noConstructionOrTech` | `commandCenter` | — |
| **`seed`** | **房间随机种子（顶层，优先于 `room.seed`）**；0 = 未指定，起服随机 | 各环境自己写 | 0–2147483647 |
| `room.incomeMultiplier` | **房间收入倍率** | `1.0` | 0.1–5.0 |
| `room.startingCredits` | 起始资金；0 = 地图默认 | `0` | 0–20000 |
| `room.fogMode` | `0` 无雾 / `1` 一次性 / `2` 正常 | `2` | 0–2 |
| `room.revealedMap` | 全图可见 | `false` | 布尔 |
| `room.startingUnits` | 起始单位档位 | `1`（地图默认） | 0–1 |
| `room.noNukes` | 禁核 | `false` | 布尔 |
| `room.aiDifficulty` | 未在 `slots` 指定 AI 的槽位默认难度码 | `1` | -2–3 |
| `slots[]` | 每号位：`slot` / `ai`（注册表 id 或数字码）/ `name` / `aiConfig` | — | ≥2 个 |
| `limits.maxTicks` | 模拟 tick 上限（60 tick = 1 秒） | `216000` | 60–216000 |
| `limits.maxWallSeconds` | 墙钟上限（秒） | `600` | 5–3600 |
| `sampling` | **可选**：整段省略 / 写 `null` / 写 `false` = 不产出 `samples.jsonl`（本通道自带的观测文件，与原版和评测都无关） | 省略不写 | — |
| `sampling.everyTicks` | 采样间隔（tick） | `60` | 1–3600 |
| `sampling.includeUnitTypes` | 采样是否带兵种直方图 | `true` | 布尔 |
| `telemetry` | **可选**：`true` 时启用评测侧 `EngineEvidence`，写 `events-live/<match>/telemetry.jsonl` + `economy.log`（逐帧事件流，评测口径）。实测约 **2.3× 变慢**、5.2 MB / 333 游戏秒 | `false` | 布尔 |

命令行可临时覆盖，不用改文件：`-Seed 4242`、`-Income 1.5`、`-MaxTicks 900`、`-Out <dir>`。

### 3.1 现成示例（`env/` 下每个文件都能直接跑）

| 文件 | 演示什么 | 关键差异 |
|---|---|---|
| `duel-hardup-vs-hard.json` | 配置版 AI vs 原版 Hard（基准） | 收入 ×2、Lake 2p、录回放 + 1 Hz 采样 |
| `duel-hardup-default-vs-hard.json` | 默认 `ai.json` = 原版 Hard 的对照 | 同规则，基类/闸门都是默认值 |
| `duel-hardup-vs-hard-swapped.json` | 双方槽位对调 | 抵消出生位不对称，和基准成对跑 |
| `duel-veryhard-base-vs-hard.json` | **换基类**：`meta.base=rwx.original.very-hard` | 对称图 Two Sides，收入 1.0，日志 `difficulty=2 income=1.8` |
| `duel-minimal.json` | **最小训练形状** | `record=false`、**没有 sampling 段** → 只留 `result.json` |
| `duel-telemetry.json` | **评测口径** | `telemetry=true` → `events-live/telemetry.jsonl`（约 2.3× 变慢） |
| `duel-custom-ais.json` | 自定义 AI 可插拔 | 两边都是自定义 AI（`rwx.ai-s` vs `rwx.ai-autopilot`） |
| `ffa3-hardup-hard-veryhard.json` | 三人混战 | 无迷雾、起始资金 4000、3 槽位 |
| `ffa4-mixed-difficulty.json` | 四人混战 + 四档难度 | Islands 4p、无迷雾、采样 2 Hz、无兵种直方图 |

`slots` 就是"1号位、2号位…"：`slot 0` 是结算视角（`outcome=win/defeat`），槽位数决定房间里建几个 AI。

AI 定义随进程注册，同一 ID 的所有队伍读取同一份配置。双权重对打时，第一队用 `rwx.ai-rl-hard`，
沿用 `slots[].aiConfig`。第二队用 `rwx.ai-rl-hard-2`，在环境 JSON 顶层用 `aiConfig2` 指定第二份文件。
使用 rlkit 时，对应参数为 `--opponent-id rwx.ai-rl-hard-2 --opponent-config <权重文件>`。

## 4. 倍率：只有"收入倍率"，没有"游戏速度倍率"

终局收入由**两层**相乘，两个都可在配置里调：

| 层 | 位置 | 原版值 | 说明 |
|---|---|---|---|
| 房间倍率 | `env/*.json` → `room.incomeMultiplier` | `1.0` | 对所有队伍一致；跨配置比较必须固定 |
| AI 自身倍率 | `AI Hard-up/ai.json` → `definition.incomeMultiplier` | Hard `1.4`（Medium 1.0 / Very Hard 1.8 / Impossible 3.0） | 每个 AI 一份，决定"难度差" |

即：**最终收入 = 房间倍率 × AI 倍率 × 地图矿区产出**。

RL 通道**没有** `game-speed` 这类"模拟速度倍率"：推进速度就是"逐原版 tick 不节流"，一个 tick 仍是
`gameLoop(1f, 16)`；想控制一局多长用 `limits.maxTicks`（训练常见 6 000–12 000 ≈ 100–200 游戏秒），
想控制产出量用 `sampling.everyTicks` 和 `record`。原版 `--game-speed` 放大的是单次 update 的步长，
会改变模拟语义，训练/评测不用它。

`seed` 的作用范围（详见 `KNOWN_LIMITS.md`）：只固定引擎的确定性抖动（地图 spawner 刷什么兵/刷在哪、
波次落点与任务目标点、单位初始朝向偏移、弹道散布），**不固定 AI 决策**（原版 AI 用未播种的 `Math.random()`），
所以同 seed 两局仍会从几十 tick 起分叉。

## 5. AI 配置（`AI Hard-up/ai.json`）

### 5.1 生效机制

这个 AI 注册为 `rwx.ai-rl-hard`（code 20），实现只用引擎已经暴露的钩子：
`AiDefinition`（收入/节拍/保留哪些原版阶段）、`overrides*()` 四个接管闸门、`onEconomy/onUnitProduction/
onBuildingProduction/onUpgrades/onTactics` 回调。**不需要改任何引擎源码**；加一个预设=加一个 `ai.json` 文件。

**`meta.base` 决定继承谁，不写死难度**：可写注册表 id（`rwx.original.very-hard`、`rwx.ai-hard-1income`…）、
难度码（`-2…3`）或简称（`very-easy/easy/medium/hard/very-hard/impossible`）。继承的是这一项的**难度、
收入倍率、原版阶段集合、回调节拍**，随后本文件逐项覆盖：

- `definition.incomeMultiplier` 省略 → 用 base 的（Hard 1.4 / Very Hard 1.8 / Impossible 3.0）
- `definition.originalPhases` 省略某个键 → 用 base 的该相位开关
- `definition.cadence` 省略 → 用 base 的节拍
- 启动日志打印 `RWX_RL_AI_BASE <id> difficulty=N income=X phases=[…]`，跑完可核对

默认 `meta.base=rwx.original.hard` + 四个原版阶段全开 + 所有 `overrides` 为 `false` → 决策逻辑与原版 Hard
完全相同（同一组原版阶段、同一收入；只是本机随机源不同，局内结果不会逐 tick 相同）。
`env/duel-hardup-default-vs-hard.json` 就是拿它和 Hard 对打的对照；把 `meta.base` 改成 `rwx.original.very-hard`
即得到"继承非常困难"的同一套可配置 AI（实测日志 `difficulty=2 income=1.8`）。

注意：能继承 base 的**难度/收入/阶段/节拍**；不能继承另一个自定义 AI 的**策略行为**——引擎没有策略组合 API，
自定义 AI 只能作为对手（`slots[].ai`），不能当父类。

### 5.2 参数（全部带 `value` / `original` / `min` / `max` / `note`）

**`ai.json` 是「引擎原值基线」：每个数值项的 `value` 都等于引擎里的原值**（`buildingScore` 20 项 =
`AiBuildingScoreTable` 字段初值、`impossible` 8 项 = 原版 Impossible 字面量、其余 = 同段 `original`）。
每个布尔项旁边写了它在原版哪个方法里、什么条件下生效，所以打开闸门也不会凭空变强，只是把原版的判断换成配置驱动。
调过的变体放 `presets/`（`hardup-takeover` 起点、`hardup-tuned` 是 cma-h5 gen300、`hardup-aggressive` 是明显偏离的示例）。

| 段 | 参数 | 当前 | 原版 | 范围 | 作用 |
|---|---|---:|---:|---|---|
| `meta` | `base` | `rwx.original.hard` | — | 任意注册表 id / `-2..3` / 简称 | 继承哪个 AI 的难度+收入+阶段+节拍；省略=Hard |
| `definition` | `incomeMultiplier`（可省略） | 1.4 | 1.4 | 0.1–3.0 | 经济倍率（省略即继承 base；再乘房间倍率） |
| | `originalPhases.{initialization,economy,tactics,strategy}` | 全 true | 全 true | 布尔 | 保留哪些原版阶段（关掉=不再跑那段原版决策） |
| | `cadence.{economy,tactics,strategy}` | 25/80/250 | 同 | 10–120 / 30–300 / 90–900 | **自定义回调**的节拍；原版计时器不受影响 |
| `overrides` | `buildingProduction` | false | — | 布尔 | 造什么由 `building.priority` 决定（选址/选人仍走原版） |
| | `unitProduction` | false | — | 布尔 | 出兵种类由 `units.weights` 决定 |
| | `upgrades` | false | — | 布尔 | 何时升级由 `upgrades` 段决定 |
| | `transportWaiting` | false | — | 布尔 | 接管运输前集结等待 |
| | `economyMaintenance` | false | — | 布尔 | 由 `economy` 段决定补采掘机/回收/维修/重定向 |
| | `tactics` | false | — | 布尔 | 给没有指令的战斗单位补进攻/后撤 |
| `building` | `attemptIntervalFrames` | 270 | 270 | 60–900 | 两次建造尝试间隔（≈`defensiveScore` 270+id%15 的建造节奏） |
| | `bankCredits` | 1300 | 1300 起分档 | 0–6000 | 低于该资金不尝试（原版按 score 分 1300…4800 六档，单值取最低档） |
| | `priority[]` | 提取器→工厂→炮塔→防空→制造仪→T2 提取器 | — | 任意类型名 | 依次尝试，第一个「没到上限且能建」的生效 |
| | `maxPerType{类型:数量}` | 陆2/空2/海1/炮塔3/防空3/制造仪5 | 同 | `-1`=不限 | 原版 if 链里的数量上限（升级后的 T2/T3 计入同族） |
| `units` | `reserveCredits` / `maxPerCycle` / `reinforcement` | 0 / 12 / false | 0 / 12 / — | 0–3000 / 1–24 | 留底资金 / 每周期最多几单 / 是否调用原版补员 |
| | `weights{类型:权重}` | 全 1.0 | 1.0（= `getUnitPriority` 的 10.0） | >0 | 相对原版 10.0 的倍率；按权重确定性地抽兵种（同 tick 同队结果固定） |
| `upgrades` | `bankCredits` / `intervalFrames` / `maxPerCycle` | 4100 / 250 / 0 | 4100 / 250 / 0 | 0–12000 / 30–1800 / 0–4 | 升级门槛 / 多久跑一次（周期，250=无额外冷却）/ 每次几个（0=不设上限） |
| `tactics` | `intervalFrames` | 800 | 编队 800 | 100–1600 | 补令节拍 |
| | `retreatHpPercent` / `resumeHpPercent` | 50 / 60 | 50 / 60 | 10–70 / 20–95 | 后撤与回归（必须滞回） |
| | `stagingDistance` | 720 | 720 | 200–1600 | attack-move 目标点离敌人多远 |
| | `focusFire` / `attackMove` | false / true | — | 布尔 | 点杀 or 推进 |
| `economy` | `harvesters` / `reclaim` / `retargetHarvesters` / `repairBuildings` | 全 true | 原版自己做 | 布尔 | 只在 `overrides.economyMaintenance=true` 时生效 |
| `slots` | `{"0": {...}, "1": {...}}` | 空 | — | — | 按队伍覆盖上面任意字段（浅合并到同名字段） |

### 5.3 `reference`：写死在引擎里的参数

`ai.json` 的 `reference` 段把原版控制器里**写死**的旋钮也列全了（路径压力阈值、基地/前哨半径与数量、
建筑评分与存款门槛、选址尝试次数、生产预算、出兵门槛、兵种比例、编队容量、攻击延迟、后撤阈值、
运输轮询、升级预算、核行为……），每项带 `value/min/max/where/applied:false`。

这些**不能**靠配置文件生效：它们散在 `AIController`/`BaseZone`/`AIStrategyNode`/`UnitGroup`/`TransporterGroup` 里，
没有读取配置的入口。列出来是为了统一口径（想调哪个就先知道它在哪、原值多少、合理范围），真要接线就得改官方文件
（按 `.agent-memory/UPSTREAM.md` 登记）。这也是"尽可能不改源码"这条约束的边界：**能改的已经全部在 §5.2 里了**。

## 6. 新增一个 AI 预设

1. 新建目录 `evaluate/RL/<你的预设名>/ai.json`，从 `AI Hard-up/ai.json` 复制后改。
2. 环境文件里给槽位写 `"ai": "rwx.ai-rl-hard"`，并用 `"aiConfig": "evaluate/RL/<你的预设名>/ai.json"` 指定文件
   （命令行启动时也可 `-Drwx.rl.aiConfig=<绝对路径>`）。
3. 跑一局看 `samples.jsonl` / `result.json` 是否按预期变化；配置里出现未知 AI id 时，报错会列出全部可用 id。

## 7. 实测与已知边界

- 实测**完整对局**（默认 limits，跑到指挥中心被清空为止，未传 `-MaxTicks`）：

  | 环境 | 结果 | tick | 游戏时长 | 纯模拟墙钟 | 速率 |
  |---|---|---:|---:|---:|---:|
  | `duel-hardup-vs-hard`（Lake 2p，aggressive 预设） | defeat（决胜） | 29 173 | 466.7 s | 3.0 s | 9 593 tick/s |
  | `duel-hardup-default-vs-hard`（River Battle，默认预设） | defeat（决胜） | 40 575 | 649.2 s | 6.8 s | 5 967 tick/s |
  | 对照：同图同 seed 的 Hard vs Hard | defeat（决胜） | 74 475 | 1 191.5 s | 10.0 s | 7 460 tick/s |

  回放：默认预设那局 `consistent=true desyncs=0`。

- 注意：上面三局**槽 0 都输**，对照局（Hard vs Hard）也一样 → 这是 River Battle / Lake 的 1v1 出生位不对称，
  不是配置 AI 的问题。做 A/B 要换对称图，或把双方槽位对调各跑一次取平均。

- 实测：官方地图按名字解析（`Lake (2p)` → `assets/maps/skirmish/[p2]Lake (2p).tmx`）能直接开，自定义图（`River_Battle`、`10p环湖绝对平衡`）同样；`-Seed 4242` 覆盖生效（`env-resolved.json` 与 `result.json.effective` 都读回 4242）。
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

## 8. 可调参数与实测（`params.json` + `optimize.py`）

从 `evaluate/RL/AI Hard-up` 运行 `optimize.py` 时，可为训练、评测和自检指定 `--scenario`。

| 场景 | 默认权重 | 默认地图池 | 搜索维度 |
|---|---|---|---:|
| `hardupv1` | `params_Hardupv1.json` | `completition_v1-19.json` | 29 |
| `hardupv2` | `params_Hardupv2.json` | `completition.json` | 56 |
| `hardupv3` | `params_Hardupv3.json` | `completition.json` | 85 |
| `hardupv4` | `params_Hardupv4.json` | `completition.json` | 103 |

[Hard-up 搜索维度表](AI%20Hard-up/HARDUP_DIMENSIONS.md)列出 v1、v3 的参数和 v4 新增项的默认值、范围、步长及引擎语义。

v1、v2 的平局基准默认分别为 0.30 和 0.20，均沿用原有时间加分。v3、v4 共用奖励函数。平局分为 `0.20 + 0.06E + 0.09B`，`E` 和 `B` 取自终局收入及在场建筑造价，分数范围为 0.20–0.35。胜局速度项以 60 分钟归一，输局存活项以 90 分钟归一。运行 v3、v4 平局需使用能输出终局 `incomePerSecond` 和 `buildingCost` 的无头包。

```powershell
python optimize.py train --scenario hardupv2 --dry-run --generations 1
python optimize.py test --scenario hardupv1
python optimize.py selftest --scenario hardupv3
python optimize.py train --scenario hardupv4 --dry-run --generations 1
```

同场景的自定义权重可用 `--params` 指定，地图池可用 `--pool` 覆盖。训练配置和元数据记录场景。旧用法仍可只传 `--params`。新 v2 用 `building.attemptIntervalFrames` 控制基地建造计时。历史 v2 权重保留原来的 `impossible.defensiveScoreBase` 行为。

v4 模板继承 v3 参数和 Hard 底座。若从某个 v3 训练产物起跑，将该文档的参数值覆盖到 v4 模板中的同路径，使用新训练的 `--params`。检查点包含各维的优化器状态，v4 维度变化后需新建检查点。

`train --scenario hardupv2 --resume <检查点>` 会为历史 57 维检查点恢复原向量布局。优先使用原训练参数或该代存档，需要时按检查点边界匹配已知历史布局。自定义历史范围匹配失败时，可用 `--params` 传入原训练参数。

### 8.1 参数清单：只看 `AI Hard-up/params.json`

全量声明在 `ai.json`（带 `value/original/min/max/note`）；**哪些值得动**单独抽到了
[`AI Hard-up/params.json`](AI%20Hard-up/params.json)，分三档：

| 档位 | 含义 | 当前内容 |
|---|---|---|
| `valuable` | 实测有方向的旋钮 | `units.weights`（配比，air −0.52 / mech +0.07…+0.14）、`upgrades.intervalFrames`（900→465，+0.11）、`building.priority`、`upgrades.bankCredits` |
| `neutral` | 实测没有可测收益，别再花时间 | `units.maxPerCycle`、`definition.cadence.economy`、`units.reserveCredits`、`building.bankCredits`、`building.attemptIntervalFrames` |
| `structural` | 不是"调多少"而是"必须先设对" | `overrides.*` 闸门、`building.maxPerType`（`-1` 会饿死后续优先级）、`units.reinforcement`（与原版补员重复）、`definition.cadence.*` |

每个条目都带：JSON 路径、默认值、范围、是否公平（`fair`）、引擎里的消费点、实测数值与样本量、
一句话结论。`optimize.py` 直接读这份文件构造可搜索空间——改参数只改这一处。

`params.json` 的 `_notTunable` 段另外列出"写在 `ai.json` 里但配置改不动"的项（`UnitGroup` 的集结/进攻
节奏、`BaseZone` 的建筑评分与分档门槛、`AIController` 的基地半径与扫描冷却……）：这些才是 AI 上限所在，
要动就得改官方文件并按 `UPSTREAM.md` 登记。

难度阶梯本身另有一份审计：
[`AI Hard-up/difficulty-ladder.md`](AI%20Hard-up/difficulty-ladder.md)。要点：六个原版难度除收入倍率
（0.4 / 0.7 / 1.0 / 1.4 / 1.8 / 3.7）外，只有 8 处硬编码判定，行为上只分 3 档（`<2` / `2` / `3`）——
Hard → Very Hard 只多"有钱就造实验室"，Very Hard → Impossible 多七条体量/节奏优势。

另有一份**完整可加载**的配置：[`AI Hard-up/params2.json`](AI%20Hard-up/params2.json)。它按"节拍/时间、
资金门槛、建造、生产与升级"四类把对应段填成可直接跑的值（基线完全继承 Hard，接管建造/生产/升级；
唯一偏离原版的是 `upgrades.intervalFrames=465`），每项带 `original/min/max/note`，`_groups` 是这四类的索引，
`reference` 收 21 条相关"写死项"。它仍是 `rwx-rl-ai-v1`，`--ai "evaluate/RL/AI Hard-up/params2.json"`
直接能用（扩展名不影响加载）。分工：`params.json` 回答"哪些值得调"，`params2.json` 回答"这套配置长什么样"。

### 8.2 怎么量（`optimize.py` 三条命令）

```powershell
# 探针：一个配置跑成对样本，看噪声/耗时/出生位；--dump-units 打印双方末次采样的兵种
python "evaluate/RL/AI Hard-up/optimize.py" probe --ai "evaluate/RL/AI Hard-up/presets/hardup-tuned.json" `
  --maps "Lake (2p),Small Island (2p)" --seeds 2026,1331 --workers 10 --max-ticks 40000 --sampling 1000

# 单参数扫描：一次只改一个旋钮，默认用 15k tick 的代理对局（~5s/局，比完整对局便宜约 4 倍）
python "evaluate/RL/AI Hard-up/optimize.py" screen --ai "evaluate/RL/AI Hard-up/presets/hardup-takeover.json" `
  --maps "Lake (2p),Two cold sides (2p)" --seeds 2026,1331 --workers 12 --max-ticks 15000 --sampling 500

# 同收入对决：两边都用 rwx.ai-rl-hard，定义收入锁 1.0，候选策略只写进 slots 的目标槽
python "evaluate/RL/AI Hard-up/optimize.py" duel --ai "evaluate/RL/AI Hard-up/presets/hardup-tuned.json" `
  --maps "Lake (2p),Small Island (2p),Ice Island (2p),Two cold sides (2p)" --seeds 2026,1331 `
  --repeats 2 --workers 10 --max-ticks 40000 --sampling 1000
```

产物只在 `agent-tmp/rl-opt/`，跑完自动删（`--keep` 保留）。成本：15k tick ≈ 5s/局，40k tick ≈ 8s/局，
10 并发下单局约 3s 摊薄。

### 8.3 必须先知道的口径：难度倍率挂在"AI 队对象"上

`PlayerTeam:1246` 用 `this.isTeamSpectator = this instanceof AIController` 标记 AI 队，
`PlayerTeam.b()` 只给这种队乘 `AiRegistry.incomeMultiplier(...)`。**槽 0 是本地玩家队对象，即使挂了 AI
也不会拿到这个倍率**；槽 1 是真正的 `AIController`，拿得到。

静默局直接测资金（起始 4000，双方不造兵，房间收入 ×5.0，2400 tick，`duel` 双槽同一配置）：

| 定义收入 | 槽 0 资金 | 槽 1 资金 | 解得增量 |
|---|---|---|---|
| 1.4 | 6160 | **7024** | 槽 0 2160 / 槽 1 3024 = 2160×1.4 |
| 1.0 | 6160 | 6160 | 两边都是 2160 |

所以：房间倍率两个槽都有（你说的没错），**定义里的 `incomeMultiplier` 只对 AI 队对象生效**。对 AI-vs-AI
房间来说这是继承口径的缺口——"继承了原版 AI 的全部参数"只对行为成立，对这份收入倍率不成立。

直接后果：默认打法的 1v1 是槽 1 的 1.4× 打槽 0 的 1.0×，实测 8/8 由槽 1 胜（跨 6 张官方 2 人图一致）。
**比胜负前必须把两边定义收入拉平**，`duel` 子命令就是干这个的。

要打**真** Very Hard / Impossible 的脑子，直接拿 `*_1income` 系列当对手：`rwx.ai-very-hard-1income`（code 12）、
`rwx.ai-impossible-1income`（code 13）就是"同难度大脑 + 定义收入 1.0"。它们放在槽 1 时倍率是 1.0，
槽 0 本来就拿不到倍率，于是**两个槽位收入真的相同**，不必先改 `PlayerTeam` 就能做公平对局
（`probe --versus rwx.ai-very-hard-1income`）。只有"任意定义 × 任意定义、两边还都要吃各自倍率"才需要动引擎。

### 8.4 已修的执行层问题

- **出兵配比按工厂能力过滤**：`chooseUnit` 先用 `factory.getUnitAction(type) != null` 筛掉该工厂造不了的，
  再按权重抽；某个工厂无货可出时 `continue` 而不是 `return`（旧版会让整轮生产作废，`aggressive` 预设
  200 游戏秒只出 3 个单位）。
- **真实兵种名与工厂映射**（`-Drwx.rl.dumpUnits=1` 打印 `RWX_RL_FACTORY <工厂> feasible=[...]`，实测）：
  `landFactory` → `c_tank`、`hovertank`、`c_artillery`、`scout`；`mechFactory` → `mechgun`、`mechmissile`；
  `commandCenter` → `scout`。其他常见类型：`heavyTank`、`heavyHoverTank`、`mechArtillery`、`lightGunship`、
  `c_interceptor`、`heavyInterceptor`、`c_helicopter`、`dropship`、`battleShip`、`missileShip`、`lightSub`、
  `attackSubmarine`、`gunBoat`、`gunShip`。大小写不敏感。

### 8.5 实测汇总

代理扫参（15k tick，2 图 × 2 种子 × 双座位 = 8 局/变体，基线噪声约 ±0.05）：快速升级 +0.11、
机甲混编 +0.07…+0.14、防御优先 +0.04、低升级门槛 +0.04；`maxPerCycle` 12→6 −0.03；
**空军混编 −0.52**；`cadence.economy` 10/16/40 ≈0；`bankCredits` / `attemptIntervalFrames` 在噪声内。

同收入对决（40k tick，采样终态，成对座位）：

| 配置 | 局数 | 兵力差（总） | 槽 0 | 槽 1 | HP 差 |
|---|---|---|---|---|---|
| takeover 基线 | 16 | +0.12 | +0.11 | +0.14 | −0.03 |
| + 快速升级 465 | 16 | +0.21 | +0.28 | +0.15 | −0.03 |
| + 机甲混编 | 16 | +0.01 | +0.12 | −0.09 | −0.01 |
| `hardup-tuned` | 16 | +0.22 | +0.26 | +0.19 | +0.03 |
| takeover 基线 | 32 | **+0.10** | +0.20 | −0.00 | −0.07 |
| `hardup-tuned` | 32 | **+0.11** | +0.14 | +0.07 | −0.09 |

16 局加到 32 局后两个配置都回落到 +0.10 左右——**16 局那次看到的 +0.21/+0.22 是噪声**。单局终态方差
很大，16 局均值的标准误就有 ±0.1，小于这个量级的差异都不能当结论。

### 8.6 诚实的结论

- **公平前提下没有找到可复现的显著提升**：把基地接管打开、按工厂能力出兵、调快升级节拍，在同等收入
  下与原版 Hard 的差距落在噪声里（32 局：+0.10/+0.11，HP 差为负）。配置层能"打平但不更强"，形态是
  单位更多、建筑更少。
- **"Hard 打败 Very Hard/Impossible" 在这个通道里不是可公平测量的命题**：难度差主要是
  `AiDefinition.incomeMultiplier`（1.4 / 1.8 / 3.0），而它只对槽 1 生效；同收入下原版 AI 之间长期僵持
  （8 局 80k tick 无胜负），胜负只在有收入差时出现。要回答这个问题得让两个槽位都按同一口径结算收入
  （改 `PlayerTeam` 或给 rollout spec 加每侧收入），按 `UPSTREAM.md` 登记后才行。
- **瓶颈不在配置层**：中后期胜负由原版 `UnitGroup` 的集结/进攻节奏决定，配置层只能改"造什么/何时造"。
