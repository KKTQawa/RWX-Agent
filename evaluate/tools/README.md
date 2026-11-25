# 辅助工具

这几个脚本不属于三阶段评估流程本身：它们整理评测产物、批量复算、核对引擎口径或复盘 Agent 会话，按需手动运行。正式入口见[总 README](../README.md)。

## `match_materials.js` — 一局只留一个目录，并记录 `meta.json`

一局打完后材料本来散在四处：`evaluate/output/commands-<名>.txt`、`evaluate/output/events-live/match-…/`、`evaluate/output/<名>/`、仓库根 `replays/<名>.replay`（新录制入口）。这个脚本把可配对的材料收敛成 `<名>/` 一个目录：

```powershell
node evaluate/tools/match_materials.js                  # 只打印计划，不动文件
node evaluate/tools/match_materials.js --apply          # 真的搬/改名/删重复/写 meta
node evaluate/tools/match_materials.js --apply "<对局名>"  # 只处理一局
node evaluate/tools/match_materials.js --archive --apply  # 顺带把根目录的 *_old 收进 _archive/
```

规则：

- **移动而不是复制**。命令日志搬成 `<名>/commands-<名>.txt`；引擎证据搬成 `<名>/events-live/<名>/`；Replay 搬成 `<名>/replay/<名>.replay`；对局目录里已有同一份材料时删掉外面那份。
- 只有回放、没有任何可定位评估材料的局只报告、不建目录，入口文件保持不动。
- 自动收敛当前批次；已有归档材料不改名或重组。内容不一致时只报 `CONFLICT`，不替人挑一份删掉。
- `--archive` 把根目录里名字以 `_old` 结尾的条目（目录或单个文件）原样搬进 `evaluate/output/_archive/`，根目录只留当前对局。归档不配对、不改名、不写 `meta.json`。
- 可以反复运行：第二次只剩刷新 `meta.json`。

`meta.json` 记这一局的身份：系统版本（引擎版本 + git commit）、参与的模型与思考强度、工具情况、日期、地图配置、时长、胜负、关联会话、token 用量。能从材料读出来的自动填，读不出来留 `null` 并写来源；人工用 `--set key=value`（`model`/`provider`/`thinking`/`tool`/`session`/`tokens`/`outcome`/`note` 等短名字，或任意点号路径）或 `--meta <文件.json>` 补。

## `rebuild_telemetry.js` — 把回放播放证据补成 live 形状

`evaluate_replay.py` 默认会调用它。引擎重放只写"引擎实际接受了什么"；live telemetry 还有一半来自 CLI：每条请求的 `command` 收据、`result` 判决、native 行的 `source`/`commandId`。被拒请求不进 replay，所以这一半必须用同局命令日志补回来。

```powershell
node evaluate/tools/rebuild_telemetry.js --telemetry <播放telemetry> --commands <commands.txt> --replay <replay.jsonl> --out <merged.jsonl> [--started-at <iso>]
```

- 输入三份：播放 telemetry、命令收据日志、`replay.py` 解析出的 JSONL；输出一棵按游戏时钟排序、重排 `seq` 的 telemetry。
- 插入 `command`/`result` 行（refs 带收据时刻的死亡时间），把与收据对上的 replay 命令的 native 行标成 `source=agent`/`commandId`；AI 那侧标 `engine`，没有收据的自动化保持 `replay_unknown`。
- 判决分两档：命中 replay 的请求 `accepted=true`；收据时刻点名的对象**全部**已死/失踪的请求按引擎口径写 `STALE_OBJECT`（可证实）；其余未命中 replay 的操作请求写 `accepted=false` + `OTHER` + `inferred:true`（引擎没执行它，但收据日志没有回执，原因不可还原）；只有 JSONL 字段不足等真正未知的情况才留 `accepted=null`。
- 压缩的 `frames` 行先展开成逐帧再插入，避免把一段压缩运行拆开。
- 原始播放文件由 `evaluate_replay.py` 保留为 `telemetry.engine.jsonl`，合并结果写成 `telemetry.jsonl`，下游 `preprocess.js` / `evaluate_stage_2.js` / `evaluate_stage_3.js` 直接读取合并结果。
- 收据日志里晚于回放 `end` 的请求（对局结束后继续轮询、退出）会被丢掉并计入 `meta.rebuilt.droppedAfterEnd`：那时已经没有引擎状态可判定，`preprocess` 本来也会把这段尾巴裁掉；不丢会让游戏时钟倒走、第二阶段直接拒读。

## `stage3_baseline.js` — 求第三阶段 `S0` 并写标定后的报告

两项饱和公式（偷袭、建筑炮击）的 `S0` 只能用基线 `S` 的中位数。这个脚本扫描已经算好的 `<局>/stage_3/`，重算并汇总：

