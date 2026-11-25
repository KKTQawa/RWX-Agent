# CASE4-Retreat — 战地撤退

用少量虫王（内置自定义近战单位 `bugMeleeT31`）摧毁左上角区域内的全部敌方炮塔，并用右下角维修湾恢复部队。
Agent 只会收到"清空左上角区域、善用维修湾"这个目标，**不会收到敌军配置、数量或坐标**。
考察的是**战损评估、撤退时机、维修效率、再次投入的节奏**。

本文件只讲**怎么跑、场景怎么布、材料在哪**。指标口径与材料字段见 [METRICS.md](METRICS.md)。
参与者只需要 §0 列出的三份材料（`prompt_single.md`、`START.md`、`command.md`）。

---

## 0. 交付给被测 Agent 的文件

**受管评测只交这三份**：

| 文件 | 内容 |
|---|---|
| [prompt_single.md](prompt_single.md) | 单局运行目录、连接方式、允许操作和异常边界；管理员替换 `{{RUN}}` 后作为对局指令发出 |
| [START.md](START.md) | 任务目标、最小操作顺序和参与边界 |
| [command.md](command.md) | 完整命令接口（注意文件名是单数；会打进 core jar，供 `rwx-micro-4-help` 逐节读取） |

**本目录其余文件都是管理员/开发者资料，不得出现在 Agent 可见的文件列表里**：

| 文件 | 为什么不给 |
|---|---|
| `README.md`（本文件） | 含炮塔区矩形、落点算法、间距规则、**敌方炮塔数量与类型**、迷雾实现、参数表与预览工具 |
| `config.json` | run 默认值、扣分/时长基线、地图/炮塔区/维修湾/各 type 配置；**改完重启生效**，字段见 [`../CONFIG.md`](../CONFIG.md) |
| `METRICS.md` | 含材料字段、指标阈值与扣分口径 |
| `prompt.txt` | 本 CASE 的实现提示词（历史稿；主体已从 hover tank 换成虫王，当前口径见本文件与 `config.json`） |
| `score_design.md` | 扣分规则草稿 |
| `evaluate.py`、`score.py`、`baseline.py`、`baselines.json`、`metrics/`、`test/`、`layout-comparison.svg` | 评测实现、基线、布局对比图 |

路由：

- **只测本 CASE** → 发替换过 run 的 `prompt_single.md`、`START.md`、`command.md`，本文与 `METRICS.md` 都不要出现。
- **一次测全部四个 CASE** → 每局各发该 CASE 的受管 prompt、`START.md` 与命令手册；四局互不相干，总览见 [`../EVALUATION.md`](../EVALUATION.md)。
- **受管并行 CASE4 评测** → 管理员按下节操作；不得把本 README、`METRICS.md`、评分脚本或产物目录交给 Agent。

### 0.1 受管评测操作（管理员）

