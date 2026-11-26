# Hard-up 参数维度

按 rlkit 的 ParamCodec 编码顺序列出。序号从 1 开始，默认值来自当前参数文件。数值范围列使用编码器实际网格，类型用编码器的 int 或 float。配置开关未计入维度。

## Hard-up v1

[参数文件](params_Hardupv1.json)。共 **29 维**，8 个数值旋钮和 21 个兵种权重。

### 数值旋钮

| 维度 | JSON 字段 | 默认 | 实际网格范围 | 步长 | 类型 |
|---:|---|---:|---:|---:|---|
| 1 | `definition.cadence.economy` | 25 | 10–120 | 5 | float |
| 2 | `definition.cadence.tactics` | 80 | 30–300 | 5 | float |
| 3 | `definition.cadence.strategy` | 250 | 90–900 | 5 | float |
| 4 | `building.attemptIntervalFrames` | 270 | 100–650 | 5 | float |
| 5 | `upgrades.intervalFrames` | 250 | 100–1800 | 5 | float |
| 6 | `units.maxPerCycle` | 12 | 2–40 | 1 | float |
| 7 | `upgrades.bankCredits` | 4100 | 3000–5000 | 100 | float |
| 8 | `upgrades.maxPerCycle` | 0 | 0–6 | 1 | float |

### 兵种权重

这一组使用 softmax。编码范围统一为 **±3.0**，原始权重总和为 **21.00**。解码权重按两位小数写入，并应用单项上限和 `0.01` 正数下限。直接评测使用文件原值。

| 维度 | `units.weights` 下的 ID | 默认权重 | 文件声明范围 |
|---:|---|---:|---:|
| 9 | `c_tank` | 1.0 | 0–10 |
| 10 | `hoverTank` | 1.0 | 0–10 |
| 11 | `heavyTank` | 1.0 | 0–10 |
| 12 | `heavyHoverTank` | 1.0 | 0–10 |
| 13 | `c_artillery` | 1.0 | 0–10 |
| 14 | `plasmaTank` | 1.0 | 0–10 |
| 15 | `missileTank` | 1.0 | 0–10 |
| 16 | `c_laserTank` | 1.0 | 0–10 |
| 17 | `scout` | 1.0 | 0–10 |
| 18 | `mechGun` | 1.0 | 0–10 |
| 19 | `mechMissile` | 1.0 | 0–10 |
| 20 | `mechArtillery` | 1.0 | 0–10 |
| 21 | `mechMinigun` | 1.0 | 0–10 |
| 22 | `mechBunker` | 1.0 | 0–10 |
| 23 | `c_interceptor` | 1.0 | 0–10 |
| 24 | `heavyInterceptor` | 1.0 | 0–10 |
| 25 | `gunShip` | 1.0 | 0–10 |
| 26 | `amphibiousJet` | 1.0 | 0–10 |
| 27 | `battleShip` | 1.0 | 0–10 |
| 28 | `missileShip` | 1.0 | 0–10 |
| 29 | `attackSubmarine` | 1.0 | 0–10 |

## Hard-up v3

[参数文件](params_Hardupv3.json)。共 **85 维**，59 个数值旋钮和 26 个兵种权重。

### 数值旋钮

