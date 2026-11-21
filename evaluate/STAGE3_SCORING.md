# 第三阶段：延迟严重程度评估（`stage3-score-v2`）

本文件说明 [`score_design.md`](score_design.md#第三阶段) 第三阶段在代码里的落地口径。四项分别是：

| 族 | 含义 | 扣分上限 |
|---|---|---|
| `STAGE3_AMBUSH` | 空闲移动单位被打 | 50 |
| `STAGE3_BARRAGE` | 建筑被炮兵持续攻击 | 40 |
| `STAGE3_GRINDER` | 危险区里仍有建造者死亡（绞肉机 v2） | 20 |
| `STAGE3_FUNDS` | 资金长期空余（资金 v2，读 `economy.log`） | 30 |

四项独立扣分、各自封顶后相加；`总分 = max(0, 100 − Σ扣分)`。所有数值参数只在 [`config.json`](config.json) 的 `stage3.parameters` 里维护，代码通过 [`config.js`](config.js) 读取，**不要在脚本里另写默认值**。设计尚未确定或没有数据标定的项在 `config.json` 里带 `"status": "provisional"`。

第三阶段不再只是单列成绩：`total-v2 = stage1-v2 − (100 − stage3) × (1 − k)`（`k=0.5`，裁到 `[0,100]`）由 [`score_match_v2.js`](score_match_v2.js) 合成总分；仍是 provisional，理由写在分数的 `calibration.reasons` 里。

## 材料与采集

用当前版本 `--evaluate <档位>` 跑，或用当前 Headless 发行包重放 Replay。`telemetry.jsonl` 除原有行外需要：

| 行 | 内容 |
|---|---|
| `stage3_meta` | 炮兵攻击间隔、危险区半径与建区参数，以及本次采集用的 `idleFireMs`（空闲判定的开火冷却窗口） |
| `stage3_ambush` | 空闲移动单位每次受击及缓冲关闭；建造者执行 build/repair 仍视为空闲，运输中不计 |
| `stage3_barrage` | 建筑遭自行火炮、重型火炮、火炮机甲命中的缓冲与关闭原因 |
| `stage3_zone` | 危险区 create/refresh/check/clear/drop 状态机及每次 E/F/ratio |
| `stage3_builder_death` | 四类建造者的完整漏斗：伤害击杀、运输、覆盖区、age、是否可计分 |

伤害通知同时记录实际 `hpLoss` 与 `shieldLoss`，均在伤害结算前后取真值，过量伤害不计。HP/盾上限和累计造价在缓冲创建时冻结。炮兵 `K` 从游戏单位数据的最大攻击间隔读取，默认原版值为 4 秒，`K_tol = 1.3K = 5.2 秒`。

**空闲时长（`idleMs`）**：采集侧**完全保留原版 1 秒闸门**（`-Drwx.evaluate.stage3.idleGateMs`，默认 1000），缓冲的创建与关闭、`T`、`N`、`D_hp` 全部不变；只在每条 `stage3_ambush` 命中与关闭行上多记一个 `idleMs`＝这个单位**连续空闲了多久**（每秒扫一次我方单位，记下进入空闲的时刻；刚进入空闲记 0）。`stage3_meta` 同时写 `idleGateMs` 与 `idleScanMs`。

评分侧用 `stage3.v21.parameters.ambushV3.minIdleMs`（默认 4000，初值 0）过滤：`idleMs < minIdleMs` 的命中不计入该事件，计数进诊断 `droppedShortIdle`。含义是“单位才刚刚空闲、或者刚开过火（开火会把它踢出空闲），仍算在反应中”，所以比原来的 1 秒闸门严格，但采集侧零行为变化。

旧遥测没有 `idleMs` 字段，沿用采集时的结果（1 s 闸门、无最短空闲门槛）。

资金项不吃 `telemetry.jsonl`，它读 `economy.log`（每秒一行，`funds` 与收入字段；`incomeFieldPerSecond=1.5625` 把 0.64 秒一格的收入字段换算成每秒资金）。`score_stage_3.js` 默认在 `prepared/`、`resim/` 或 `stage_3/` 里找它，也可以用 `--economy` 指定。**触及对局开始或对局结束的资金区间不计分**：左端点落在第 0 秒的记 `IGNORED_OPENING`，右端点落在最后一个样本的记 `IGNORED_TRAILING`，两端都落的记 `IGNORED_WHOLE_MATCH`。开局押金本身不是可自由支配的囤积，末尾区间只是窗口截断，两者都写进 `excluded` 与 `diagnostics.ignoredEdges`，不进 `items`。第二阶段（`stage2-v2`，旧对照）仍按原样计这两类区间。

危险区严格按设计顺序在同帧批处理：死亡台账 → 刷新已有区 → 4 秒节拍检查 → 按 id 聚类建区 → 判定建造者死亡。区域造价使用游戏真值，不受视野限制；所有阈值与每次判定的 E/F 都写进原始材料。

## 扣分公式

公共项：`E = D_hp + α·D_sh`，`H = HP_max + α·Shield_max`，`L = 1`（致死/摧毁），否则 `β·min(1, E/H)`；`W = W_min + (1 − W_min)·min(1, ln N / ln N_sat)`；`w = clip(sqrt(cost/C_w), w_lo, w_hi)`；`S = Σs / clip(G/G_ref, r_lo, r_hi)`；`扣分 = P_max·(1 − e^{−S/S0})`。

- **偷袭**：`s = w·L·W·Tf`，`Tf = 1 + γ·min(1, max(0, (T − T0)/T_span))`。`T` 是缓冲从首次 idle 受击到关闭的时长，`T0` 以下不加成。
- **炮击**：`s = w·L·W`，没有时长项（炮兵间隔已经体现在 `N` 与缓冲区里）。
- **绞肉机**：同一有效区内以第一次死亡为锚点，`T_merge` 内的死亡合并成一个事件；`B = min(1, Σw / W_full)`，`age = t_first − t_birth − Δ0`，`L = L_min + (1 − L_min)·min(1, age / T_stale)`，`P = SingleMax·L·B`，`扣分 = min(Cap, ΣP)`。不做时长归一。
- **资金**：先对每秒资金做 3 秒中值平滑；阈值 `θ = K × 近 30 秒平均收入率`。资金首次达到 `θ` 开始计时，累计囤积时长 `D` 在区间内取最大值 `d_k`。资金回落到 `θ` 以下、或一次释放超过 `releaseShare`（默认 80%）时区间结束。左端点为第 0 秒或右端点为最后一个样本的区间整段不计分（见上节），其余区间照算。花费按 `s > max(spendFloor, spendShare·M)` 才计入（`M` 为区间内资金最大值），并按 `s/M` 折减 `D`：≤50% 乘 `rho1`，50%~80% 乘 `rho2`。区间结算 `f(d) = (e^{λu} − 1)/(e^{λ} − 1)`，`u = (d − d0)/(d1 − d0)`，`d ≤ d0` 为 0、`d ≥ d1` 为 1；`扣分 = min(Cap, Σ eventMax·f(d_k))`。设计里的动态标定（`K`、`d0/d1`、`κ`、向先验收缩）还没有参考池，`config.json` 把它们标成 provisional 或 `disabled`。

## `stage3-score-v2.1-v3`：偷袭 v3、偷家 v3、绞肉机 v2、资金 v3

`score_design.md` 的 v2.1 把第三阶段的偷袭、偷家、资金三项换掉，绞肉机沿用 v2。
当前 v3 的核心变化是**以受袭事件次数为主**：伤害只做严重度，不再拿全场暴露量做分母。

```text
E = D_hp + α·D_sh
H = HP_max + α·Shield_max

偷袭 v3（我方陆地移动单位，攻击者为敌方移动单位）：
  M1 = Σ w（所有准入事件，含 T<T0 的快速反应）
  准入 = E/H ≥ ε 或 died
  u  = clip((ln(1+T) − ln(1+T0)) / (ln(1+T_hi) − ln(1+T0)), 0, 1)
  u' = min(1, u + δ·died)
  sev = 1（died）或 clip(E/H, s_lo, 1)
  s  = w·u'·sev
  R1 = Σs / (M1 + W_floor)             扣分1 = 50·(1 − exp(−R1 / R0₁))

偷家 v3（我方建筑，炮兵缓冲）：
  M2 = Σ w（N≥2 或摧毁的准入事件，含短暂炮击）
  准入 = (N≥2 或 destroyed) 且 (E/H ≥ ε_b 或 destroyed)
  T_j = 最后一发时刻 − 第一发时刻（摧毁时取摧毁时刻）
  u' / sev / s 同上，δ 作用于 destroyed
  R2 = Σs / (M2 + W_floor_b)           扣分2 = 40·(1 − exp(−R2 / R0₂))

stage3-v2.1 = max(0, 100 − 扣分1 − 扣分2 − 绞肉机 − 资金 v3)
total-v2.1  = clip(stage1-v2 × 0.4 + stage3-v2.1 × 0.6, 0, 100)
```

关键实现口径：

- 偷袭记录仍从 `stage3_ambush` 的 idle 缓冲重建；逐条剔除 `attacker.building=true`，
  且只保留**陆地**受害者（v2 的“非陆地保留在记录里”不再适用于 v3）。
- `T<T0` 的事件**不丢**：`u=0`，但仍按 `w` 进 M1，作为“Agent 本可以反应的机会”。
  `died` 事件不论 T、E/H 多少都准入；一击秒杀由 `δ` 兜底。
- 偷家 T_j 必须取**最后一发炮弹**，不能取缓冲到期时刻；因此 v3 直接读 `prepared/telemetry.jsonl`
  的 `stage3_barrage` hit/close，而不复用 `stage_3/events.jsonl` 的 `t_end`（后者对 `EXPIRED` 是到期时刻）。
- v2 的伤害占比 `r1/r2` 仍作为 `components.stage3.legacy` 旁路输出，**不计分**；它沿用 v3 的陆地受害者集合，是近似对照，检索旧 v2 精确值时以历史 `_v21-summary` 为准。

资金 v3 按游戏时长把评分窗口切成 `[0,1/4)`、`[1/4,3/4)`、`[3/4,1]` 三段：

```text
Ki = 该段总花费 / 该段总收入          # 每段的收入 = 段初资金 + 段内收入
K  = 0.4·K1 + 0.4·K2 + 0.2·K3
资金 v3 扣分 = (1 − K)^exponent × SingleMax    # exponent 默认 0.5，SingleMax = 30
```

金额都从 `economy.log` 的每秒 `funds(+income)` 推导，不读订单：

- 段收入/可用 = 段初资金 + `Σ 该段每秒收入字段 × incomeFieldPerSecond`（`1.5625`，与 v2 同一换算）。第一段的段初资金是开局 4000，第二、三段的段初资金是上一段结束时的余额；
- 段花费 = 段初资金 + 段内现金收入 − 段尾资金。这是段内资金余额恒等式，退款/出售会抵消一部分花费，所以它低于或等于实际下单金额；`funds_v3.js` 同时输出 `negativeDeltaSpend` 与 `positivePerSecondSpend` 两个交叉核对值。

因此每段 `Ki = 1 − 段尾资金 / 段可用`，天然在 [0,1]；整窗口 `总花费 / (开局资金 + 总收入) = 1 − 结束资金 / 总可用`。`score_v21.json` 的 `windows[]` 同时给出每段 `startFunds/income/available/spent/rawRatio/k`，便于核对。

参数在 `config.json`：

- `stage3.v21.parameters.ambushV3`：`alpha=0.4`、`epsilon=0.05`、`T0=3`、`T_hi=21.122`、`delta=0.2`、`s_lo=0.3`、`C_w=1000`、`w_lo=0.4`、`w_hi=sqrt(7)`、`W_floor=3`、`R0=0.253601`、`P_max=50`；
- `stage3.v21.parameters.barrageV3`：`alpha=0.4`、`epsilon=0.03`、`T0=8`、`T_hi=23.152`、`delta=0.2`、`s_lo=0.3`、`C_w=1000`、`w_lo=0.5`、`w_hi=sqrt(8)`、`W_floor=2`、`R0=0.237905`、`P_max=40`；
- 旧 `stage3.v21.parameters.ambush/barrage` 保留为 v2 诊断参数，不再参与 v3 计分；
- `total.v2_1.parameters`：`stage1Weight=0.4`、`stage3Weight=0.6`、`clipMin=0`、`clipMax=100`。

标定（26 局当前批）：

- `T_hi` 取每局准入事件 T 的 P90，再取 26 局的中位数：偷袭 **21.122 s**、偷家 **23.152 s**；
- `R0` 取 26 局 R 的中位数：偷袭 **0.253601**、偷家 **0.237905**；
- 饱和（T≥T_hi）占准入事件：偷袭 **219/1191（18.4%）**、偷家 **41/238（17.2%）**；
- 偷袭准入 **1191/1439**（命中 6517/6900），偷家准入 **238/346**（命中 1829/1943，摧毁 149）；
  事件少（偷袭 <5、偷家 <3）的局在报告里标 `lowConfidence`。

`R0` 用中位数而不是 Q1：v3 的 R 本身已经是“价值加权的失职占比”，中位数对应 P_max 的 63%；
再用 Q1 会把多数局推到接近封顶，反而失去区分度。

落地文件：`evaluate/score_stage_3_v21.js`（纯 Stage3-v2.1 计算，读 `prepared/telemetry.jsonl` + `stage_3/score.json` + `economy.log`；v3 的偷袭/偷家都从 telemetry 重建，偷家不能用 `events.jsonl` 的到期时刻）与 `evaluate/score_match_v21.js`（组合 Stage1-v2 与 Stage3-v2.1，写 `score_v21.json`/`score_v21.txt`）。`evaluate_corpus_v2.js` 在 `total-v2` 之后顺带生成；已有对局可整批补算：

```powershell
node evaluate/tools/add_v21_scores.js              # 当前批 + 归档，写 _v21-summary.*
node evaluate/tools/add_v21_scores.js --current-only
```

v2.1 只读 v2 已有材料，不改 `stage_3/score.json`、`stage_3/events.jsonl` 或 `score_v2.json`；归档局的 Stage1/Stage3 仍是历史批次参数，v2 与 v2.1 两列分别用各自的总分公式重算后比较。

## 离线流程

```powershell
$m = "evaluate/output/<对局名>"
node evaluate/evaluate_stage_3.js "$m/prepared/telemetry.jsonl" --out "$m/stage_3"
node evaluate/score_stage_3.js "$m/stage_3" --cut-ms <评分窗口 ms>
```

第一条命令只做材料门槛、缓冲重建和漏斗整理；第二条命令才计分。`--cut-ms` 与预处理窗口一致，避免把窗口外的资金区间算进来。输出：

| 文件 | 用途 |
|---|---|
| `stage_3/events.jsonl` | 三类规范事件及排除原因 |
| `stage_3/zones.jsonl` | 危险区完整状态机，供人工复核和重新标定 |
| `stage_3/summary.json` | 覆盖、漏斗、区寿命和输入身份 |
| `stage_3/events.txt` | 简明事件时间线 |
| `stage_3/score.json` | 四项参数、逐项中间量、诊断和总分 |
| `stage_3/score.txt` | 人读摘要 |
| `stage_3/timeline.csv` | 可排序的事件表（含资金区间） |

旧 telemetry 没有 `stage3_meta` 时入口会拒绝，不能把"没有采集"解释成"零事件"；窗口截断且没有关闭行的缓冲保留为 `INCOMPLETE_INTERVAL`，不扣分。没有 `economy.log` 时资金项记 `ECONOMY_EVIDENCE_MISSING`、`evidenceComplete=false`，这时不会出 `score_v2.json`。

## 归档局的加速重放（resim）

`evaluate/output/_archive/<old_v1.0|old_v1.1>/` 里录制时还没采集第三阶段证据的局，只能重放补：

```powershell
$m = "evaluate/output/_archive/old_v1.1/<对局名>"
python evaluate/utils/evaluate_replay.py "replays/<对局名>.replay" --team <队伍> `
  --commands "$m/commands-<对局名>.txt" --out "agent-tmp/<slug>"
Copy-Item "agent-tmp/<slug>/engine/match-*/telemetry.jsonl" "$m/resim/telemetry.jsonl"
Copy-Item "agent-tmp/<slug>/engine/match-*/economy.log"     "$m/resim/economy.log"
```

`resim/playback.json` 记录回放名与 SHA-256、队伍、`checksumWarnings`、引擎提交和耗时，是这份证据的来源凭证。规则：

- 重放窗口止于 `replay_end`（回放里没有 `match_result`），不做 `preprocess` 的尾部裁剪；窗口里的结局由 `evaluate_corpus_v2.js` 用 `planWindow` 重新判定。
- `checksumWarnings > 0` 表示重放与录制分叉，这份材料不进入 v2 总分（`replay_desync:<N>`）。当前语料里 4 局是这样，另有 1 局因回放未完成、材料缺失被忽略。
- 录制完整、重放零分叉的局才写 `evaluation_v2.json`，并标注 `evidenceSource=faithful-resim`。

## S0 标定与全局参数

第三阶段有四个由语料自动标定的全局参数：偷袭/炮击的 `S0`，以及资金 v2 的 `K`、`d0`、`d1`。调参池由 `config.json` 的 `policy.tuningPool` 定义，脚本不另立规则：

- 只取 `evaluate/output` 根目录（current 批）的对局；`_archive` 永不进池。
- 评分窗口严格大于 `minDurationExclusiveSeconds`，Stage-3 证据完整，重放无分叉（live 证据天然忠实）。
- `meta.json.evaluation.disposition` 在 `excludeDisposition` 里的局（当前是 `worthless`）**退出调参池，但照常评分与展示**；`requireOutcome` 为空时不按胜负筛。
- `S = Σs / clip(G/G_ref, ·)` 与 `S0` 无关（`S0` 只进饱和函数），所以中位数可以随时从已算好的 `stage_3/score.json` 复算，不需要重跑阶段。

自动标定规则（`score_design.md`）：

| 参数 | 估计 | 裁剪 |
|---|---|---|
| `ambush.S0` / `barrage.S0` | 池内 `S` 的中位数 | — |
| `funds.K` | `median_m Q0.9(r_m)`，`r_m(t) = 平滑资金 / 近 30 秒收入率` | `[20,45]` |
| `funds.d0` | 用该 `K` 重算参考池区间后的 `Q0.5(d_k)` | `[8,25]` |
| `funds.d1` | 同一批区间的 `Q0.95(d_k)` | `[90,180]` |

- 池内区间少于 30 个时资金三项退回先验（`K=30/d0=15/d1=120`），与设计一致；`worthless` 局不提供区间。
- 资金最小花费的 `κ` 在设计中未给值，仍用 `spendFloor=800` 先验；`λ` 也仍是先验 1。
- 设计写的是"同分层参考对局（剔除本局）"，但同一节又要求"每个评测批次冻结参数快照"；这里取**批次级全量冻结**（不剔除本局），与顺序重跑后的最终统一遍一致。

当前批的日常入口是 [`tools/calibrate_stage3.js`](tools/README.md)：

```powershell
node evaluate/tools/calibrate_stage3.js            # 只报告
node evaluate/tools/calibrate_stage3.js --write    # 写回 config.json 的 S0 / 资金参数 / stage3.calibration
```

- 样本少于 `--min`（默认 3）时保持当前 `S0`，不拿一两局的中位数当基线。
- `--write` 同时更新 `stage3.calibration.current`（样本数、胜负分布、`minDurationExclusiveSeconds`、`excludedDisposition` 与 `funds` 标定明细），报告里的 `calibration.baseline` 直接读它。
- 归档语料仍用 [`tools/stage3_baseline.js`](tools/README.md)：它扫 `_archive`、写 `<局>/stage_3/score.calibrated.*` 与聚合，`--s0` 可冻结一套旧基线。

顺序重跑整批用 [`tools/run_batch_v2.js`](tools/README.md)：按对局创建时间逐局重评 → 每局后重标定 `S0` 与资金参数（写 config）→ 最后用收敛后的参数统一补跑一遍，保证榜单同基线。`meta.json` 只读，驱动会在前后比对哈希。

## 给新一批局打分

整批跑（含归档局）用 [`tools/evaluate_corpus_v2.js`](tools/README.md)：

```powershell
node evaluate/tools/evaluate_corpus_v2.js                 # 扫 evaluate/output 全树
node evaluate/tools/evaluate_corpus_v2.js --current       # 只跑当前批
node evaluate/tools/evaluate_corpus_v2.js --match "<对局目录>"
```

它按"live 有 `stage3_meta` 就用 live，否则要求 resim 零分叉"选证据，跑 Stage1-v2 / Stage3 / `total-v2`，写 `<局>/evaluation_v2.json`，并把结论汇总到 `evaluate/output/_v2-summary.json`（含忽略原因与调参池的 `S` 中位数、入池/出池明细）。`evaluate/output/` 不进版本库，公开结论由 `evaluate/tools/build_web_results_v2.js` 写进 `web/resource/results.json`。

## 已知限制

- `S0` 取自当前批 `S` 的中位数（task147：22 局，worthless 4 局出池）；`W_min`、`N_sat`、`G_ref` 等仍是设计先验，没有参考池冻结。
- 单项上限 `P_max`/`Cap` 现为 100（偷袭、炮击、绞肉机）与 30（资金），四项相加可远超 100；中位数 `S0` 下多数对局的 Stage3 会落到 0，排名由少数 Stage3 仍为正的局与 Stage1-v2 决定（task147 实测 26 局中 23 局 total-v2 = 0）。这是参数与加权方式的结果，不是材料缺失。
- 资金 v2 的 `λ`、动态 `spendFloor`（设计里的 `κ·收入率`）与向先验收缩公式未定，当前用显式先验并标 provisional。
- 危险区在基地内可能因我方造价过高建不起来（设计已知局限 1）；建造者是第一个死的人时不计分（宁漏勿错）。
- 4P 归档局重放会分叉，只有 2P 的归档局能进 v2 总分。
- 页面上的 `old_v1.0` / `old_v1.1` 只是归档批次标签（按目录），不影响分数口径；`old_v1.0` 不参与本轮调参。
