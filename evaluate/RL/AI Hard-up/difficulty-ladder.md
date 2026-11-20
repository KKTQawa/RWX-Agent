# 难度阶梯审计：六个原版难度到底差在哪

结论先说：**原版六个难度不是六套 AI，而是一个大脑 + 两个判定谓词。**
除收入倍率外，全部差异只有 8 处硬编码判定（7 处只给 Impossible、1 处只给 Very Hard 及以上），
"闸门"（`AiPhase` 四阶段）在六个原版难度之间**完全相同**——闸门只存在于自定义 AI（`AiRlConfig.overrides`）。

审计日期 2026-11-19，基于当前仓库代码；行号随重构会漂移，关键符号名不会。

## 一、定义层：只有 code / 名字 / 收入不同

`AiRegistry` 注册六个原版（`core/.../ai/strategy/AiRegistry.java:16-21`），每个都走
`AiDefinition.original(...)`（`AiDefinition.java:44-47`）：

| 字段 | 六个难度的值 | 是否不同 |
|---|---|---|
| `factory` | `null`（走 native `AIController`，没有自定义回调） | 同 |
| `originalPhases` | `EnumSet.allOf(AiPhase.class)` —— INITIALIZATION / ECONOMY / TACTICS / STRATEGY 全开 | **同** |
| `cadence` | `AiCadence.STANDARD` = 25 / 80 / 250 帧 | **同** |
| `originalDifficulty` | 就等于 code（-2…3） | 不同（但只是把 code 传下去） |
| `id` / 名字 | 六个 | 不同（展示用） |
| `incomeMultiplier` | `legacyIncome(code)` | **不同** |

收入表（`AiRegistry.java:70-74`：`code > 0 ? 1 + 0.4·code : 1 + 0.3·code`，`code == 3` 再 `+1.5`）：

| 难度 | code | 定义收入倍率 | 相对上一档 |
|---|---|---|---|
| 非常简单 Very Easy | -2 | 0.4 | — |
| 简单 Easy | -1 | 0.7 | ×1.75 |
| 中等 Medium | 0 | 1.0 | ×1.43 |
| 困难 Hard | 1 | 1.4 | ×1.4 |
| 非常困难 Very Hard | 2 | 1.8 | **×1.286（+28.6%）** |
| 不可能 Impossible | 3 | **3.7** | **×2.06** |

`Hard → Impossible` 是 ×2.64 的收入差。这是整个阶梯里最大的一段，也是"调参能不能打赢 Impossible"的
真实障碍：**难度提升基本靠钱，不靠脑子。**

## 二、引擎层：两个谓词、八处判定

`AIController.java:377-384`：

- `isInsaneDifficulty()`：`code == 3 || code > 300`
- `isHardOrAboveDifficulty()`：`code >= 2`

除此之外整个代码库没有任何地方按难度分叉：`difficultyLevel` 的另一处用途只是
`AiRegistry.find(...)` 查定义（`AIController.java:1386-1407`），行为上的消费者只有上面两个谓词
（全仓 `grep` 验证）。

| # | 位置 | 生效难度 | 普通 | 该难度 | 实际影响 |
|---|---|---|---|---|---|
| 1 | `AIController.java:1688-1690` | Impossible | `globalTimer` 每帧 −1 | 额外再 −4/帧（共 5×） | 资源前哨 / 扩张决策频率 ×5 |
| 2 | `AIController.java:2190-2195` | Impossible | 建造编组 `maxUnits = 8` | 10 | 同时施工的工程车更多 |
| 3 | `AIController.java:2199-2216` | Impossible | 首个陆军攻击编组 3 / 5 / 7 | 14（内部计数 <25）或 18（≥25） | 第一次进攻的集结体量翻倍 |
| 4 | `AIController.java:2218-2226` | Impossible | 海军攻击编组 `maxUnits = 5` | 10 | 跨海投送翻倍 |
| 5 | `BaseZone.java:1344-1346` | Impossible | `defensiveScore` 重置 270 + … | 190 + … | 建造/回收决策周期缩短 29.6% |
| 6 | `BaseZone.java:1439-1444` | Impossible | 生产闸门 `<50` / `<12` | `<65` / `<16` | 存量上限更高，继续排产的窗口更长 |
| 7 | `BaseZone.java:418-430` | Impossible | 第 4 座防空塔 0.02/4 ≈ 0.005（等于不建） | 0.3/4 = 0.075 | 真的会补第 4 座防空 |
| 8 | `BaseZone.java:463-470` | **Very Hard 及以上** | 实验室 `experimentalLandFactory` 不打分 | 0.04（>15000 钱）/ 0.03（>55000 第二座） | 只有 VH / Impossible 会开实验单位 |

于是行为上其实只有 **3 个档**：

- `code < 2`（很简单 / 简单 / 中等 / 困难）：除收入外**完全同一套行为**
- `code == 2`（非常困难）：同上，再加第 8 条
- `code == 3 or > 300`（不可能）：同上，再加第 1–7 条

