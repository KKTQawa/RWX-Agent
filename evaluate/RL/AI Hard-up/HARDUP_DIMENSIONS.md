# Hard-up v1 与 v3 参数维度

按 rlkit 的 ParamCodec 编码顺序列出。序号从 1 开始，默认值来自当前参数文件。数值范围列使用编码器实际网格，类型用编码器的 int 或 float。配置开关未计入维度。

## Hard-up v1

[参数文件](params_Hardupv1.json)。共 **29 维**，8 个数值旋钮和 21 个兵种权重。

### 数值旋钮

| 维度 | JSON 字段 | 默认 | 实际网格范围 | 步长 | 类型 |
|---:|---|---:|---:|---:|---|
| 1 | `definition.cadence.economy` | 15 | 10–120 | 5 | float |
| 2 | `definition.cadence.tactics` | 80 | 30–300 | 5 | float |
| 3 | `definition.cadence.strategy` | 250 | 90–900 | 5 | float |
| 4 | `building.attemptIntervalFrames` | 175 | 100–650 | 5 | float |
| 5 | `upgrades.intervalFrames` | 255 | 100–1800 | 5 | float |
| 6 | `units.maxPerCycle` | 12 | 2–40 | 1 | float |
| 7 | `upgrades.bankCredits` | 3900 | 3000–5000 | 100 | float |
| 8 | `upgrades.maxPerCycle` | 0 | 0–6 | 1 | float |

### 兵种权重

这一组使用 softmax。编码范围统一为 **±3.3210579**，原始权重总和为 **20.89**。解码权重按两位小数写入，并应用单项上限和 `0.01` 正数下限。直接评测使用文件原值。

| 维度 | `units.weights` 下的 ID | 默认权重 | 文件声明范围 |
|---:|---|---:|---:|
| 9 | `c_tank` | 0.28 | 0–10 |
| 10 | `hoverTank` | 0.4 | 0–10 |
| 11 | `heavyTank` | 0.63 | 0–10 |
| 12 | `heavyHoverTank` | 0.06 | 0–10 |
| 13 | `c_artillery` | 0.12 | 0–10 |
| 14 | `plasmaTank` | 6.04 | 0–10 |
| 15 | `missileTank` | 0.06 | 0–10 |
| 16 | `c_laserTank` | 1.13 | 0–10 |
| 17 | `scout` | 0 | 0–10 |
| 18 | `mechGun` | 0 | 0–10 |
| 19 | `mechMissile` | 1.75 | 0–10 |
| 20 | `mechArtillery` | 0.82 | 0–10 |
| 21 | `mechMinigun` | 0.43 | 0–10 |
| 22 | `mechBunker` | 0.3 | 0–10 |
| 23 | `c_interceptor` | 0.21 | 0–10 |
| 24 | `heavyInterceptor` | 0 | 0–10 |
| 25 | `gunShip` | 0 | 0–10 |
| 26 | `amphibiousJet` | 0.06 | 0–10 |
| 27 | `battleShip` | 0.19 | 0–10 |
| 28 | `missileShip` | 2.33 | 0–10 |
| 29 | `attackSubmarine` | 6.04 | 0–10 |

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
| 29 | `impossible.globalTimerExtraDecay` | 4 | 0–12 | 0.5 | float |
| 30 | `impossible.builderGroupMaxUnits` | 10 | 4–16 | 1 | int |
| 31 | `impossible.attackGroupMaxUnitsNarrow` | 14 | 8–24 | 1 | int |
| 32 | `impossible.attackGroupMaxUnitsWide` | 18 | 10–32 | 1 | int |
| 33 | `impossible.seaGroupMaxUnits` | 10 | 4–20 | 1 | int |
| 34 | `impossible.productionIdleUnitsLimit` | 65 | 20–150 | 1 | int |
| 35 | `impossible.productionWaterUnitsLimit` | 16 | 4–40 | 1 | int |
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
