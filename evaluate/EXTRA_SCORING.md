# 附加分：操作流畅度（`extra-fluency-v1`）

**不计入 `total`。** 这是一项诊断指标：它衡量"操作节奏是否流畅"，不衡量"响应是否及时"。

它和 Stage1/2/3 的根本区别是输入：那三阶段看状态（资金、单位、伤害），这一项直接读**引擎执行的命令流**（`telemetry.jsonl` 的 `native` 行）。每条命令本身就是一次操作，不需要从状态差分里推断。

脚本：[`score_extra.js`](score_extra.js)　测试：[`test/test-extra.js`](test/test-extra.js)

---

## 1. 口径

| 项 | 取值 |
|---|---|
| 时间基 | `native` 行的 `timeMs`，即 tick 换算的游戏时间；**暂停不推进**，不需要额外剔除暂停段 |
| 窗口 | `stage_3/summary.json` 的 `durationMs`，已经裁到"胜负已定"（指令中心被摧毁/投降） |
| 开局 | 跳过 `skipHeadSeconds`（默认 30 s），**跳过的时长也不进分母** |
| 席位 | 只取 `meta.team` 对应的席位；敌方 AI 的命令行一律丢弃 |
| 去重 | 按 `nativeId` 合并 `before`/`after` 成一行；`targetId` 只在 after 行，合并时回填 |
| 材料 | 优先 `<match>/extra/native.jsonl`（回放重采的命令流，带 `x/y`/`targetId`/`buildType`）；没有才回落到 `prepared/telemetry.jsonl`（`material: live`，降级） |
| 计入 | `action` `move` `attackMove` `guardAt` `build` `repair` `patrol` `loadInto` `reclaim` `loadUp` `guard` `follow` `stop` `attack`（`countAttack` 可关） |

`attack` 是**玩家主动指定目标**的命令，单位自动开火不会产生它，所以默认计入。

## 2. 从命令到「操作」

一条命令不等于一次操作：一次框选 30 个单位是一次操作，30 次单独点击是 30 次。

1. 合并 `before`/`after` → 一条命令一行。
2. 展开成单位级命令（每条命令带 `units` 列表）。
3. **刷屏抑制**：同一单位、同一签名，在 `spamSeconds` 内重复下令只记第一次。
4. **归并**：同一 `operation` + 时间桶 `bucketSeconds` + 同一签名 → 一次操作，`n` = 不同单位数。
5. **权重**：`w = 1 + α·ln(n)`，100 个单位约 2.4 而不是 100。

签名规则：

| 命令 | 签名 |
|---|---|
| 空间类（move/attack/attackMove/build/repair/guardAt/…） | 坐标按 `positionQuantum` 取整 + `targetId` |
| `action` | 首单位 + `actionId`（两个工厂造同一个兵是两次操作） |
| `stop` | 首单位 |

**缺坐标时降级**：材料没有 `x/y` 就分不清两次下令是否同一个目标，此时不做归并、不做刷屏抑制，一条命令记一次操作，并在 `warnings` 里报 `no_coordinates`。宁可粗，不可把整局折叠成几次"操作"。

## 3. 三个分量

设清洗后的操作序列 `t_1<…<t_n`，权重 `w_i`，活跃时长 `A`（窗口减去开局跳过），间隔 `g_i = t_{i+1}-t_i`。

| 分量 | 定义 |
|---|---|
| 频率 | `μ = Σw_i / A × 60`（加权操作/分钟）；`S_rate = 1 − e^(−μ/μ0)` |
| 发呆 | `q = (Σ g_i, g_i>T) / A`，**首尾边缘也算间隔**；`S_dead = clip(1 − (q−q0)/(q1−q0), 0, 1)` |
| 节奏 | 把 `A` 切成 `W = smoothWindowSeconds` 长的窗口，`e_k` = 第 k 窗的加权操作数；`CV = σ_e/μ_e`（至少 2 窗）；`S_smooth = clip(1 − (CV−c0)/(c1−c0), 0, 1)` |

```
Fluency = 100 · S_rate · (w_dead·S_dead + w_smooth·S_smooth) / (w_dead + w_smooth)
```

`S_rate` 是**乘法门槛**，避免"低频但很稳"拿高分。首尾边缘计入发呆占比：每局操作数本来就不多，丢掉边缘恰好会漏掉"原地两分钟"这种最该抓的情况。