即：**Hard → Very Hard 只多了一条"有钱就造实验室"；Very Hard → Impossible 多了七条。**
"Hard 打 Very Hard"在公平前提下要克服的是 28.6% 收入差 + 对面会补实验单位；
"Hard 打 Impossible"要克服 2.64× 收入差 + 七条体量/节奏优势。

## 三、完全相同的部分（不用再找）

- 建筑打分表：`BaseZone.getBestBuildingToBuild` 的全套优先级（0.48 / 0.47 / 0.42 / 0.29 / 0.02…）与
  `credits` 分档门槛（1300 / 1700 / 2100 / 2800 / 3100 / 4800…）
- 兵种混编与抽取：`UnitBuildStrategy`
- 进攻判定：`isReadyForAttack` / `hasSufficientUnitsForAttack` / `isAttackBlockedByConditions` /
  `shouldLaunchAttack`
- 升级节拍：≥4100 钱、每次升级后 900 帧冷却、2400 帧兜底重试（`AIController.java:1786-1788 / 1883-1884`）
- 基地半径、侦察/扫描节拍、运输编组、核弹与反导逻辑、`maxPerType` 之类的隐式上限
- 四阶段节拍 25 / 80 / 250 帧；六个难度的闸门都是全开

> 注：`custom/very_hard_1income` 等六个类的注释写了"升级阈值"随难度变化——那是猜的，实际没有。
> 升级节拍对所有难度相同（这也是 `params.json` 里 `upgrades.intervalFrames` 值得调的原因：
> 它本来就是同一条常量 900）。

## 四、几个容易踩的点

1. **`code > 300` 也算 Impossible**：自定义 AI 的编号如果 ≥301（`AiDefinition.custom` 只要求 ≥4），
   会意外获得"不可能"的七条分支。当前自定义 AI 用 4–13 与 20，没问题。
2. **难度码同时是 `teamColorId`**：AI 队的 `teamColorId` 被挪用存难度（`PlayerTeam.getTeamColorId()`
   在 `isTeamLocked` / 网络局时返回 `teamPingTime`），所以难度既走房间设置 `aiDifficulty`，
   也走每队的 `teamPingTime`，存档/回放读的是这个数。改难度等于改这个 int。
3. **自定义 AI 继承的是行为档，不是收入**：`AiRlConfig` 的 `meta.base` / `baseDifficulty` 只决定
   `originalDifficulty`（即上面八条判定走哪一档）；收入由 `definition.incomeMultiplier` 单独给，
   缺省才继承基类的值。
4. **收入倍率的挂载点在队对象上**（`PlayerTeam.java:1246` + `1110-1124`）：只有 `AIController` 实例
   才拿得到定义倍率，槽 0 是本地玩家队对象。详见 `evaluate/RL/README.md` §8.3。
5. **公平打 VH / Impossible 今天就能做**：`rwx.ai-very-hard-1income`（code 12）与
   `rwx.ai-impossible-1income`（code 13）就是"同难度大脑 + 收入 1.0"（
   `custom/very_hard_1income/CustomVeryHard1IncomeStrategy.java:39-48`）。
   把它们放在槽 1 当对手时，槽 1 的定义倍率就是 1.0，**两个槽位收入真的相同**——不必先改
   `PlayerTeam` 才能做公平对局：

   ```powershell
   python "evaluate/RL/AI Hard-up/optimize.py" probe --versus rwx.ai-very-hard-1income `
     --maps "Lake (2p)" --seeds 2026,1331 --max-ticks 40000 --sampling 1000
   ```

   只有"任意定义 × 任意定义、且两边都要吃各自倍率"才需要改 `PlayerTeam` / rollout spec。
6. **槽位还有 teamId 相位偏移**（`AIController.java:937-951`：经济 50+2·teamId、战术 100+9·teamId、
   战略 202+19·teamId、扩张 3500+5·teamId）：这是"哪个槽"的差异，不是难度差异；
   首个战略相位最多差约 48 帧（<1 秒），不要拿它解释胜负。

## 五、对调参任务的含义

- 想在**公平**前提下"提升 Hard 能力"，能动的只有决策质量（建造顺序、配比、升级前置、编组），
  而不是难度档位——把 `baseDifficulty` 改成 2 只是"偷"第 8 条，等于换 AI 而不是调参；
  而且 `definition.incomeMultiplier` 缺省会继承基类，收入同时从 1.4 变成 1.8，那就更不是公平比较了。
- 想验证"能不能打赢 Very Hard"，用 `rwx.ai-very-hard-1income` 当对手才是干净的对照：
  两边 1.0 收入，差异只剩脑子。
- 想凭空补上 2.64× 收入差是不现实的；`params.json` 里 `_notTunable` 列的那些
  （编组集结/进攻节奏、建筑评分、基地半径、扫描冷却）才是脑子真正的分档点，都在官方代码里。
