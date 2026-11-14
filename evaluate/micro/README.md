# 微操试验场（micro cases）

小规模、固定场景、可复现的实时/回合制操控评测。引擎负责布景、生命周期、命令隔离、薄网关、自动录像和结果文件；指标全部在 `evaluate/micro/` 的 Python 脚本里离线计算。

## 0. 文档分层：谁能看哪一份

四个 CASE 共用一套约定，但**文档分两套**。给被测 Agent 的文件里只写参与对局所需内容，
场景数据、指标口径与评分公式一律留在管理员侧。

场景与评分的常用可调参数集中在各 CASE 的 `config.json`，字段说明见 [`CONFIG.md`](CONFIG.md)。
`--evaluate <CASE>` 启动时会自动读取该文件；`--case-args` 显式参数优先，也可以用 `--micro-config <file>`
临时换一份配置。

| 文件 | 读者 | 内容 |
|---|---|---|
| [`EVALUATION.md`](EVALUATION.md) | **被测 Agent** | 一次跑完四个 CASE 的统一入口：测试结构、受管运行说明、各 CASE 第一步、参与边界 |
| `CASE*/prompt_single.md` | **被测 Agent**（管理员替换 `{{RUN}}` 后发放） | 单局运行目录、连接方式、允许操作与异常边界 |
| `CASE*/START.md` | **被测 Agent** | 单个 CASE 的任务目标、最小操作顺序与参与边界 |
| `CASE*/commands.md`、`CASE*/command.md` | **被测 Agent** | 命令手册（会打进 core jar，供 `rwx-micro-<n>-help` 读取） |
| `CASE*/README.md` | 管理员 / 开发者 | 怎么跑、场景怎么布、材料在哪 |
| [`CONFIG.md`](CONFIG.md) + `CASE*/config.json` | 管理员 / 开发者 | 每个 CASE 的 run 默认值、评测参数与地图/场景参数；改完重启生效 |
| `CASE*/METRICS.md` | 管理员 / 开发者 | 材料字段、指标定义、阈值、扣分口径 |
| `CASE*/prompt.txt`、`CASE*/score_design.md`、`CASE*/*.py` | 管理员 / 开发者 | 设计稿、实现提示词、评分实现 |
| `design.txt` | 管理员 | 最初的 CASE 设计草稿（含未实现的提案） |
| 本文件 | 管理员 / 开发者 | 运行时机制、证据契约、新增 CASE 流程、人类基线 |

两条硬规则：

- **受管单 CASE 只把替换过 run 的单局 prompt、`START.md` 和 `commands.md`（或 `command.md`）交给被测 Agent。** 同一目录下的
  `README.md`、`METRICS.md`、`prompt.txt`、`score_design.md` 不得出现在 Agent 可见的文件列表里。
- 只测一个 CASE 时，Agent 只看该 CASE 的 `prompt_single.md`、`START.md` 与命令手册；测全部四个时再加 [`EVALUATION.md`](EVALUATION.md)。
  `EVALUATION.md` 里不含任何 CASE 的敌方配置、数量、坐标或布景算法。

## 1. 受管并行运行