1. 为每个 Agent 分配一个尚不存在的仓库外目录、task、seed 与赛道，然后启动一局（本 CASE 只接受 `track=realtime`）：

   ```powershell
   .\agent-operation\server\start-micro-evaluation-run.ps1 `
     -Run X:\game\RWX-multiagent\micro-case4-a01 `
     -Case CASE4-Retreat `
     -CaseArgs 'task=4_1_1,track=realtime'
   ```

   想看这一局的画面时加 `-Headless:$false`（旧写法 `-Window`）：run 目录、端口与材料都不变，只是多一个窗口。窗口只用于观看——命令仍由 Agent 经 `rwx.cmd` 发出，中途关掉窗口会让这一局没有 `result.json`。说明见 [PARALLEL_MICRO_EVALUATION.md](../../../agent-operation/server/PARALLEL_MICRO_EVALUATION.md#visible-client-watch-window)。
2. 启动器返回时实例只处于 lobby，尚未生成微操场景或录像。将 `prompt_single.md` 中的 `{{RUN}}` 替换为该局 `Run`，连同 `START.md`、`command.md` 发给对应 Agent。每个 Agent 只得到自己的 run，不得到端口、`CaseArgs`、日志或输出目录；由该 Agent 的一次 `rwx-micro-lobby-enter` 开始场景载入。
3. 进程自然结束后，先预览再收敛材料；只接受带 `result.json` 的唯一结果目录：

   ```powershell
   python -B .\evaluate\micro\collect_runs.py --run X:\game\RWX-multiagent\micro-case4-a01
   python -B .\evaluate\micro\collect_runs.py --run X:\game\RWX-multiagent\micro-case4-a01 --apply
   ```

4. 对移入 `evaluate/output/micro/CASE4-Retreat/` 的目录运行本 README §3 的 `evaluate.py`。完整的并行故障处理与所有权表见 [`../../../agent-operation/server/PARALLEL_MICRO_EVALUATION.md`](../../../agent-operation/server/PARALLEL_MICRO_EVALUATION.md)。

---

## 1. 场景布置

### 1.1 地图

矩形 `a × b` 格，`a`、`b` 各自取 `[65,70)` 的整数，由 seed 决定（同 seed 固定）。全草地，**无水域/岩浆/悬崖/资源点**。
20 世界单位/格。`Case4Map` 写出 stock TMX，同目录另有 `map.tmx` 供复盘。

### 1.2 炮塔区（左上 3/5）

炮塔只落在**地图左上角炮塔区**：默认宽、高各取地图的 `3/5`；密集配置下可扩到 `0.8`（65..69 格的地图对应 52..55 格），且整片炮塔离地图边界至少 3 格。

1. 在该矩形内随机取**种子中心点**（离我方出生角 ≥22 格），并要求中心到矩形边缘至少 8 格；
2. 场地的**长半轴**取"中心到矩形边缘/地图边界的最小余量（含 3 格边距）"，夹到 **8..24 格**；远程塔较多的任务会把下限抬到
   能摆下当前间距的值；
3. 场地是 **2:1 椭圆**：长轴沿 `y=-x`（与出生角方向垂直）、短轴沿 `y=x`（指向右下出生角），短半轴 = 长半轴的一半；
   落点先在单位圆盘取样（`√u × 方向`），再按 `(长半轴, 短半轴)` 缩放并旋转 45°——所以每座塔都在椭圆内，
   椭圆的包围盒只有 `0.79 × 长半轴`，整片区域不会越出 3/5 矩形。

方向规则：

- **远程塔**（`c_turret_t3_gun`、`c_turret_t2_artillery`、`c_turret_t1_artillery`）：候选方向按 80% 使用 `225° ± 35°` 的高斯分布、20% 完全随机抽样。
  在相同间距下尝试 32 组完整远程布局，按整组重心沿 225° 的投影择优，并对侧向漂移轻微扣权，
  让远程火力整体偏向**远离我方出生角**的一侧。80% 是候选方向的抽样概率，不是最终落在左上象限的比例承诺。
- **近程塔**：方向完全随机，在椭圆内填空隙。

间距：远程之间按 10 / 8 / 6 / 4 格逐档尝试、近程之间按 3 / 2.4 / 1.8 / 1.2 格逐档尝试、跨类仍 ≥ 3 格，违反就重抽。
最终坐标再叠加 ±0.35 格抖动；`meta.achievedTurretSpacingTiles` 记录实际最小间距，
`meta.achievedCentreDistanceTiles` 记录实际最小/最大中心距，`meta.region.box*` 记录炮塔区范围。

seed 影响：中心点、方向抽样、抖动与右下角折角点。同布局版本、同 `(task, seed)` 完全复现。
当前布局写入 `meta.layoutVersion=8`，右下维修湾矩阵可随配置的数量扩展。炮塔场使用 2:1 椭圆和 10/8/6/4 格间距档，`region.longRangePlacement=joint_candidates`、`longRangeLayoutTrials=32`。

离线对比覆盖全部 9 个 task、seed 0..127（1152 组）：新旧均无放置失败或格点范围/半径越界；
远程塔平均偏移由 `(-1.39,-1.42)` 改为 `(-4.09,-4.00)` 格，远程最小间距由 8.06 格提升至 10 格，
保持完整 10 格远程间距的布局占比由 95.7% 提升至 100%。这是**圆形场地时期**的布局采样结果，椭圆改动后未重采。

![旧版炮塔布景的固定 seed 5 对比](layout-comparison.svg)

### 1.3 维修湾与出生点（右下）

维修湾用右下角的矩阵布置，格点中心间距 3 格，优先填充离右下角最近的位置。8 座和 12 座使用 4 列 × 3 行，20 座扩为 5 列 × 4 行。虫王在矩阵上方，出生点可接受多座维修湾治疗，也可直接向战场移动。布局会重抽覆盖维修湾或虫王出生点的炮塔场。

### 1.4 兵力表

任务 id：`4_<type 1..3>_<level 1..3>`，`level` 是敌军数量倍率。

| type | 我方 | 维修湾 | 敌方炮塔（×level） | 迷雾 | 游戏上限 |
|---|---|---:|---|---|---:|
| 1 | 虫王 ×1 | 8 | `c_turret_t2_gun` ×3、`c_turret_t3_gun` ×1、`c_turret_t2_flame` ×2、`c_turret_t1_artillery` ×1、`c_turret_t2_artillery` ×2、`c_turret_t1_lightning` ×3 | 一次性 | 1500 s |
| 2 | 虫王 ×2 | 12 | `c_turret_t2_gun` ×3、`c_turret_t3_gun` ×2、`c_turret_t2_flame` ×3、`c_turret_t1_artillery` ×1、`c_turret_t2_artillery` ×2、`c_turret_t1_lightning` ×3、`c_turret_t2_lightning` ×1 | 一次性 | 1500 s |
| 3 | 虫王 ×3 | 20 | `c_turret_t2_gun` ×2、`c_turret_t3_gun` ×3、`c_turret_t2_flame` ×3、`c_turret_t1_artillery` ×1、`c_turret_t2_artillery` ×3、`c_turret_t1_lightning` ×4、`c_turret_t2_lightning` ×2 | 一次性 | 1500 s |

> 三个 type 的游戏上限为 **1500 s**，墙钟上限为 **1680 s**，均由 `config.json` 的 `run` 段配置。墙钟从首条 CLI 请求起计，包含开战前的操作时间。

> 表里的"×level"是每级数量再乘 level（例如 type1 level2 会把上表每种炮塔数量翻倍）。

### 1.5 单位与炮塔参数（已按源码核实）

我方 `bugMeleeT31`（虫王，`assets/units/bug_melee/bug_melee_t31.ini`，内置自定义单位，**不需要模组加载**）：
HP **6000**、**无护盾**（`shield`/`maxShield` 恒 0）、近战 **`isMelee`**、`maxAttackRange` **15** 世界单位、
单发 **170 直接伤害 + 100 范围伤害**（半径 80）、`shootDelay` 30 帧、移速 1.4/帧、`OVER_CLIFF`、
`selfRegenRate` 0.1/帧、`isBio=true`。`canAttackLandUnits=true`、`canAttackFlyingUnits=false`。

维修湾 `repairbay`：HP 1000、占地半径 30；**治疗半径 230 世界单位（11.5 格）**；每 40 帧自动挑
"范围内 HP 最低的我方单位"下达 repair 指令；基础治疗速率 0.2/帧（≈12 HP/秒），多座湾同时覆盖同一单位时会叠加；
满血目标跳过；**无需玩家命令**。2026-11-12 的 type1 虫王局（两湾覆盖）实测合计回血约 **31 HP/秒**（含自带回复）。

| 内部 ID | 语义 | HP | 射程（世界单位/格） | 冷却 | 单发伤害 |
|---|---|---:|---:|---:|---:|
| `c_turret_t2_gun` | T2 机枪 | 1100 | 185 / 9.25 | 20 帧 | 44 |
| `c_turret_t1_lightning` | T1 电击塔 | 1500 | 210 / 10.5 | 2.00 s | 150 |
| `c_turret_t2_lightning` | T2 电击塔 | 2700 | 250 / 12.5 | 1.40 s | 310 |
| `c_turret_t2_flame` | T2 喷火塔 | 1600 | 155 / 7.75 | 5 帧 | 4 范围伤害 |
| `c_turret_t1_artillery` | T1 火炮 | 1000 | 350 / 17.5 | 3.67 s | 80 范围伤害 |
| `c_turret_t3_gun` | T3 机枪 | 3900 | 320 / 16 | 13 帧 | 40 |
| `c_turret_t2_artillery` | T2 火炮 | 1800 | 460 / 23 | 1.83 s | 140 范围伤害 |

全部 `canAttackLandUnits: true`、`canAttackFlyingUnits: false`。

### 1.6 迷雾

| type | fog | 实现 |
|---|---|---|
| 1/2/3 | 一次性 | `fogEnabled=true`、`fogPeriodicMaintenanceEnabled=false`、`fogRenderActive=false`，fog 数据填 10（从未探索）；单位视野首次揭示后保持已探索，不再长回 |

敌方可见性走引擎原生判断：迷雾中的炮塔不会出现在 `unit-list --owner enemy`、`threat-list` 或 `unit-show`。
`meta.fogMode` 统一为 `1`（一次性迷雾）。2026-11-13 之前的 duration 基线是在旧迷雾（type1 无、type2/3 持续）下测得，仅供历史对照。

### 1.7 目标与判定

- 公开目标只有一句："摧毁左上角区域内全部敌人，并妥善利用维修湾"。`state` 只给通用目标描述与 `goal.reached`，
  **不给**剩余敌军数量/类型/坐标。
- `success`：本局全部炮塔被摧毁。`defeat`：我方虫王全部阵亡。`timeout`：预算耗尽。`error`：异常。
- 敌方配置（`meta.turrets`）是评测方私有数据，不得经任何 Agent 可访问接口泄露。

### 1.8 改场景与离线预览

场景只由两处代码生成：`Case4Map`（地图尺寸/地面）与 `Case4Retreat`（区域、落点、出生点）。改完不必启动对局即可出图。

| 想改 | 位置 |
|---|---|
| 地图边长 | `Case4Map.MIN_SIZE` / `MAX_SIZE`（默认 `[65,70)`，seed 决定具体值）；想固定尺寸就直接改 `width(seed)`/`height(seed)`。`TILE=20` 是格与世界单位的换算 |
| 任务单位类型 | `config.json` 的 `map.subject.type`（默认 `bugMeleeT31`）；`Case4Retreat.configure` 写入 `meta.tankType`，`layout()`/`spec` 的坦克表都从它取。换成未登记的自定义单位时，`RwxMapEntityCodes` 里没有编码就不会出现在 `--unit-land` 图上 |
| 炮塔区矩形 | `Case4Retreat.REGION_FRACTION`（3/5）、`FIELD_MARGIN`（离边界 3 格） |
| 场地椭圆 | 长半轴 `RADIUS_MIN` / `RADIUS_MAX`（8..18）与 `regionRadius`、`minimumRadius`；比例 `ELLIPSE_RATIO`（0.5）、朝向 `ELLIPSE_AXIS_DEGREES`（-45°，即长轴在 `y=-x`） |
| 种子中心 | `pickCentre`（离矩形边与出生角的约束）、`BASE_CLEARANCE` |
| 远程偏置 | `LONG_RANGE_BIAS_DEGREES` / `LONG_RANGE_BIAS_SPREAD`、`LONG_RANGE_RANDOM_SHARE`、`LONG_RANGE_LAYOUT_TRIALS`、`placeLongRangeGroup` |
| 间距与放宽 | `SPACING_LONG` / `SPACING_SHORT` / `SPACING_CROSS`、`SPACING_FLOOR` / `RELAX_STEPS`、`fits` |
| 落点抽样 | `placeOne`、`drawOne`（方向抽样后按椭圆边界 `× √u` 取距、`JITTER_TILES` 抖动） |
| 数量/类型/迷雾/时限 | `spec(task)`；维修湾与坦克出生在 `layout()` 的 `bays` / `tanks` 段 |

离线预览（不启动游戏、不读资源，输出 PNG + `layout.json` + `map.tmx`）：

```powershell
.\gradlew.bat :core:previewCase4 -Ptask=4_1_1 "-Pseed=1,2,3,5,8"
.\gradlew.bat :core:previewCase4 -Ptask=4_3_2 -Pseed=5 -Pscale=14 -Pranges=1
```

产物在 `agent-tmp/case4-preview/<task>-s<seed>/`：`scene.png` 是该 seed 的俯视图（红=远程塔、蓝=近程塔、绿=维修湾、紫=坦克；
虚线椭圆=场地（2:1，长轴在 y=-x）、橙框=左上 3/5、箭头=225° 远程偏置），`layout.json` 与 `meta.json` 里那份落点数据同源。
多个 seed 会额外生成 `compare-<task>.png` 拼图；`-Pscale` 是像素/格（默认 9），`-Pranges=1` 叠加每座塔的射程圈（看覆盖是否重叠）。

预览直接调用 `Case4Retreat.layout(config, null)`——该方法不读 `GameEngine`，所以与真机布景逐格一致。
它只验证"摆在哪"，不验证贴图、迷雾与寻路；定稿前仍应 `--window` 跑一局确认。
改了落点逻辑后把 `meta.layoutVersion` 加一：同 seed 的旧落点与新落点不是同一场景，不能混比。

---

## 2. 快速开始

从仓库根目录：

```powershell
# 无头
.\gradlew.bat :desktop:run '--args=--headless --no-steam --evaluate CASE4-Retreat --case-args task=4_1_1,track=realtime --data-dir=agent-operation/tmp/retreat-a --cli-port-file=agent-operation/tmp/retreat-a/port'