**为什么节奏项按窗口、而不是按命令间隔**：间隔 CV 测的是**命令粒度的爆发性**。按轮询周期成簇下令的脚本，每个周期一次吐 10 条、然后停几秒，间隔序列天然高方差（实测 CV 1.17–1.44），比一条一条点的人类（0.92）更"不匀"——于是脚本的节奏分反而低于人类，与设计目标相反。改成"每 30 s 有多少操作"的 CV 之后，测的是**战略节奏**，成簇下令不再被惩罚：脚本 0.37 < 人类 0.44 < Agent 0.61。窗口不足 2 个时 `CV` 记 null、`S_smooth = 0`（没有离散度就白送满分是不对的）；`smoothWindowSeconds: 0` 可退回旧的间隔算法，只用于诊断。

## 4. 参数

都在 [`config.json`](config.json) 的 `extra.parameters.fluency` 里，脚本每次调用重新读盘。

| 参数 | 当前值 | 含义 |
|---|---|---|
| `T` | 8 s | 长间隔阈值，超过即整段算发呆。**最敏感**，改了要重标 `q0`/`q1` |
| `mu0` | 14 | 频率饱和尺度；`μ=mu0` 时 `S_rate≈0.63` |
| `q0` / `q1` | 0.15 / 0.75 | 发呆占比的满分点 / 零分点 |
| `c0` / `c1` | 0.40 / 0.95 | 窗口 CV 的满分点 / 零分点 |
| `α` | 0.3 | 批量压缩系数；0 = 一次操作恒为 1 |
| `spamSeconds` | 3 | 刷屏抑制窗口 |
| `bucketSeconds` | 5 | 归并的时间桶 |
| `skipHeadSeconds` | 30 | 开局忽略时长 |
| positionQuantum | 1 px | 坐标取整粒度 |
| `smoothWindowSeconds` | 30 s | 节奏项的统计窗口；0 = 退回按命令间隔的旧算法（仅诊断） |
| smoothWindowSeconds | 30 s | 节奏项的统计窗口；0 = 退回按命令间隔的旧算法（仅诊断） |
| `weightDead` / `weightSmooth` | 0.5 / 0.5 | 两项权重 |
| `countAttack` | true | 是否计入主动 `attack` 命令 |

## 5. 输出

单局（`extra/` 下）：

| 文件 | 内容 |
|---|---|
| `score.json` | 全部分量、参数快照、计数、`material`、`longestGaps`（最长 5 段，带起止时间） |
| `score.txt` | 一屏报告 |
| `ops.csv` | 清洗后的操作时间线（`t_ms,operation,units,weight,x,y,action,targetId,buildType,applied`） |
| `native.jsonl` | **重采产物**：窗口内的 `native` 行（含 `x/y`/`targetId`/`buildType`），37 局共 32.8 MB |

批量（`evaluate/output/` 根）：

| 文件 | 内容 |
|---|---|
| `_extra-summary.csv` | 每局一行：`material / fluency / operations / weighted / muPerMinute / deadShare / cv / activeSeconds / warnings` |
| `_extra-summary.json` | 同上，带 `components` |

## 6. 用法

```bash
# 单局
node evaluate/score_extra.js "evaluate/output/<match>" 
node evaluate/score_extra.js "evaluate/output/<match>" --out agent-tmp/x --json
# 批量（54 局，约 10 秒；自动优先 extra/native.jsonl）
node evaluate/score_extra.js evaluate/output --all
# 指定窗口材料/席位
node evaluate/score_extra.js <match> --telemetry <file> --team 1 --skip-head 60
```

`--all` 会扫 `evaluate/output` 下**所有**有 `prepared/telemetry.jsonl` 的目录。别的 Agent 正在产生的新批次也会被算进去（它们可能还没跑完），需要自己限定池子边界再解读汇总。

重采（补 `x/y` 等字段）不是日常操作，流程是：用 `desktop/build/headless` 以 `--headless --auto-replay=<replay> -Drwx.evaluate.dir=… -Drwx.evaluate.team=… -Drwx.evaluate.replaySpeed=64 -Drwx.evaluate.exitOnReplayEnd=true` 播放回放，把窗口内的 `native` 行抽成 `<match>/extra/native.jsonl`。一局一个 JVM、串行。

## 7. 材料来源与标定状态（`provisional`）

### 7.1 两份材料

| `material` | 来源 | 有无坐标 | 可比性 |
|---|---|---|---|
| `native` | `<match>/extra/native.jsonl`：用 headless 重放该局回放得到的命令流（2026-11-21 重采，37 局） | 有 | **可跨局比较** |
| `live` | `prepared/telemetry.jsonl`：原始采集，补丁前没有 `x/y` | 无 | **不可比**，只做参考 |