多 Agent 正式微操评测使用仓库外的一局一目录启动器；流程、所有权边界和完成后归档见
[`../../agent-operation/server/PARALLEL_MICRO_EVALUATION.md`](../../agent-operation/server/PARALLEL_MICRO_EVALUATION.md)。
启动器接受全部四个 CASE（`CASE1-duel`、`CASE2-LTE`、`CASE3-Transport`、`CASE4-Retreat`），每个 CASE 都有
自己的 `prompt_single.md`；交接时只替换 `{{RUN}}`。入场后 CASE1/2/4 先到 briefing、需 `begin`，CASE3 直接运行。
实时材料先写 `<run>\micro-output\`，仅在 `result.json` 完整后由管理员用 `collect_runs.py --apply` 移入
`evaluate/output/micro/<CASE>/`，从而既隔离并行过程，又让 case 汇总器只读取完成材料。移动时它会同时重定位
`meta.map.file` 与回放里记录的绝对地图路径（`evaluate/utils/replay_map.py`），否则回放会因地图找不到而无法观看。
随后用 `evaluate/tools/stamp_micro_meta.py --runner agent|baseline|human --apply` 声明参与者：它会写
`models` / `tools` / `runner` / `display_name`，并把 run 目录改名成 display name，所以归档目录名本身就是
`<case> <task> realtime · <时间> · <模型> - <工具> · s<seed>`（脚本基线与人类局写 `baseline` / `human`；
同一配置重跑时末尾再加 ` · 0N`，N 记在 `meta.attempt`），
而不是只有环境戳的 `<case>_<task>_<track>_s<seed>_<时间戳>`。

## 2. 启动

> 本节是管理员视角的参数说明。被测 Agent 的受管流程见各 CASE 的 `prompt_single.md`；
> 非受管练习模板见 [`EVALUATION.md`](EVALUATION.md) §3。

从仓库根目录启动

```powershell
# agent，pause 赛道；headless 发行版用 :desktop:run --args
.\gradlew.bat :desktop:run '--args=--headless --no-steam --evaluate CASE1-duel --case-args task=1_2_2,seed=1,track=pause --data-dir=agent-operation/tmp/micro-a --cli-port-file=agent-operation/tmp/micro-a/port'

# 人类模式（GUI，同一布景，载入后暂停在 tick0；解除暂停即开局）
.\gradlew.bat :desktop:run '--args=--no-steam --evaluate CASE1-duel --case-args mode=human,task=1_2_2,seed=1'
.\gradlew.bat :desktop:run '--args=--no-steam --evaluate CASE4-Retreat --case-args mode=human,task=4_1_1,seed=1'

# agent 对局但开着窗口观看（--window 与 --headless 互斥；pause/realtime 都支持）
.\gradlew.bat :desktop:run '--args=--window --no-steam --evaluate CASE1-duel --case-args task=1_2_2,seed=1,track=realtime --data-dir=agent-operation/tmp/micro-a --cli-port-file=agent-operation/tmp/micro-a/port'
```

- `--window` 显式要求 GUI（不带 `--headless` 时本来就是窗口）。窗口模式下游戏线程由渲染循环驱动，暂停帧也会消费 CLI 排入的游戏线程任务，因此暂停时的命令与回合推进不会在无 GL 上下文的线程上碰图形；pause 模式下镜头在每个回合开始时对准我方单位；realtime 与 `mode=human` 不跟随。关闭窗口即退出进程。
- micro 模式下不运行原版 mission 的胜负流程（结果由 `MicroRuntime` 写 `result.json`），所以窗口里不会弹出原版结束界面。

- `--evaluate` 不带值保持原有完整对局行为。
- `--case-args k=v,k=v`；必填 `task`、`seed`，agent 模式另需 `track=realtime|pause`。
- 可选：`mode=agent|human`、`briefingOrders=allow|deny`（仅 realtime）、`briefingSeconds`（仅 realtime）、`seed`（可选，省略即随机并写入 meta）、`turnSeconds`/`turnTicks`（pause 默认 60 tick；`turnSeconds` 是**名义**秒，60 tick 的引擎时钟是 0.960 秒）、`wallLimitSeconds`、`gameLimitSeconds`、`startTimeoutSeconds`、`enemyDelaySeconds`、`liveSnapshots`、`out`。
- 布景完成后游戏停在 tick 0（briefing），realtime 与 pause 都一样；realtime 的 `begin` 从 tick 0 起 1× 运行，pause 的 `begin` 跑第 1 回合。
- 1 tick 名义 16.667ms，但引擎 int 截断后 1× 每 tick 只加 **16 game-ms**：60 tick → `t=0.960`、`gameMs=960`。`tickDurationMs`/`gameMsPerTick=16`，`simulationFrameMs`/`nominalTickMs=16.667`。
- 启动完成后日志出现 `RWX_MICRO_RUN <run目录>` 与 `RWX_MICRO_READY`，端口写入 `--cli-port-file`；命令客户端沿用 `agent-operation/tools/rwx-cli.py`。
  受管并行局会再加 `--micro-lobby`（见 §1）：先打印 `RWX_MICRO_LOBBY`，只有 Agent 发一次 `rwx-micro-lobby-enter` 才会出现上面两条。
- 人类模式：`Q` 键切换暂停（第一下从 briefing 开局，之后暂停/继续）。原版暂停键在 `GameUI.updateInput` 里处理，而暂停帧不会驱动 `gameLoop`，所以它只能暂停、不能恢复；`Q` 走渲染循环，双向都有效。\n- 结束行为：headless 打印 `RWX_MICRO_RESULT ...` 后直接退出进程；`--window` 或 `mode=human` 播放原版胜利/失败结算画面，`RWX_MICRO_EXIT_IN 15..1` 倒计时后退出。
- 配置文件 `evaluate/micro/config.json` 可提供默认值（`--micro-config`），命令行参数覆盖它。

## 3. 证据契约（`rwx-micro-evidence/1`）

```
<run>/
  meta.json        布景完成时写
  gateway.jsonl    薄网关，一行一条（请求/生命周期）
  result.json      结束时写
  match.replay     自动录像；stamp 后改名为 <display_name>.replay（类型1另有 map.tmx）
  replay/          离线：replay.py 解析出的底层命令
  engine/          离线：re-sim 的 snapshots.jsonl/events.jsonl/final.json/playback.json；
                   CASE 自有的 live 证据（CASE2 lifecycle、CASE3 production/transport、CASE4 turret_*/repair_sessions/tank_state 等）
  eval/            离线：metrics.json/report.txt/report.html（有 `score.py` 时 metrics.json 还带顶层 `score`）
  session/         受管局补充：原始会话 JSONL + transcript.md；评分不读取