| 维度 | JSON 字段 | 默认 | 实际网格范围 | 步长 | 类型 |
|---:|---|---:|---:|---:|---|
| 1 | `definition.cadence.economy` | 25 | 10–120 | 5 | float |
| 2 | `definition.cadence.tactics` | 80 | 30–300 | 5 | float |
| 3 | `definition.cadence.strategy` | 250 | 90–900 | 5 | float |
| 4 | `building.attemptIntervalFrames` | 270 | 120–650 | 5 | int |
| 5 | `upgrades.intervalFrames` | 250 | 100–1800 | 5 | int |
| 6 | `units.maxPerCycle` | 12 | 1–20 | 1 | int |
| 7 | `upgrades.bankCredits` | 4100 | 3000–5000 | 100 | float |
| 8 | `upgrades.maxPerCycle` | 0 | 0–6 | 1 | float |
| 9 | `buildingScore.extractorFirst` | 0.98 | 0.6–0.99 | 0.01 | float |
| 10 | `buildingScore.extractorNext` | 0.25 | 0.1–0.6 | 0.01 | float |
| 11 | `buildingScore.landFactoryFirst` | 0.8 | 0.35–0.95 | 0.01 | float |
| 12 | `buildingScore.landFactoryNext` | 0.46 | 0.2–0.8 | 0.01 | float |
| 13 | `buildingScore.airFactoryFirst` | 0.48 | 0.25–0.9 | 0.01 | float |
| 14 | `buildingScore.airFactoryNext` | 0.29 | 0.15–0.6 | 0.01 | float |
| 15 | `buildingScore.seaFactoryFirst` | 0.3 | 0.1–0.7 | 0.01 | float |
| 16 | `buildingScore.seaFactoryNext` | 0.1 | 0.05–0.3 | 0.01 | float |
| 17 | `buildingScore.turretFirst` | 0.47 | 0.2–0.9 | 0.01 | float |
| 18 | `buildingScore.turretNext` | 0.35 | 0.15–0.7 | 0.01 | float |
| 19 | `buildingScore.antiAirFirst` | 0.42 | 0.2–0.85 | 0.01 | float |
| 20 | `buildingScore.antiAirNext` | 0.3 | 0.12–0.6 | 0.01 | float |
| 21 | `buildingScore.laserDefenceFirst` | 0.018 | 0.011–0.05 | 0.001 | float |
| 22 | `buildingScore.repairbayFirst` | 0.02 | 0.011–0.05 | 0.001 | float |
| 23 | `buildingScore.fabricatorFirst` | 0.11 | 0.03–0.35 | 0.01 | float |
| 24 | `buildingScore.fabricatorNext` | 0.07 | 0.02–0.25 | 0.005 | float |
| 25 | `buildingScore.antiNukeFirst` | 0.06 | 0.02–0.2 | 0.005 | float |
| 26 | `buildingScore.antiNukeNext` | 0.05 | 0.02–0.15 | 0.005 | float |
| 27 | `buildingScore.experimentalFirst` | 0.04 | 0.02–0.2 | 0.005 | float |
| 28 | `buildingScore.experimentalNext` | 0.03 | 0.01–0.15 | 0.005 | float |
| 29 | `impossible.globalTimerExtraDecay` | 0 | 0–12 | 0.5 | float |
| 30 | `impossible.builderGroupMaxUnits` | 8 | 4–16 | 1 | int |
| 31 | `impossible.attackGroupMaxUnitsNarrow` | 7 | 6–24 | 1 | int |
| 32 | `impossible.attackGroupMaxUnitsWide` | 7 | 6–32 | 1 | int |
| 33 | `impossible.seaGroupMaxUnits` | 5 | 4–20 | 1 | int |
| 34 | `impossible.productionIdleUnitsLimit` | 50 | 20–150 | 1 | int |
| 35 | `impossible.productionWaterUnitsLimit` | 12 | 4–40 | 1 | int |
| 36 | `units.reserveCredits` | 0 | 0–3000 | 100 | int |
| 37 | `tactics.intervalFrames` | 800 | 180–1600 | 20 | int |
| 38 | `tactics.retreatHpPercent` | 50 | 10–55 | 5 | int |
| 39 | `tactics.resumeHpPercent` | 60 | 60–95 | 5 | int |
| 40 | `tactics.stagingDistance` | 720 | 450–1600 | 10 | int |
| 41 | `reference.productionAttemptsPerCycle` | 12 | 4–20 | 1 | int |
| 42 | `reference.reclaimScoreCap` | 3.5 | 3.5–5 | 0.05 | float |
| 43 | `reference.attackCreditThresholds.highCredits` | 1300 | 800–2300 | 50 | int |
| 44 | `reference.attackCreditThresholds.highScore` | 1 | 0.5–1.5 | 0.05 | float |
| 45 | `reference.attackCreditThresholds.lowCredits` | 300 | 200–550 | 50 | int |
| 46 | `reference.attackCreditThresholds.lowScore` | 3 | 2–3.5 | 0.05 | float |
| 47 | `reference.builderGroupSize.normal` | 1 | 1–2 | 1 | int |
| 48 | `reference.builderGroupSize.aggressive` | 2 | 1–2 | 1 | int |
| 49 | `reference.builderGroupSize.established` | 2 | 2–3 | 1 | int |
| 50 | `reference.builderGroupSize.large` | 3 | 3–5 | 1 | int |
| 51 | `reference.groupCapacity.landFirst` | 3 | 2–6 | 1 | int |
| 52 | `reference.groupCapacity.landSecond` | 5 | 3–10 | 1 | int |
| 53 | `reference.groupAttackDelayFrames` | 1000 | 300–3000 | 50 | int |
| 54 | `reference.groupRecruitFrames` | 200 | 100–700 | 10 | int |
| 55 | `reference.groupPatrolFrames` | 4000 | 800–8000 | 50 | int |
| 56 | `reference.groupCombatLifetime.minUnits` | 3 | 1–6 | 1 | int |
| 57 | `reference.groupCombatLifetime.attackFrames` | 1000 | 500–4000 | 100 | int |
| 58 | `reference.groupCombatLifetime.totalAttackFrames` | 11000 | 6000–24000 | 100 | int |
| 59 | `reference.attackMoveChance` | 80 | 50–95 | 1 | int |