降级模式（`no_coordinates`）一条命令记一次操作、不合并、不抑制刷屏，因此会**系统性抬高 μ 与 CV**：本次 17 局 live 材料 μ 最大 110.9、CV 最大 3.50，而 37 局 native 材料 μ 最大 45.8、CV 最大 2.23。看分数时务必先看 `material`。

### 7.2 重采的忠实性

- **37/37** 局的命令流与现有材料逐条一致（比对 `team/operation/action/units/timeMs`，只比补丁前就有的字段，范围裁到旧窗口）：0 条差异。
- 新材料只多两样东西：窗口外的尾部行（原始播放跑到 `replay_end`，评分时按窗口裁掉）与新字段（`x/y`/`targetId`/`buildType`）。
- 7 局 `checksumWarnings > 0`（Mainkheim-07-46 47、Odas-01-02 25、岩浆对峙-09-40 50、Remmy-19-22 284、Remmy-20-29 232、Remmy-07-52 52、Whale-09-32 68）——与上一轮重建**同样的局、同样的次数**，是回放本身的分叉，不是本次采集的问题。命令流仍一致（命令来自回放文件），标 `replay_desync` 提示状态可能分叉。
- 17 局没有回放，永远拿不到坐标。

### 7.3 标定（62 局：13 人类 / 8 脚本 / 41 Agent）

设备：`smoothWindowSeconds = 30`、`c0 = 0.40`、`c1 = 0.95`、`μ0 = 14`、`q0 = 0.15`、`q1 = 0.75`。

| 组 | 样本 | fluency 最小 / P25 / 中位 / P75 / 最大 |
|---|---:|---|
| 人类 | 13 | 46.2 / 72.3 / **83.2** / 86.9 / 91.0 |
| 脚本 ScriptAI | 8 | 91.2 / 96.2 / **99.4** / 99.9 / 100.0 |
| Agent（可比较 24 局） | 24 | 0.0 / — / **—** / — / 68.4 |
| Agent（含 17 局降级） | 41 | 0.0 / 19.3 / **28.8** / 40.2 / 72.9 |

锚点来源：`μ0` = 人类 μ 中位数（27.1）的一半；`q0` = 人类 q 中位数（0.14）向上；`q1` = Agent q 中位数（0.54）略放宽；`c0` = 人类 30 s 窗口 CV 中位数（0.44）下方；`c1` = Agent 窗口 CV 的 P25（0.50）与中位（0.61）之间偏上。

三组分量的中位：

| 组 | μ | q | 窗口 CV |
|---|---:|---:|---:|
| 人类 | 27.1 | 0.14 | 0.44 |
| 脚本 | 100.1 | 0.01 | 0.37 |
| Agent | 14.9 | 0.57 | 0.61 |

已知问题：

- **脚本 7/8 ≥ 95**，`火山-(8p)-…-23-49_scriptai` 90.3（窗口 CV 0.50，略高于 c0）；人类 13 局里 11 局落在 65–90，两端是 `水田2P-09-58`（42.4，q=0.48 近半场发呆）和 `火山-08-02`（90.6）。
- Agent 可比较的 24 局里 4 局 >40（最高 66.9，`10p环湖-09-18-52_pi`，μ 21.3 / q 0.23，接近人类水平，不是指标失真）。
- 17 局降级材料把 μ 抬到最高 110.9，分数不可与原生材料混读；它们的 fluency 仍会算出来，但看 `material` / `warnings` 区分。
- 每局操作数不多，`q` 与窗口 CV 噪声大，锚点取**中位数**而不是均值。
## 8. 这套指标做不到的事

- **不能判断"该做没做"。** 命令流只知道发生了什么，不知道当时有没有空闲工厂、有没有钱、敌人在哪。它衡量节奏，不衡量响应是否及时。
- **不分阶段。** 前期操作天然稀疏、后期密集；没有分段，长局会被前期拖低。
- **不区分"思考"和"卡顿"。** Agent 等待工具返回与人类思考在时间轴上都表现为长间隔。

## 9. 调参顺序

1. 先定口径：`countAttack`、`α`、`spamSeconds`、`bucketSeconds` —— 这几个定了，其他数值才有意义。
2. 看三类对局（脚本 / 人类 / Agent）的间隔分布，定 `T`（人类间隔 P90 附近）。
3. 用分布定 `μ0`、`q0/q1`、`c0/c1`；**先定 `α` 再定 `c0/c1`**，批量压缩会改变间隔分布。
4. 检验：脚本 ≥95，人类 65–90，慢 Agent ≤40，三组区间不重叠；不满足时优先调 `q1` 和 `c1`，其次权重。
5. 冻结成参数快照，同一评测批次内不再变动。