```

上面是**引擎写出的原始形状**，`match.replay` 在 run 根目录。受管局收集进
`evaluate/output/micro/<CASE>/` 后跑 `stamp_micro_meta.py`：写入统计身份、生成
`display_name`，并把回放改名为 `<display_name>.replay`（`meta.replay` 同步）。显示名的形状与完整对局对应：
`<case> <task> [track] · <YYYYMMDD HH-MM> · <model> - <tool> · s<seed>[ · 0N]`，例如
`CASE2-LTE 2_6_4 realtime · 20261110 15-56 · DeepSeek V4.1 Flash - Pi · s1331`。
`archive_micro_runs.py` 只继续收敛解析产物与 HTML，不会把显示名回放改回机器名。
受管局在收集后把该局的原始 Agent 会话 JSONL 放进 `session/`（文件名保留会话 id），并附
`transcript.md` 便于人工复核；评分只读 `meta/result/gateway/engine`，不依赖会话文件。

### meta.json

`schema`、`case`、`task`、`seed`、`mapType`、`level`、`track`、`mode`、`agent`、`controlledTeam`、`map{file,sha256,width,height,tileSize}`、`limits{wallSeconds,gameSeconds,briefingSeconds,startTimeoutSeconds,enemyDelaySeconds}`、`turnTicks`、`turnSeconds`、`tickDurationMs`（16，实际 game-ms/tick）、`simulationFrameMs`（16.667，名义）、`gameMsPerTick`（16）、`nominalTickMs`（16.667）、`engineVersion`、`commit`、`replay`、`enemyPolicy`、`liveSnapshots`、`a`、`b`、`units[]`。

每个单位：`id`、`alias`、`team`、`sourceTeam`、`type`、`x`、`y`、`maxHp`、`maxShield`、`weapons[{index,range,damage,reloadFrames,warmupFrames,warmupNoReset,reloadTransferFrames}]`、`range`。`range`/`weapons[].range` 是中心距；`reloadTransferFrames` 是**出生时**预热对应的装填减免（机甲/猛犸出生都是 0；机甲满预热最大 19，来自 `warmupShootDelayTransfer`）。布景是 meta 的纯函数，re-sim 用同一份 meta 重建。

统计身份由管理员在收集后补：`models[{provider,id,thinking}]`、`tools[{profile,detail}]`、`display_name`（与完整对局同名字段）。用
`python evaluate/tools/stamp_micro_meta.py --run <run> --provider OpenCode --model "DeepSeek V4.1 Flash" --thinking high --tool Pi --apply`
写入；同一次调用会把回放改名为 `<display_name>.replay` 并更新 `meta.replay`。引擎不写这些字段，重跑引擎或
`evaluate.py` 也不会覆盖它们。完整对局用 `模型 / 工具` 分段，这里改用 `-`，让同一字符串可以直接当 Windows
文件名；自定义显示名若含 `/` 等非法字符，只会在文件名里替换为 `-`。

### gateway.jsonl

请求行：

```json
{"kind":"request","seq":14,"wallRecvMs":120,"wallReplyMs":125,"gameMs":0,"tick":0,"phase":"briefing","turn":0,"class":"B","name":"rwx-micro-1-move","raw":"...","status":"submitted","error":null,"units":["M1:1000"],"skippedDead":[],"parent":null}
```

生命周期行：

```json
{"kind":"lifecycle","event":"turn","wallMs":900,"gameMs":960,"tick":60,"turn":1,"reason":"boundary"}
```

不记录解析后的参数和应用 tick（这些在 replay 里）；`class` 以命令注册表为唯一来源；`status` 为 `submitted|partial|error|rejected`。

### result.json

`outcome`（`win|loss|draw|timeout|error`）、`endReason`、`gameMs`、`tick`、`wallMs`（相对首条命令）、`turns`、`kills[]`、`units[]`（终态）、`self`/`enemy`（存活数、hp、shield）。不含基线，基线由评测器附加到 `eval/metrics.json.reference`。

### snapshots/events

- `snapshots.jsonl`：默认每 250 游戏毫秒一帧，`gameMs/tick/units[]`，单位含 `x,y,hp,shield,order,target,weapons,alive`。
- `events.jsonl`：`damage`（attacker/victim/HP 与护盾伤害/之后数值/双方坐标/当时所有对手位置与射程）、`kill`、`order`（`source=player|ai|engine`）。
- 两个来源（live fallback 与 re-sim）格式相同；评测器用 `engine/playback.json` 判断是否走了 re-sim，并在报告里标 `evidence=re-sim|live/unverified`。字段只增不删，变动必须升 schema 版本。

## 4. 评测

```powershell
python evaluate/micro/CASE1-duel/evaluate.py <run目录> [--resim auto|force|skip] [--baseline auto|none|<metrics.json>] [--metrics-config <json>]
```

1. 没有 `engine/snapshots.jsonl` 且未 skip 时先 re-sim；把重放终态与 `result.json` 比对，写 `engine/playback.json`（outcome、各单位终态 hp/shield、击杀身份与顺序；每个击杀 tick 允许 ≤2 tick 偏差并记 warning，超出判失败）。`metrics.json.evidence.source` 为 `re-sim` 且 `verified=true` 才代表过了独立复算闸门。
2. 用 `evaluate/utils/replay.py` 解析底层命令，只保留 `meta.controlledTeam` 的我方命令。
3. 有 gateway 时按 (tick 窗口、种类、单位集合) 顺序匹配 B 请求；歧义/未匹配如实报告。
4. 自动发现 `metrics/*.py`（导出 `ID`、`TIER`、`compute(run)`），单指标异常不拖垮其它。
5. 生成 `eval/metrics.json`、`report.txt`、`report.html`（结局/实时性摘要 + 双方总 HP/护盾时间线 + B 类命令刻度 + 交战窗口 + pause 回合边界）。
6. 如果 CASE 目录里有 `score.py`（导出 `compute(run)`），同一份证据再生成顶层 `score` 扣分文档；指标仍不加权，评分与指标分开呈现。
   目前四个 CASE 各有一份：`case1-score-v1`（无关行为 / 机甲承受伤害 / 集体空闲）、`case2-score-v1`、
   `case3-score-v1`、`case4-score-v1`（虫王损失 / 虫王空闲 / 整体时长）。口径在各自 `METRICS.md` 的“评分”章节；
   `score` 只有扣分项、不含胜负，必须和 `outcome` 一起读。
7. **timeout 对局一律拒绝评分**：`outcome=="timeout"` 时 `score.status="REJECTED"`、`total/deduction=null`，
   `diagnostics` 记 `timeout_rejected`；四个 CASE 的 `evaluate.py` 都走同一条规则。timeout 局仍保留原始指标，
   但不参与排名、不当基线、也不产生扣分总分。

`--resim` 需要 Headless 发行包（`--dist`，默认 `desktop/build/headless`）和 Java（`--java` 或 `JAVA_HOME`）。re-sim 进程在隔离目录的 `replays/` 里读副本，不污染仓库 `replays/`。

- **live fallback**：`liveSnapshots=true` 时引擎在跑的过程中直接写 `engine/snapshots.jsonl`/`events.jsonl`；`--resim auto` 发现它们已存在就**跳过 re-sim**，因此没有 `playback.json`、没有独立复算，报告显示 `evidence=live/unverified`。它只用于调试/没有 Headless 包的场景；**正式评测用默认 `liveSnapshots=false` + re-sim**。
- **re-sim 失败**：`evaluate.py` 捕获异常写入 `diagnostics.resimError`，不会伪造 `playback.json`；如果因此没有快照，T1 指标会 N/A 或 `ERROR`。报告仍会输出 `outcome`（来自 `result.json`）并标注 `evidence=live/unverified`。`--resim skip` 同理。

## 5. 新增一个 CASE

运行时不再认识任何 case id：它只通过 `MicroCase` / `MicroSession` 两个接口拿东西。新增一个 CASE 只需在 case 自己的类里声明，不改 `MicroRuntime`、`MicroConfig`、`MicroCommandProfile`。

### 5.1 Java 侧（`core/src/main/java/.../micro/`）

1. **实现 `MicroCase`**（`<caseN>/CaseN<Name>.java`），必须实现：
   - `id()`、`prepareMap()`、`layout()`、`setup()`、`controlledTeam()`；
   - `taskInfo(task)`：**自己校验 task 语法**，返回 `TaskInfo(mapType, level, gameSeconds, wallSeconds)`（预算也在这里，`MicroConfig` 不再硬编码）；
   - `helpCommand()`：返回本 case 的帮助命令名（如 `Command.TRANSPORT_HELP.commandName()`），runtime 用它渲染 `commands.md`；
   - `profile(config)`：用 `new MicroCommandProfile(config.track, COMMANDS)` 声明本 case 接受的命令（`COMMANDS` 常量数组放在 case 类里），**命令归属只写在这一处**。
2. **可选覆盖**（默认值即"常规 case"）：
   - `startsRunning()`：true = 布景后直接 1× 运行，没有 begin/pause/step（CASE3）；
   - `requiresAgentRealtime()`：默认 true；支持回合制的 case（CASE1）返回 false；
   - `supportsHuman()`：默认 false；CASE1/CASE4 返回 true，允许 GUI `mode=human`（CASE4 仍保持 realtime-only）；
   - `reportsScenarioFailure()`：布景失败时是否仍写 `meta.json`/`result.json` 再退出；
   - `fallbackEnemyTeam()`：`layout()` 只列出一个队伍时的敌方队号；
   - `session(run, meta)`：返回本 case 的 `MicroSession`（几乎都要实现）。
3. **实现 `MicroSession`**：命令处理 + 原生命令授权 + 证据。
   - 继承 `AbstractCaseSession` 可白拿 `stamp()/emit()/reject()/permitted/allow()/recorded()/applied()/violations.jsonl`，只需实现 `matches(nativeCommand, instruction)`（每种指令允许的原生命令形状）、`nativeLog()`（native 记录写哪个文件）、`closeLogs()`；
   - `execute(command, args)` 里自己解析参数、自己创建原生命令并登记到 `permitted`；
   - 需要引擎事件时覆写 `damage()/created()/waiting()/afterTick()`；
   - 不接受某条命令时，默认回 `unknown command`；有自己的拒绝语义就覆写 `rejectCommand()`；
   - 若本 case 刻意复用完整对局的 order 服务（CASE1 的 `MicroCommands`），覆写 `acceptsServiceOrders()` 返回 true，否则 `RwxEngineLocalGameService` 会把通用 order 当成越权拒绝。
4. **注册**：`MicroCaseRegistry.find()` 加一行 `if`。这是唯一允许出现 case id 字符串的 Java 位置（`MicroConfig` 用它校验 id）。
5. **CLI**：`RwxCliCommands` 加命令枚举（`Domain.MICRO`），`MicroCommandProfile` 的静态 `ENTRIES` 补上分类（A/B/C）。命令名带 `rwx-micro-<n>-` 前缀只是命名约定，运行时不再靠前缀判断归属。

### 5.2 评测侧（`evaluate/micro/<CASE>/`）

1. 文档：`README.md`、`commands.md`（会打进 core jar，供本 case 的 `rwx-micro-<n>-help` 读取；文件名也兼容 `command.md`）、`START.md`、`prompt_single.md`、`METRICS.md`。`commands.md` 的一级章节必须写成 `## 1. 标题` 这种带编号的形式，help 的 `--list`/章节选取才可用。
2. `evaluate.py` + `metrics/*.py`：每个插件声明 `ID/TIER/SOURCES` 并提供 `compute(run)`，插件只读证据文件、不参与游戏；可复用 `common/` 的 replay/resim/统计工具。若本 CASE 有扣分规则，再加 `score.py`（`compute(run)` → 封顶扣分文档，复用 `common/scoring.py` 的曲线）。
3. `baseline*.py`：只用本 case 的公开命令（见 `START.md` 白名单），不读 `meta.json` 私有字段、证据或 Replay。
4. `test/smoke.py`：至少覆盖基线取胜、缩短预算 → timeout、无 Agent → error、越权命令被拒、同 task+seed 布景可复现。

### 5.3 验收

重新构建 Headless 包并实跑：`meta/gateway/result/replay` 四产物齐全，`engine/*` 证据与 `violations.jsonl` 行为符合本 case 约定，`test/smoke.py` 通过，`rwx-micro-<n>-help` 能列出章节。

## 6. 人类基线

1. `--evaluate CASE1-duel --case-args mode=human,task=...,seed=...` 启动 GUI，载入后暂停在 tick 0。
2. 人类玩家用鼠标操控 team0，解除暂停后 1× 打完（规则上不暂停/不变速）；自动录像。
3. 对局结束写 `result.json`；`evaluate.py <run目录>` 生成 `eval/metrics.json`。
4. 在 `evaluate/micro/CASE1-duel/baselines/index.json` 登记 `{"runs": {"<task>:<seed>": "<相对路径或 run 目录>"}}`。key 是 **task:seed**，每个要比较的组合都要有自己的人类 run，不能拿别的 seed 顶替。
5. 之后带 `--baseline auto` 的 run 会在报告中并排显示 human 的 T1 指标；基线只写 `eval/metrics.json.reference`，不回写引擎产物。

- 人类只有 realtime 1×；和 pause 赛道的 Agent 比较时，`outcome`/`hpLossFractions`/`ENGAGE_LAG`/`LOWHP_LAG`/`FIRE_UPTIME` 可参考（pause 有回合量化），`cadence`/`turn`/`thinkingWallMs` 不可比。realtime 与 pause 不共享榜单。
- `delta` 只用于同一 task+seed 内；`timeout` 不高于 `loss`，不要把它当胜利。
- GUI 在当前环境仍**未验证**：鼠标操控、胜负展示、暂停/变速拦截都没有实跑证据。`mode=human` 目前只把“解除暂停”当作开局，**没有强制禁用 GUI 的暂停/变速**；正式人类基线需要人工监督“1× 不暂停”，或后续补真正的锁。文档不伪造结果。

### 6.1 评分（`score` 文档）能否用于人类对局

只有 **CASE1** 与 **CASE4** 接受 `mode=human`；CASE2/3 在 `MicroConfig` 里用默认 `requiresAgentRealtime()`
拒绝 `mode=human` 和 `track=pause`，**根本没有人类对局**。

CASE1 人类局有三份差异：没有 `gateway.jsonl`（没有 CLI 请求）、没有 `violations.jsonl`、
没有 `engine/*` 之外的私有证据，其余（`meta`/`result`/`match.replay`/re-sim 快照）照常生成。
CASE4 人类局同样没有网关，但它的三个扣分项全部只消费 `meta`/`result`/`engine/tank_state.jsonl`，
所以可以完整评分。`mode=human` 的配置解析与 Kotlin 测试已通过；GUI 鼠标操控与 `Q` 暂停/恢复
尚未做真实窗口人工验收，正式采集需人工确认“1× 不暂停”。

| CASE1 扣分项 | 人类可统计 | 说明 |
|---|---|---|
| `irrelevant` 无关行为（上限 30） | **部分** | 7.5 档（违规/被拒请求）与 4.5 档（失败的 B 请求）只存在于 `gateway.jsonl`，人类恒为 0；只有 1.8 档的"引用已死单位的底层命令"能从 replay 算 |
| `mech_damage` 承受伤害（上限 60） | **可以** | 只用 `engine/events.jsonl` + 终态单位；人类局跑了 re-sim 就有 |
| `collective_idle` 集体空闲（上限 40） | **可以** | 只用 250 game-ms 快照 |

| CASE4 扣分项 | 人类可统计 | 说明 |
|---|---|---|
| `tank_loss` 虫王损失（上限 30） | **可以** | 只用终态坦克存活表 |
| `tank_idle` 虫王空闲（上限 50） | **可以** | 只用 `engine/tank_state.jsonl` 的 250 game-ms 时间线；A/B 都从原始区间切分 |
| `duration` 整体时长（上限 30） | **可以** | 只用 `result.gameMs` 与 `config` 的 T |

读法上的三个限制：

- 人类局的 `score.total` **天然偏高**：CASE1 的 `irrelevant` 两档拿不到证据，不扣分不等于没做无关操作。
- 缺证据的项记 `N/A` 且不扣分；`N/A` 是"没证据"，不是"表现满分"。
- `score` 不含胜负，必须与 `outcome` 一起读；`case1-score-v1` 与其它版本不可混榜。

CASE2/3 的扣分项都以 `gateway.jsonl` 的 A/B 请求或 `engine/*` 的原生命令为依据，没有人类模式也就没有可比数据。
需要人类参照时，CASE1 用 T1 指标（`METRICS.md` 里的 `tier=T1` 那一组），CASE4 可直接用 `tank_loss`/`tank_idle`/`duration`，
但都不要拿 `score` 与 Agent 直接混榜。

## 7. 目录

```
evaluate/micro/
  EVALUATION.md            被测 Agent 的总入口（一次测全部 CASE 时只给它这一份）
  config.json              默认 case 参数
  design.txt               最初的 CASE 设计草稿（含未实现的提案）
  common/                  Run 载入、replay 语义、resim、指标计算、报告
  test/                    Python fixture 测试（手算可核）
  CASE1-duel/              README、prompt_single、START、commands、METRICS、score_design
                           evaluate.py、score.py、metrics/、baselines/、report_html.py
  CASE2-LTE/               README、prompt_single、START、commands、METRICS、prompt.txt、score_design
                           evaluate.py、score.py、greedy.py、metrics/、test/
  CASE3-Transport/         README、prompt_single、START、command、METRICS、prompt.txt、score_design
                           evaluate.py、score.py、baselines.json、baseline/、metrics/
  CASE4-Retreat/           README、prompt_single、START、command、METRICS、prompt.txt、score_design
                           evaluate.py、score.py、baselines.json、baseline.py、metrics/
```

`report_html.py`（多局汇总）目前只有 CASE1 有；CASE3/CASE4 的命令手册文件名是单数 `command.md`，
CASE1/CASE2 是 `commands.md`，两种名字运行时都认。

同一配置反复重跑会在 `evaluate/output/micro/` 留下只差时间戳的兄弟目录；受管并行局先把材料留在各自 `<run>\micro-output\`，完成后只用 [`collect_runs.py`](collect_runs.py) 迁入规范 case 目录，用 `stamp_micro_meta.py` 写显示名并命名回放，再用 [`archive_micro_runs.py`](../tools/archive_micro_runs.py) 收敛解析产物与逐局 HTML。整理旧输出用 [`tools/cleanup_micro_output.py`](../tools/README.md)：先不带参数看计划，确认后再加 `--apply`。