# 带窗口观看
.\gradlew.bat :desktop:run '--args=--window --no-steam --evaluate CASE4-Retreat --case-args task=4_1_1,track=realtime --data-dir=agent-operation/tmp/retreat-a --cli-port-file=agent-operation/tmp/retreat-a/port'
```

启动成功：

```text
RWX_MICRO_RUN <run目录>
RWX_MICRO_READY case=CASE4-Retreat phase=briefing tick=0
```

受管并行局会再加 `--micro-lobby`：进程先停在 lobby（只有 `rwx-micro-lobby-status` / `rwx-micro-lobby-enter` / `rwx-ping`），
由 Agent 自己发一次 `rwx-micro-lobby-enter` 才出现上面的 `RWX_MICRO_RUN` 与 `RWX_MICRO_READY`。

本 CASE 接受 `mode=agent,track=realtime` 与 `mode=human`；`track=pause`、`turnTicks`、`turnSeconds`、
`enemyDelaySeconds` 仍会被拒绝。人类模式的命令行与评分口径见 §6.1。

### 连接 CLI

```powershell
python agent-operation/tools/rwx-cli.py --port-file agent-operation/tmp/retreat-a/port --stdio
```

建议先在 briefing 阶段观察，再发 `rwx-micro-4-begin` 开始（1× 连续运行，无 pause/step/speed）。
命令面见 [command.md](command.md)。

---

## 3. 完整评测流程

**① 跑局** — 产物落在 `evaluate/output/micro/CASE4-Retreat/<case>_<task>_realtime_s<seed>_<时间戳>/`。收录后用 `evaluate/tools/stamp_micro_meta.py` 声明参与者，目录会改名成 display name（`<case> <task> realtime · <时间> · <模型> - <工具>` 或 `baseline` / `human`，末尾 `s<seed>`）。

**② 观察与操作** — 观察用 `rwx-micro-4-state` + 只读的 `rwx-game-map-show` / `unit-list` / `unit-show` / `threat-list` / `map-path`；
操作用 `order-move` / `order-attack` / `order-attack-move` / `order-stop`（只允许本局虫王）。

**③ 离线评测**

```powershell
python evaluate/micro/CASE4-Retreat/evaluate.py evaluate/output/micro/CASE4-Retreat/<run目录>
# 传父目录会遍历其中所有含 meta.json 的子目录；加 --json 打印完整文档
```

输出 `eval/metrics.json`、`report.txt`、`report.html`。本 CASE **不做 re-sim**：
战斗/维修证据来自 live 引擎记录，`match.replay` 只用于核对底层命令。

**④ 看结果**

| 文件 | 看什么 |
|---|---|
| `eval/metrics.json` | 9 个指标 + 顶层 `score`（扣分，`case4-score-v1`）+ `diagnostics` + `evidence` |
| `engine/turret_damage.jsonl` | 每座塔每次受伤的真实序列（含攻击者） |
| `engine/turret_destroyed.jsonl` | 摧毁顺序 + 当时我方全员 HP 快照 |
| `engine/repair_sessions.jsonl` | 正式维修会话（>5 游戏秒且实际回血） |
| `engine/tank_state.jsonl` | 250 game-ms 的坦克位置/HP/order/所在维修湾（“虫王空闲”扣分的唯一来源） |

无参数运行会打印摘要：`task seed: outcome (reason) game=…ms turrets=…/… tankHits=… hpLost=… tanksLost=… repairs=… healed=… violations=… score=… (deduction …; tank_loss=… tank_idle=… duration=…)`。

扣分口径（三项封顶扣分、阈值、R、时长横坐标）见 [METRICS.md §13](METRICS.md)；分数与 `outcome`/指标分开读。

**⑤ 冒烟/回归**（需要先构建 Headless 包：`.\gradlew.bat :desktop:headlessArchive`）

```powershell
python -B evaluate/micro/CASE4-Retreat/test/smoke.py --dist desktop/build/headless
# --heavy 追加有迷雾的 type 2/3；--tmp 改临时目录；--out 改运行产物父目录
# （默认 agent-tmp/retreat-smoke-output，不会写 evaluate/output）；--java 指定解释器
```

---

## 4. 机制

### 4.1 生命周期

- 布景完成停在 tick 0。Agent 通过 `rwx-micro-4-begin` 开战，游戏时钟随之启动。墙钟预算从首条请求起计。
- begin 后 1× 连续运行，没有 pause/step/speed。
- 结束时写 `lifecycle end`（如 `all-turrets-destroyed`）+ `result.json`，之后不再接受操作。

### 4.2 命令类别

| 类 | 命令 |
|---|---|
| A | `rwx-micro-4-state`、`rwx-game-map-show`、`rwx-game-unit-list`、`rwx-game-unit-show`、`rwx-game-threat-list`、`rwx-game-map-path` |
| B | `rwx-game-order-move`、`-attack`、`-attack-move`、`-stop` |
| C | `rwx-micro-4-begin`、`-help`、`rwx-ping` |

**不开放**建造、生产、升级、回收、任意技能、全局自动化或 pause/step/speed。B 类命令逐条经 session 授权后生成原生命令。

### 4.3 维修

- 维修湾**自动**发起治疗（每 40 帧挑范围内 HP 最低的我方单位），不需要 `repair` 命令。
- 治疗只加 HP；本局虫王没有护盾，Agent/基线只用 HP 判断战损，评分也不读护盾字段。
- 只有"进入范围**并且实际回血**且持续 > 5 游戏秒"的区间才会写成正式会话。

### 4.4 违规

不在白名单的命令、越权原生命令一律执行前拒绝：不进 replay、不改状态、单独写 `violations.jsonl`。

---

## 5. 材料与指标

一局跑完能拿到这些材料：`meta` / `gateway` / `result` / `match.replay`+`replay/` / `delivery.jsonl` /
`engine/turret_damage.jsonl` / `engine/unit_damage.jsonl` / `engine/turret_destroyed.jsonl` /
`engine/repair_sessions.jsonl` / `engine/tank_state.jsonl` / `violations.jsonl`（另有 `eval/` 输出）。
每份材料的字段、精度与坑，以及 9 个指标的完整定义、扣分规则（§13），全部在 **[METRICS.md](METRICS.md)**。

| 想知道 | 看 |
|---|---|
| 清完了没有、多快 | `outcome.goalReachedGameMs`、`turret_progress.destroyOrder` |
| 每次击杀后还剩多少血 | `post_kill_snapshots.totalHp` |
| 挨了多少打、谁打的 | `battle_damage.tanks[].attackers` |
| 撤得及时吗 | `repair_effectiveness.hitToRetreat` |
| 修完多久回战场 | `repair_effectiveness.repairEndToReengage` |
| 治疗到底有没有效 | `repair_sessions.totalHealed` + `repairCoverage` |
| Agent 观察是否滞后 | `ab_timing` + `gateway.jsonl` |
| 这次扣了多少分 | `eval/metrics.json.score.total` / `score.items` |

---

## 6. 基线

> [`config.json`](config.json) 的 `evaluation.duration` 是评分采用的基线，`baselines.json` 同步实测值。CASE4 的评测启动和基线重跑默认使用 seed 1331。

```powershell
python evaluate/micro/CASE4-Retreat/baseline.py `
  --port-file agent-operation/tmp/retreat-a/port `
  --meta-file evaluate/output/micro/CASE4-Retreat/<run>/meta.json