### 兵种权重

这一组使用 softmax。编码范围统一为 **±3**，原始权重总和为 **26**。解码权重按两位小数写入，并应用单项上限和 `0.01` 正数下限。直接评测使用文件原值。

| 维度 | `units.weights` 下的 ID | 默认权重 | 文件声明范围 |
|---:|---|---:|---:|
| 60 | `c_tank` | 1 | 0–10 |
| 61 | `hoverTank` | 1 | 0–10 |
| 62 | `heavyTank` | 1 | 0–10 |
| 63 | `heavyHoverTank` | 1 | 0–10 |
| 64 | `c_artillery` | 1 | 0–10 |
| 65 | `plasmaTank` | 1 | 0–10 |
| 66 | `missileTank` | 1 | 0–10 |
| 67 | `c_laserTank` | 1 | 0–10 |
| 68 | `scout` | 1 | 0–10 |
| 69 | `mechGun` | 1 | 0–10 |
| 70 | `mechMissile` | 1 | 0–10 |
| 71 | `mechArtillery` | 1 | 0–10 |
| 72 | `mechMinigun` | 1 | 0–10 |
| 73 | `mechBunker` | 1 | 0–10 |
| 74 | `c_interceptor` | 1 | 0–10 |
| 75 | `heavyInterceptor` | 1 | 0–10 |
| 76 | `gunShip` | 1 | 0–10 |
| 77 | `amphibiousJet` | 1 | 0–10 |
| 78 | `battleShip` | 1 | 0–10 |
| 79 | `missileShip` | 1 | 0–10 |
| 80 | `attackSubmarine` | 1 | 0–10 |
| 81 | `fireBee` | 1 | 0.01–10 |
| 82 | `experimentalHoverTank` | 1 | 0.01–10 |
| 83 | `c_experimentalTank` | 1 | 0.01–10 |
| 84 | `experimentalDropship` | 1 | 0.01–10 |
| 85 | `experimentalSpider` | 1 | 0.01–10 |

`tactics.intervalFrames` 与 `reference.groupOrderFrames` 对应同一参数。工兵、海上和后两档陆攻编队容量沿用 `impossible` 中的各自维度。

## Hard-up v4