```powershell
node evaluate/tools/stage3_baseline.js                    # 读 evaluate/output/_archive，只打印
node evaluate/tools/stage3_baseline.js --write            # 顺带写各局 score.calibrated.json/.txt
node evaluate/tools/stage3_baseline.js --match "<甲>" --match "<乙>" --out agent-tmp/x.json
node evaluate/tools/stage3_baseline.js --s0 evaluate/output/_archive/_stage3-baseline.json `
  --match "evaluate/output/<甲>" ... --out evaluate/output/_stage3-standard.json --write
```

- 只统计 `summary.complete=true` 且 `resim/playback.json.checksumWarnings=0` 的局；证据不全、重放分叉的局单独列出并写明原因，不参与中位数。
- 某一族整批没有记录时保留 `config.json` 里的 `S0`（不重置成 1，也不除以 0），报告写“该族无记录，沿用 config.json 的 S0”。
- 聚合结果（各局 `S`、`N` 直方图、类型占比、危险区漏斗、标定后扣分与总分）写到 `--out` 的 JSON 和同名 `.md`，默认在 `_archive/` 下。
- 标定后的报告仍写 `provisional:true` + `s0Source:"archive-median"`：归档语料模型/提示词不统一，只能当工作标定。
- `--s0 <已有基线.json>` 冻结一组 S0（可直接传另一份 `_stage3-baseline.json`），给新一批局打分时不再重新标定；此时 `s0Source="fixed-baseline"`、`baseline.source` 记录来源，分数仍 `provisional`。
- `--kind <名字>` 只改聚合里的 `baseline.kind/source` 标签（如 `standard-corpus`），`--title` 改报告标题。

## `stage3_details.js` — 把第三阶段每一条记录的扣分明细摊开

`stage3_baseline.js` 回答“每局多少分”，这个脚本回答“这些分是哪几条记录产生的”：读各局 `stage_3/score.calibrated.json`（没有就退回 `score.json`）与 `events.jsonl`，逐条列出 `L`/`W`/`w`/`Tf`/`s`、事件时间、单位/建筑类型、`N`、`E`/`H`，并把族扣分按 `s` 比例摊到每条（“份额”）。

```powershell
node evaluate/tools/stage3_details.js                       # 写 evaluate/output/_archive/_stage3-detail.md
node evaluate/tools/stage3_details.js --note "说明"         # 报告头部追加一条说明
node evaluate/tools/stage3_details.js --match "<甲>" --out agent-tmp/x.md
```

- 份额只是饱和函数的比例归因，不能当可加分数：`扣分 = P_max·(1−e^(−S/S0))` 是非线性的。
- 绞肉机列出合并后的事件（区、首死亡、权重和、`age`、`B`、`L`）与每条被排除的建造者死亡原因。
- 重放分叉（`resim/playback.json.checksumWarnings>0`）的局照样列，但表头标「排除」并写明不一致条数。
- 没有 `stage_3` 的局直接跳过，不占位。

## `evaluate_corpus_v2.js` — 整批跑 v2 总分（含归档局）

一次扫完 `evaluate/output` 全树（含 `_archive/old_v1.0` 与 `_archive/old_v1.1`），逐局算 `stage1-score-v2` + `stage3-score-v2` + `total-v2`：

```powershell
node evaluate/tools/evaluate_corpus_v2.js                     # 全部可评估的局
node evaluate/tools/evaluate_corpus_v2.js --match "<对局目录>"  # 只跑一局
```

- **证据选择**：`prepared/telemetry.jsonl` 里有 `stage3_meta` 就直接用 live；否则要求 `resim/telemetry.jsonl` 存在且 `resim/playback.json.checksumWarnings === 0`，否则该局记入忽略（`replay_desync:<N>` / `economy_missing` / `stage3_evidence_unavailable`），不猜分。
- **人类基线局**（没有 `commands-*.txt`，最常见的是真人用鼠标打的一局）：不跑 Stage1-v2，直接写一个 `score: 0`、`human: true`、`status: not-applicable` 的 `stage_1_v2/score.json` 桩，然后照常算 Stage3 v2 / v2.1；`total-v2.1 = 0.4×0 + 0.6×stage3`。窗口仍由 `preprocess.js` 用 telemetry 的 `victory/defeat/end` 定。`meta.json` 里 `runner=human`（或 `tools.profile=Human`）会让网页把它归到「人类」行。整条流程一条命令：`.\agent-operation\server\collect-evaluation-run.ps1 -Tool Human -Apply -Batch`。**人类局必须有回放**：没有 `replay/*.replay` 的局直接 `human_missing_replay` 拒评（材料不全都拒绝，不是猜分）。
- 每局写 `evaluation_v2.json`（评分窗口、结局/战败投降、`evidenceSource`、两个阶段的分数、可选的旧 `stage1v1`/`stage2` 对照），并把全部结论、忽略原因和由 `config.json` 调参池定义的 `S` 中位数汇总到 `evaluate/output/_v2-summary.json`。
- 调参池从磁盘按 `policy.tuningPool` 收集（不限于本次调用重跑的局）：`evaluate/output` 根目录、窗口 >`minDurationExclusiveSeconds`、Stage-3 证据完整、重放无分叉；`meta.json.evaluation.disposition` 在 `excludeDisposition` 里的局（当前 `worthless`）退出调参池，但仍照常评分并写进摘要的 `excluded`。
- 每局的 `archive` 取自目录：`_archive/<标签>/…` 用该标签，其余算当前批次（`old_v1.1`），所以 `old_v1.0` / `old_v1.1` 不需要在代码里写死名单。
- 结局由 `preprocess.js` 的 `planWindow` 判定（投降/退出/我方指挥中心被毁/敌方全灭/正常结束，取最早），所以同一局在 v2 里的窗口与旧 `stage_2` 的窗口可能不同。
- 它只重算评分，不重跑 `preprocess.js`；窗口 ms 直接传给两个评分器（`--cut-ms`），所以 `prepared/` 与 `resim/` 必须已经是当前版本的产物。
- `total-v2` 之后顺带调 `score_match_v21.js` 写 `score_v21.json`（v2.1 对照分）并记进 `evaluation_v2.json` 的 `scores.totalV21`；v2.1 失败只记 `v21Error`，不影响 v2 结果。

## `add_v21_scores.js` — 给现有对局补 v2.1 评分并出汇总表

`total-v2.1` 把第三阶段的偷袭、偷家、资金换成 v3 定义，绞肉机沿用 v2：

- 偷袭 v3：只取我方陆地移动单位被敌方移动单位打的 idle 事件；`M1 = Σw` 包含 `T<T0` 的快速反应和 `died` 事件，`u` 从 `T0=3s` 爬到 `T_hi=21.122s`，`u' = min(1,u+δ·died)`，`sev=1`（死亡）或 `clip(E/H,0.3,1)`，`R1=Σw·u'·sev/(M1+3)`。
- 偷家 v3：炮兵事件 `N≥2` 或摧毁才进 `M2`，`T_j` 取最后一发到第一发（摧毁取摧毁时刻），`T0=8s`、`T_hi=23.152s`，`R2=Σw·u'·sev/(M2+2)`。
- 两项扣分 `P_max·(1−exp(−R/R0))`，`P_max=50/40`，`R0=0.253601/0.237905`（26 局 R 中位数）；v3 的 `R` 是价值加权的失职占比，`M` 是事件次数分母，不再用全场伤害 `X1/X2`。
- 资金 v3 按评分窗口切 `[0,1/4)`、`[1/4,3/4)`、`[3/4,1]` 三段，`Ki = 段花费 / 段可用`（每段可用含该段段初资金），`K = 0.4K1 + 0.4K2 + 0.2K3`，扣分 `(1−K)^exponent × 30`（exponent 默认 0.5）。
- 总分：`clip(stage1-v2 × 0.4 + stage3-v2.1 × 0.6, 0, 100)`，权重在 `total.v2_1.parameters`。

本工具不重跑 Stage1；Stage3 只从 `stage_3/score.json` 取绞肉机，v3 的偷袭/偷家从 telemetry 重算（`stage_1_v2/score.json`、`prepared/telemetry.jsonl`、`stage_3/score.json`、`economy.log`）：

```powershell
node evaluate/tools/add_v21_scores.js                 # 当前批 + 归档
node evaluate/tools/add_v21_scores.js --current-only  # 只算 evaluate/output 根目录
node evaluate/tools/add_v21_scores.js --root <目录>
```

- 入选条件：有 `stage_1_v2/score.json`、`stage_3/score.json`、`prepared/telemetry.jsonl`（或 `resim/telemetry.jsonl`）和 `economy.log`（`prepared/`、`resim/` 或 `stage_3/`）。缺任何一项就记入 `ignored`，不猜分。
- 每局写 `score_v21.json` / `score_v21.txt`；`score_v2.json`、`stage_3/score.json`、`stage_3/events.jsonl` 都不改。`components.stage3.ambush.records` / `barrage.records` 给出准入记录及 `E/H/ratio/u/uPrime/sev/w/s`；`M/R/R0/events/admitted` 与 `legacy`（v2 伤害占比）同时在顶层。资金 v3 的 `windows[]` 给出每段 `income/available/spent/rawRatio/k`。
- 汇总写 `evaluate/output/_v21-summary.json`（机读）、`_v21-summary.md`（主表 + 偷袭/偷家 v2→v3 + 事件数/饱和 + 统计 + `R0/T_hi` 标定）与 `_v21-detail.csv`。`--current-only` 只算当前批并只把当前批写进汇总（当前文件就是这个口径）。
- 归档局的 Stage1/Stage3 是历史批次参数；v2 与 v2.1 两列分别用各自当前的总分公式重算（不采用归档 `score_v2.json` 里已退役的 `stage1×0.4 + stage3×0.6`），只作参考。

## `stage1_provisional.js` — 26 局偏差池的临时 Stage1 标尺

这版只解决 `stage1-v2` 的 silence 饱和：26 局里 f5 有 42.3%、f6 有 88.5% 顶满，`W`/`λ` 对顶满样本无效。
它只把 f5/f6 的 `hi` 改成逐局时间加权 P90 的 P90（88.568 / 107.472），`lo` 保留 5/3，`W=(20,40,40)` 与 `λ=0`
冻结，活跃度闸门关闭；参数在 `config.json` 的 `stage1.v2_provisional.parameters`。

```powershell
node evaluate/tools/stage1_provisional.js              # 500 次块自助
node evaluate/tools/stage1_provisional.js --reps 300
node evaluate/tools/stage1_provisional.js --root <目录>
```

- 读 `<对局>/prepared/commands-*.txt` 与 `prepared/telemetry.jsonl`，按 `evaluation_v2.json` 的窗口复算 f1–f6；缺输入或旧报告分数对不上会报在终端，不猜分。
- 写 `<对局>/stage_1_v2_provisional/score.json|score.txt`，以及 `_stage1-provisional-summary.json|md`、`_stage1-provisional-detail.csv`。**不覆盖** `stage_1_v2/`、`score_v2.json`、`score_v21.json`、`_v21-summary.*`。
- 汇总含逐局 f1–f6、末尾空窗、旧/新 `u`、旧/新分数、饱和率、特征相关、胜负 AUC、与 Stage3 v2.1 的相关、P1–P6/R 扰动和 5 块自助。
- 结论：均值 35.882 → 40.616；f5/f6 饱和均降到 3/26；f5–f6 相关 0.841；块自助标准差 1.393 > 相邻分差 0.860，局间排序不可信。详见 [`STAGE1_V2_PROVISIONAL.md`](../STAGE1_V2_PROVISIONAL.md)。

## `stage1_saturation.js` — 只读 CSV 的 Stage1 饱和度验收

检查设计验收条件“每个**计分**特征 `u=1` 的局数占比 ≤40%”。它只读
`_stage1-provisional-detail.csv` 的 `newU1..newU6`，**不重新评分**；`f4` 仅诊断，不计入通过/失败。

```powershell
node evaluate/tools/stage1_saturation.js
node evaluate/tools/stage1_saturation.js --csv <detail.csv> --threshold 0.4
```

- 写 `_stage1-saturation.json` / `_stage1-saturation.md`；任一计分特征超 40% 时退出码为 1。
- 当前 26 局：f1 1/26（3.9%）、f2 0/26（max u 0.922）、f3 0/26（max u 0.650）、
  f5/f6 各 3/26（11.5%），**全部通过**；f4 17/26（65.4%）只作诊断。因此 f1/f2/f3 的 hi 不动。

## `calibrate_stage3.js` — 用调参池重标定 `S0` 与资金参数并写回 `config.json`

自动标定的全局参数有四项：偷袭/炮击的 `S0`（池内 `S` 中位数），资金 v2 的 `K`（`clip(median_m Q0.9(r_m), 20, 45)`）、
`d0`（`Q0.5(d_k)` 裁 `[8,25]`）与 `d1`（`Q0.95(d_k)` 裁 `[90,180]`）。`S` 与 `S0` 无关，资金分位只看 `economy.log`，
所以不用重跑阶段：

```powershell
node evaluate/tools/calibrate_stage3.js            # 只报告
node evaluate/tools/calibrate_stage3.js --write    # 写回 S0、资金参数与 stage3.calibration
node evaluate/tools/calibrate_stage3.js --out evaluate/output/_tuning-step.json --label "3/26 <局名>"
```

- 池规则只来自 `policy.tuningPool`（见 [`tuning_pool.js`](../tuning_pool.js)）：当前批、窗口 >min、证据完整、重放忠实、`disposition` 不在 `excludeDisposition`（`worthless` 出池但仍评分）。
- 样本少于 `--min`（默认 3）时保持当前 `S0`；参考区间少于 `--intervals`（默认 30）时资金三项保持先验。
- `--write` 同时更新 `stage3.calibration.current`（样本数、胜负分布、`minDurationExclusiveSeconds`、`excludedDisposition`、`funds` 标定明细）；`initial` 不动。
- 归档语料仍用 `stage3_baseline.js`（写 `score.calibrated.*` 与聚合），两者不互相覆盖。

## `calibrate_v3.js` — 用指定池重标定偷袭/偷家 v3 的 `T_hi` 与 `R0`

v2.1 的两个 v3 项共用一套全局参数，所以「让某一类对局的参数影响另一类」只能靠**换标定池**。本工具按池给出候选值，并用同一批记录重算每局扣分，`--write` 才落盘：

```powershell
node evaluate/tools/calibrate_v3.js                  # 默认池 current（全部当前对局，含人类）
node evaluate/tools/calibrate_v3.js --pool ai        # 只用 AI 对局
node evaluate/tools/calibrate_v3.js --pool human     # 只用人类对局
node evaluate/tools/calibrate_v3.js --pool all       # 一次报告四个池
node evaluate/tools/calibrate_v3.js --pool current --write
```

- 口径：`T_hi` = 各局准入事件 T 的 P90，再取池内中位数；`R0` = 池内各局 `R` 的中位数（含 `R=0` 的局）。
- 报告会给出「换掉参数后，池内偷袭+偷家的扣分合计与总分合计」的变化，便于判断要不要写。
- **注意**：池内 `R=0` 的局占多数时（例如人类局偷家 7/13 为 0），中位数会落到 0，`R0=0` 会让该项直接打满 `P_max`。写回前先看报告。
- `--write` 更新 `stage3.v21.parameters.ambushV3/barrageV3` 的 `T_hi`/`R0` 与 `stage3.v21.calibration`；写完要对整批重跑 `add_v21_scores.js` 才会改分。

## `run_batch_v2.js` — 按创建时间顺序重跑整批，每局后调参

```powershell
node evaluate/tools/run_batch_v2.js                 # 26 局顺序重评 + 逐局标定 + 最终统一补跑
node evaluate/tools/run_batch_v2.js --no-final      # 只做顺序重评与逐局标定
node evaluate/tools/run_batch_v2.js --limit 3       # 只处理前 3 局（调试）
```

- 顺序取目录名里的开赛时间（`YYYYMMDD--HH-MM`），没有时回落到 `meta.createdAt`；同分钟按目录名。
- 第一遍（walk-forward）：逐局 `evaluate_corpus_v2` 的 `evaluateMatch` → `calibrate_stage3 --write`，把每步的 `S0`、池大小与分数写进 `evaluate/output/_batch-v2.json`。
- 第二遍（final）：用收敛后的 `S0` 对当前批再统一重评一次，保证榜单同基线；`--no-final` 关掉。
- `meta.json` 只读：驱动对每局 `meta.json` 取 SHA-256，前后不一致直接报错。
- `_v2-summary.json` 由最终遍重写；之后按需跑 `build_web_results_v2.js` 与 `check_site.py`。

## `build_web_results_v2.js` — 把 v2 汇总写进网页账本

`_v2-summary.json` 与 `evaluate/output/` 都不进版本库，页面读不到。这个脚本把结论写成 `web/resource/results.json`（schema 3）：

```powershell
node evaluate/score_extra.js evaluate/output --all    # 可选：先刷新操作流畅度产物
node evaluate/tools/build_web_results_v2.js
python web/tools/check_site.py
```

- 每局一条：`title`（`meta.display_name` 优先）、`pairs`（模型 × 数量 × 工具，工具改造放 `extra`）、`duration`（评分窗口 + 游戏秒）、`result`（胜负/投降）、`scores`（`totalV2`/`stage1V2`/`stage3` 与可选的旧分）、`stage3.deductions`（四项扣分与上限）、`v21`（当前口径与 v2 对照）。
- 每局另带 `fluency`：`extra/score.json` 的操作流畅度四元组（`score` / `mu` / `dead` / `cv`，`appliesToTotal: false`）。它是附加分，不参与 `total-v2.1` 与排序；`material` 区分回放重采（`native`）与降级采集（`live`）。
- `human` / `scriptAi` 标记人类局与脚本 AI 基线局；两者都没有 CLI 命令日志，`stage_1_v2` 按约定记 0，页面上各自单独成行。
- 归档语料没有结构化 `meta.json` 的，用脚本顶部的 `ARCHIVE` 表补日期与参与模型；缺的字段写 `unknown`，不猜 provider/推理强度。
- 忽略的局单列进 `ignored`（原因 + 相对路径），页面上是"未进入排名"。
- `check_site.py` 会校验 `total-v2` 与 `stage1-v2 − (100−stage3)×(1−k)` 一致、四项 Stage3 齐全、`fluency` 四元组完整、`pairs` 字段完整。

## `results_details.js` — 把逐项扣分证据写进网页账本（old_v1.1 旧账本）

评测页要对每一局展开「第一阶段 12 项 + 第二阶段 6 类」的扣分明细，但 `web/resource/results.json` 在版本库里、`evaluate/output` 不进版本库，页面自己读不到评分产物。这个脚本做桥梁：

> 2026-11-06 起评测页改用 `total-v2` 账本（schema 2），不再有 `stage1Items`；本脚本只用于复现 `old_v1.1` 之前的旧账本，新流程请用 `build_web_results_v2.js`。

```powershell
node evaluate/tools/results_details.js           # 把证据写进 results.json
node evaluate/tools/results_details.js --check   # 只比对，不写；有漂移时退出码 1
```

- 从 `stage_1/score.json` 的 `evidence` 生成第一阶段每项的「本局证据」（首个行动秒数、周期均值、离群数、底层间隔分布……）；从 `stage_2/score.json` 的逐事件明细生成第二阶段每类的说明（可计分/不可计分的闲置段数、偷袭加权冲击与最大一次、资金闲置时长与峰值……）。
- 第二阶段 6 类固定顺序输出；某一局没有该类事件时补 `raw/capped = 0` 与「本局未出现该类事件」，页面才能逐局对齐。
- 写回的是 `metrics.stage1Items[].detail` 与 `breakdown.stage2.families[]`（`raw/capped/cap/events/detail`）。分值以评分产物为准：账本分数与 `score.json` 对不上、或缺某一项时脚本直接报错不写，避免页面展示旧分。
- 新对局要在脚本的 `DIRS`（`id` → `evaluate/output/<对局名>`）里补一行，或直接在账本条目里写 `match` 字段；历史上有两局目录名与工具编号相反（`…07-22__dsh4.1_tool1_vsHard` 实际是 tool2），映射表已按会话与录像核对过。

## `stage1_audit.js` — 批量复算全部 Stage1 报告

口径或评分规则改动后，需要确认"现有报告复算出来的数字有没有变"。`evaluate_stage_1.js` 一次只处理一局，这个脚本按 `execution_summary.json` 遍历 `evaluate/output/`，单局失败不中断其余样本：

```powershell
node evaluate/tools/stage1_audit.js                    # 就地重生成（覆盖现有报告）
node evaluate/tools/stage1_audit.js --out <目录>        # 写到别处，不动现有报告
node evaluate/tools/stage1_audit.js --resolve <目录>    # 输入缺失时额外搜索该目录（可重复）
```

每局输出一行 JSON（时长、A/B、分数、健康状态、开局里程碑、周期/等待、空窗占比、无落地原始/调整），最后汇总成功/跳过/失败数。缺原始输入（commands 或解析后的 JSONL）的样本记为跳过，退出码不受影响；只有评估本身报错才返回非零。

命令日志被 `match_materials.js` 改名后，旧报告里的 `file1` 仍指向改名前的路径；脚本会退回同一对局目录里的 `commands-<对局名>.txt`，不需要先把关卡搬回去。

注意：早期扁平布局（`evaluate/output/commands-…_analysis/`，没有 `stage_1/`）的样本会被写到一个**新的** `<对局名>/stage_1/`——产物目录由 commands 文件名推出，不会覆盖旧目录。这类样本要人工比对后再替换。

## `archive_micro_runs.py` — 把微操局收敛成完整对局的一局一目录

微操引擎把录像写成 run 根目录的 `match.replay`，逐局 HTML 汇总写在 `<CASE>/reports/`；完整对局则是
`<对局>/replay/<对局>.replay`、所有材料都在对局目录内。这个脚本把已有微操局统一成后者：

```powershell
python evaluate/tools/archive_micro_runs.py              # 只打印计划
python evaluate/tools/archive_micro_runs.py --apply      # 执行
python evaluate/tools/archive_micro_runs.py --case CASE1-duel
```

- 回放从 `match.replay` 改成 `replay/<run>.replay`，并同步 `meta.json` 的 `replay` 字段；
  `replay/match.{jsonl,txt,summary.txt}` 一并改成 `replay/<run>.*`。
- 已经用 `stamp_micro_meta.py` 命名的局（`meta.replay` 的文件名等于 `meta.display_name`）**不再移动回放**，
  显示名就是公开身份、目录名和回放文件名；本脚本只继续收敛解析产物与 HTML。
- `<CASE>/reports/<run>.html` 搬进 `<run>/eval/report-full.html`，改写它内部的汇总页链接，并改写
  `reports/index.html` 里指向逐局页的链接。
- 根 `replays/<run>.replay` 是收录局回放的镜像（文件名与 run 目录同名），保留不动，只有字节不一致时才报
  `CONFLICT`；只有旧 run-id 命名的根回放才在字节一致时删除。没有对应 run 的根回放报 `ORPHAN`，不猜、不覆盖。
- 只移动不复制，默认 dry run，可反复运行；不重命名 run 目录（目录名由 `stamp_micro_meta.py` 改成 display name）、
  不改写 `result.json`。
- 受管局先用 `collect_runs.py` 把完成的 `micro-output` 搬进 `<CASE>/`，再跑本脚本收敛布局。

## `stamp_micro_meta.py` — 声明参与者，并把 run 目录改成 display name

微操引擎只写对局证据，不写是谁跑的。这个脚本按完整对局同名口径把
`models[{provider,id,thinking}]`、`tools[{profile,detail}]`、`runner`、`display_name` 写进 `<run>/meta.json`，
并把 run 目录本身改名成 display name：

```powershell
python evaluate/tools/stamp_micro_meta.py --run evaluate/output/micro/CASE2-LTE/<run> `
  --provider OpenCode --model "DeepSeek V4.1 Flash" --thinking high --tool Pi --runner agent --apply
```

- 默认 dry run；`--run` 可重复，一次给多局写同一身份。
- 显示名按完整对局的形状生成：`<case> <task> [track] · <YYYYMMDD HH-MM> · <参与者> · s<seed>`；
  例如 `CASE2-LTE 2_7_4 realtime · 20261114 17-59 · DeepSeek V4.1 Flash - Pi · s1331`。
  目录名与 `meta.display_name` 是同一个字符串，所以归档路径本身就写明参与者，而不是只有
  `CASE2-LTE_2_7_3_realtime_s1331_20261113-100024` 这类环境戳。
- 参与者槽位有三种声明：`--runner agent`（必须同时给 `--provider`/`--model`/`--tool`，可选 `--thinking`）、
  `--runner baseline`（greedy 脚本基线，`--runner script` 等价）、`--runner human`。没有 `models` 的局必须显式
  声明 `baseline`/`human`，脚本不会把脚本局当成 Agent 局来命名。`meta.runner` 记录同一个事实。
- 改名同时修掉所有存过旧目录名的地方：`meta.map.file`、回放内嵌的 `mapPath`（重新压缩并修块长度）、
  `replay/` 下的解析产物文本、以及 CASE `config.json` 里 `baselines.byTask[*].run` 的指针。
- 回放文件同时改名成 `<display_name>.replay`，`meta.replay` 指向它。模型/工具之间用 `-` 而不是完整对局的
  `/`，因为同一个字符串要能直接当 Windows 文件名；其余分段（名称、时间、run id）与完整对局一一对应。
- `--display-name` 可覆盖自动生成的名称；`/` 等文件名非法字符会在**文件名**里替换为 `-`，但 `meta.display_name`
  保留原值。已带 `display_name` 的局再次执行会沿用它，不会因为目录改名而重算时间。
- `--attempt N`：同一配置重跑时给显示名追加 ` · 0N`，并把 `meta.attempt` 写成 N（如
  `… · DeepSeek V4.1 Flash - Pi · s1331 · 02`）。网页按这个字段把 `Pi 01` / `Pi 02` 分开展示，
  同时仍按工具（`Pi` / `DSH`）做汇总。
- 只增/覆盖统计字段、重命名回放与目录，不动引擎写的地图、单位、预算与结果；重复执行无副作用。

## `patch_replay_map.py` — 把回放里的地图路径指向当前 `map.tmx`

回放的初始存档记录的是录制时的地图位置。微操局原来写**绝对路径**，`collect_runs.py` 把 run 移进
`evaluate/output/micro/<CASE>/` 后路径就失效，点开回放会因地图找不到而弹出“是否退出”。
现在非官方地图一律记成抽象路径 `/SD/rustedWarfare/maps/<文件>`——引擎按
`DesktopPlatformStorage.mapsDir` 解析到 `<数据目录>/mods/maps/<文件>`，换机器、搬目录都不失效；
地图在 `assets` 里（官方地图）才保留绝对路径。这个脚本只重写 `gamesave/saveCompression` 里的
`mapPath`（重新压缩并修正块长度），命令、时序和其余材料逐字节不变：

```powershell
python evaluate/tools/patch_replay_map.py --run evaluate/output/micro/CASE2-LTE/<run>          # 只打印计划
python evaluate/tools/patch_replay_map.py --run evaluate/output/micro/CASE2-LTE/<run> --apply
python evaluate/tools/patch_replay_map.py --root evaluate/output/micro                         # 扫全部 run
python evaluate/tools/patch_replay_map.py --replay <file.replay> --map <map.tmx> `
    --stored-name CASE2-LTE-s1331-map.tmx --apply
```

- 生成的微操地图都叫 `map.tmx`，写进 `mods/maps/` 会互相覆盖，所以给 `--stored-name` 一个唯一名字；
  官方地图与完整对局的地图本来就有唯一文件名，不需要它。
- 完整对局的回放本来就用 `/SD/rustedWarfare/maps/<地图>.tmx`，不需要这个脚本。

- 只处理有同目录 `map.tmx` 的 run；run 根目录与 `replay/` 下的 `*.replay` 都会检查（包括显示名回放）。
- 默认 dry run；`--apply` 原子替换。无变化时输出 `unchanged`，重复运行无副作用。
- `collect_runs.py --apply` 已自动调用同一逻辑，新收的局不需要单独跑；这个脚本用于历史材料或手工移动过的回放。

## `cleanup_micro_output.py` — 清理微操运行产物

微操每跑一次就写一个 `evaluate/output/micro/<CASE>/<case>_<task>_<track>_s<seed>_<stamp>/`，同一配置反复重跑会留下大量只差时间戳的兄弟目录；根目录 `replays/` 还会为每个 run 留一份 `<run>.replay`。

```powershell
python evaluate/tools/cleanup_micro_output.py           # 只打印计划，不删
python evaluate/tools/cleanup_micro_output.py --apply   # 执行
```

口径：按 `(case, task, track, seed)` 配置分组，每组只保留一个 run（优先有 `result.json` + `eval/report.txt` 的，其次最新的有 `result.json` 的，**没有 `result.json` 的中断局一律不留**）；`replays/<run>.replay` 跟随其 run 存亡。

它只认微操 run 名（`CASE<n>-…_realtime|pause|human_s<seed>_<时间戳>`）。完整对局的回放现在叫 `<对局名>.replay`（与 `evaluate/output/<对局名>/` 同名），`[local] *.replay` 是真人局：这两类都不归它管，永远不会被删。

## `session_cast.js` — 归档并分析 Agent 会话

Agent 的思考链是评测的重要旁证。把 Pi 的会话文件归档并生成基本分析：

```powershell
node evaluate/tools/session_cast.js C:\Users\<你>\.pi\agent\sessions\<目录>\<会话>.jsonl `
     --name "<对局名>" --match "<对局名>"
```

产出 `evaluate/session-cast/<对局名>/{session.jsonl, analysis.md}`：工具调用次数、被拒命令及引擎回执、思考量、单轮间隔、WSL 告警条数。整个目录被 `.gitignore` 忽略——会话是模型自己的推理记录，本地留存、不随仓库分发。`--out <目录>` 换输出目录。

## `income_audit.js` — 核对收入口径

引擎按 `resourceIncomeUpdateInterval`（10 tick）结算、HUD/CLI 按 `resourceIncomeRatePeriod`（40 tick）报速率，两者只在常量与时钟步长一致时才等于实际到账。这个脚本挑出"没有下单的安静秒"，直接比对资金实增与两个速率字段，不信任任一侧的换算。

输入是一个按 `kind` 区分三类行的 JSONL：`command`（`timeMs`/`name`/`id`）、`economy`（`sampleMs`/`funds`/`income`/`incomePerSecond`）、`result`（`commandId`/`reply`，用来抓 `rwx-game-state` 回复里的 `Credits: N (+M/s)`）。

```powershell
node evaluate/tools/income_audit.js <evidence.jsonl>
```

输出 `fieldToDelta`、`ipsToDelta` 两个比值：接近 1 说明该字段就是每秒到账，接近 1.5625 说明它是"每 40 tick"。用于确认 `rwx-game-state` 的 `incomePerSecond` 可信，以及 `economy.log` 的 `income` 为什么不是每秒。

## `damage_scope_check.js` — 核对偷袭/炮击的伤害口径

把 `stage_3/events.jsonl` 里可计分的偷袭、炮击事件与 `prepared/telemetry.jsonl` 的原始 `damage` 行按 `(受害者 id, timeMs, hpLoss, shieldLoss)` 关联，逐条拆成：

- **A**：我方陆地移动单位被敌方非建筑单位打（`hpLoss+shieldLoss`）；
- **B**：我方建筑被敌方单位打（`unit` 与 `all` 两列，后者含敌方炮塔/建筑）。

输出每局的 `ambush` / `ambushInsideA` / `ambushAir` / `ambushBuilding` / `A` / `barrage` / `BUnits` / `BAll`，以及违规检查（`ambush>A`、`barrage>B`）。陆地/空中/水上按类型表分类；`hoverTank`/`heavyHoverTank`/`hovercraft` 属 `HoverLandUnit`，归陆地。只读，不改材料。

```powershell
node evaluate/tools/damage_scope_check.js                 # 当前批
node evaluate/tools/damage_scope_check.js --json          # 机读明细
node evaluate/tools/damage_scope_check.js --root <目录>
```