```

同一个脚本通过当前对局的私有 `meta.json` 读取虫王出生点和炮塔坐标，通过击毁事件移除已死亡的目标。它会自动开始对局，每 0.5 秒检查各只虫王。虫王会攻击最近的剩余炮塔，对未发现的塔下达前往坐标的攻击移动指令。血量低于 65% 时撤回维修，恢复到至少 99.9% 后再次接战。所有操作通过公开的 `rwx-game-order-*` 提交。

脚本读取引擎生成的 `result.json`，仅在 `outcome=success` 且炮塔清零时返回退出码 0。
`test/smoke.py --heavy` 读取 `config.json` 的默认 seed，并行验证 `4_1_1`、`4_2_1`、`4_3_1` 的实时局。
各场实测时长和对局记录见 [config.json](config.json) 的 `evaluation.duration` 与 `evaluation.baselines`。

### 6.1 人类基线（`mode=human`）

CASE4 与 CASE1 一样接受 GUI 人类局：

```powershell
.\gradlew.bat :desktop:run '--args=--no-steam --evaluate CASE4-Retreat --case-args mode=human,task=4_1_1'
```

1. 启动后载入同一布景并暂停在 tick 0；鼠标操控 team0，按 `Q`（或解除暂停）以 1× 开局。
   进入 human 局时镜头会居中到我方单位（修复先前相机停在左上角造成的黑屏/点不到单位）。
2. 人类只有 realtime 1×；没有 `track=pause`、没有回合、没有变速锁。正式采集需人工监督“不暂停、不变速”。
3. 结束后写 `result.json` 与 `engine/tank_state.jsonl`；`python evaluate/micro/CASE4-Retreat/evaluate.py <run目录>` 生成 `eval/metrics.json`。
4. 与 CASE1 的差异：人类局没有 `gateway.jsonl`（没有 CLI 请求），但 CASE4 的三个扣分项
   `tank_loss` / `tank_idle` / `duration` **全部是引擎侧证据**，因此仍可完整评分；`irrelevant` 不参与 CASE4 评分。
5. `tank_idle` 的 A 段仍然按“湾内全员满血”切分；人类在湾内等队友回满的时间会如实计入 A，不会因为无网关而丢失。

**当前验证边界**：`mode=human` 的配置解析与 Kotlin 测试已通过；GUI 鼠标操控、`Q` 暂停/恢复和结算展示
还没有在真实窗口里做人工验收（与 CASE1 相同的已知限制）。正式人类基线需要人工确认“1× 不暂停”。

人类 run 不能与 Agent 的 `score.total` 直接混榜；同 task+seed 可比较 `tank_loss`、`tank_idle`、`duration` 与 `outcome`。

---

## 7. 复现与清理

- 同 `task+seed` 布景确定：地图、炮塔位置、维修湾、坦克出生点与朝向一致。
- 反复练习会在 `evaluate/output/micro/` 留下只差时间戳的兄弟目录。受管并行局先保留在各自 `<run>\micro-output\`，完成后只用 [`../collect_runs.py`](../collect_runs.py) 迁入规范 case 目录；它拒绝不完整、歧义或重名材料，不会从根 `replays/` 寻找录像。
- 整理旧输出用 [`tools/cleanup_micro_output.py`](../../tools/README.md)：先不带参数看计划，确认后加 `--apply`。
- 临时文件放 `agent-tmp/`，端口文件放 `agent-operation/tmp/`。

---

## 8. 目录

```
evaluate/micro/CASE4-Retreat/
  README.md            本文件：运行、场景、流程、机制
  METRICS.md           材料清单 + 指标定义 + 阈值 + 已知问题
  prompt_single.md     受管单局 prompt（管理员替换 {{RUN}} 后发放）
  START.md             参与者说明
  command.md           命令手册（会打进 core jar）
  prompt.txt           CASE 实现提示词（不是参与材料）
  evaluate.py          离线评测入口
  score.py             扣分评分（case4-score-v1，写进 metrics.json 的 score）
  baselines.json       整体时长的实测基线 T 与空闲基线 w/T
  baseline.py          通用基线（type 1~3 × level 1~3）
  metrics/             9 个指标插件（outcome/turret_progress/battle_damage/…）
  test/                smoke.py 端到端冒烟、test_score.py 评分单测
```

场景代码与预览工具不在本目录：

```
core/src/main/java/com/corrodinggames/rts/game/ai/custom/micro/case4/
  Case4Map.java        地图尺寸与地面
  Case4Retreat.java    区域/落点/出生点/迷雾/单位表
core/src/test/kotlin/com/corrodinggames/rts/game/ai/custom/micro/
  Case4ScenePreview.kt :core:previewCase4 的实现（离线出图）
```