[参数文件](params_Hardupv4.json)。共 **103 维**，77 个数值参数和 26 个兵种权重。前 59 个数值参数及兵种权重沿用 v3。下表所有范围均为搜索网格，端点包含在内。距离用世界单位，计时用游戏帧。

### 维度简表

| 参数组 | 维度 |
|---|---:|
| 经济、战术、战略节拍 | 3 |
| 建造尝试间隔 | 1 |
| 升级门槛、间隔、每轮上限、普通抽签倍率 | 4 |
| 每轮战斗单位生产上限 | 1 |
| 建筑选型评分 | 20 |
| Impossible 分支参数 | 7 |
| 单位生产预留资金 | 1 |
| 战术与战斗控制 | 4 |
| 兵种相对权重 | 26 |
| 原版硬编码编队相关 | 13 |
| 原版硬编码生产相关 | 6 |
| 水域判定门槛 | 1 |
| 基地半径、前哨数量及扫描冷却 | 7 |
| 建造失败重试与通用选址 | 3 |
| 海工厂选址半径 | 2 |
| 运输编组、超时与落点抖动 | 4 |
| **合计** | **103** |

### 新增参数及建造间隔沿用项

| `ai.json` 字段 | Hard 默认（v4） | Impossible 原版 | 搜索范围 | 步长 | 类型 | 引擎实际作用 |
|---|---:|---:|---:|---:|---|---|
| `pathfindingOverloadThreshold` | 3000 | 3000 | 1000–8000 | 250 | 整数 | 最大连通可航水域格数严格大于门槛时，触发相关海军和运输决策。 |
| `baseRadius` | 420 | 420 | 320–600 | 20 | 整数 | 四种主基地创建路径使用的区域半径。 |
| `resourceOutpostRadius` | 360 | 360 | 260–500 | 20 | 整数 | 开局补建和定期扫描创建资源前哨时的半径。 |
| `frontOutpostRadius` | 310 | 310 | 220–480 | 10 | 整数 | 定期扫描创建前沿据点时的半径。 |
| `maxResourceOutposts` | 2 | 2 | 0–5 | 1 | 整数 | 所有 `Pre` 基地区域数超过该值时，重置为 300 原版计时单位后再扫。设为 0 仍允许在没有筹建区时扩张。 |
| `maxFrontOutposts` | 3 | 3 | 0–6 | 1 | 整数 | 同时存在的前沿据点上限，0 关闭创建。 |
| `resourceScanCooldownFrames` | 2000 | 2000 原版计时单位，衰减换算 400 帧 | 600–5000 | 100 | 整数 | 成功建区后到下一次扫描的有效等待，受策略更新节拍取整。 |
| `frontScanCooldownFrames` | 5000 | 5000 | 1500–10000 | 250 | 整数 | 成功建前沿据点后的扫描等待，失败或满额重试仍用原版 100 帧。 |
| `buildingBaseIntervalFrames` | 270 + 区域 ID % 15 | 190 + 区域 ID % 15 | 120–650（基础值） | 5 | 整数 | 已使用 `building.attemptIntervalFrames`，该轴还保留区域偏移和低评分延迟。 |
| `buildingFailureBackoffFrames` | 120 | 120 | 0–120 | 20 | 整数 | 建造失败时从剩余计时减去该值，值越大越早重试。 |
| `placementAttempts` | 15 | 15 | 10–25 | 1 | 整数 | 原版随机选址循环的总预算。资源点专用选址走原路径。 |
| `fabricatorClusterAttempts` | 6 | 6 | 0–8 | 1 | 整数 | 前几次优先沿现有制造器聚类，0 只做通用选址。 |
| `navalRadiusStart` | 600 | 600 | 400–800 | 20 | 整数 | 海工厂的起始选址半径。 |
| `navalRadiusStep` | 100 | 100 | 50–125 | 25 | 整数 | 每次海工厂选址失败后扩大半径的步长。 |
| `transporterGroups.max` | 3 | 3 | 0–6 | 1 | 整数 | 每队同时存在的运输组数量上限，0 关闭创建。 |
| `transporterGroups.capacity` | 1 | 1 | 1–3 | 1 | 整数 | 每运输组目标运输载具数。每个载具的乘员容量取自单位定义。 |
| `transporterTimeoutFrames` | 1700 | 1700 | 1700–3200 | 100 | 整数 | 开始卸载后累计的任务超时，保留 600、1200 帧后的二次扩大搜索。 |
| `transporterDropTolerance` | 40 | 40 | 20–80 | 10 | 整数 | 初次卸载目标在 X、Y 各自独立采样 ±该值。移动指令的 40 和发卸载令的 80 距离保持原值。 |
| `upgradeActionProbabilityScale` | 1.0 | 同一原版抽签 | 0.50–1.50 | 0.05 | 浮点 | 普通升级每个合格候选的抽签概率倍率。 |

### 参数之间的约束

- 资源扫描的成功等待与 v3 的 `impossible.globalTimerExtraDecay` 原本作用于同一个计时器。v4 在成功创建资源前哨时按 `等待帧数 × (1 + 额外衰减率)` 装载计时器，使该次等待独立于衰减率。继承的衰减率继续控制开局等待和筹建拥堵后的重试。v3 和内置难度沿用原版装载值，Impossible 以 5 倍速消耗资源扫描计时器。
- 主基地、资源前哨与前沿据点半径描述三类区域。区域覆盖变化会影响后续选址、归属和局部单位计数。资源前哨的固定威胁检查半径是另一个 360 常量，继续使用原值。
- 建造失败扣减上限取 v3 建造基础间隔的下限，避免搜索组合产生负冷却。两项选址预算保证至少两次留给通用选址。海工厂候选搜索半径上界为 `navalRadiusStart + (placementAttempts - 1) × navalRadiusStep`，默认 2000，上界 3800，地图边界和原版建造合法性仍逐次检查。
- 水域门槛是地图特征。实测 Crossing 3678 格、Large Ice Outcrop 1308 格、Volcano 7686 格、Lake 3883 格，均可在 1000–8000 的搜索网格内跨过切换点。海工厂建筑打分、补海军门槛、海上进攻组容量分别决定优先级、生产和编组规模。运输组数和组容量分别改变并行任务上限和每组可招募载具数，实际受可用运输单位限制。

### 升级概率与公平性

原版普通分支使用 0 到 99 的整数抽签，比较的是 `roll > threshold`。阈值已经包含余额、采掘器和首座二级空厂偏好。v4 先按实际能通过的整数点数计算概率，再乘倍率并四舍五入，保留 89% 的原版概率上限和零概率候选。倍率 1.0 保留原阈值。比如普通默认阈值 94 有五个成功点，倍率 1.5 时变为 8%。高优先级动作分支沿用原版抽签。

`upgrades.bankCredits` 决定触发评估的资金门槛，`upgrades.intervalFrames` 决定评估节拍，`upgrades.maxPerCycle` 决定每轮发出的上限。倍率只作用于普通候选的选择。资金支付、动作可用性、禁用项检查、单位科技与升级用时、成功后 900 帧冷却均走原逻辑。它可以改变策略强度，收入、价格和可用动作权限仍遵循相同对局规则。该分支在 Hard 和 Impossible 上使用相同的概率规则。

源码位置见 [AIController](../../../core/src/main/java/com/corrodinggames/rts/game/ai/AIController.java)、[BaseZone](../../../core/src/main/java/com/corrodinggames/rts/game/ai/BaseZone.java)、[AIStrategyNode](../../../core/src/main/java/com/corrodinggames/rts/game/ai/AIStrategyNode.java)、[TransporterGroup](../../../core/src/main/java/com/corrodinggames/rts/game/ai/TransporterGroup.java)、[PathCostMap](../../../core/src/main/java/com/corrodinggames/rts/gameFramework/pathfinding/PathCostMap.java)。
