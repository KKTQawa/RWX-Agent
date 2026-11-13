# 微操配置（`config.json`）

每个 CASE 目录下有一份唯一的 `config.json`：

```text
evaluate/micro/CASE1-duel/config.json
evaluate/micro/CASE2-LTE/config.json
evaluate/micro/CASE3-Transport/config.json
evaluate/micro/CASE4-Retreat/config.json
```

改完直接重新启动一局即可；**不支持热加载**。已经跑完的材料不会因为改配置而变，只有新局使用新值。

## 1. 三段结构

| 段 | 谁读 | 用途 |
|---|---|---|
| `run` | `MicroConfig` | 默认 task/seed/track/模式/预算/ briefing 等启动参数 |
| `evaluation` | 各 CASE 的 `score.py` | 扣分上限、权重、阈值、时长/空闲基线 |
| `map` | 各 CASE 的场景 Java 类 | 地图尺寸、地形/岛屿、兵力、维修湾、防空、矿脉、出生阵型等 |

`run` 是**默认值**：`--case-args` 中显式给出的键优先。没有给 `--case-args` 时，直接用 `config.json.run` 启动。
`--micro-config <另一份.json>` 可以临时换一整套参数，不修改仓库里的默认配置。

## 2. `run` 的键

```json
"run": {
  "task": "4_1_2",
  "seed": 1,
  "track": "realtime",
  "mode": "agent",
  "briefingSeconds": 180,
  "briefingOrders": "allow",
  "gameLimitSeconds": 900,
  "wallLimitSeconds": 900,
  "startTimeoutSeconds": 600
}
```

- `task` 仍然是场景语法：CASE1 `1_<地图1|2>_<level1..4>`、CASE2 `2_<矿脉4..8>_<档次1..5>`、
  CASE3 `3_<type1..4>_<level1..3>`、CASE4 `4_<type1..3>_<level1..3>`。
- `gameLimitSeconds` / `wallLimitSeconds` 写 `null` 表示“用 task 默认值”；写数字就是硬覆盖。
  CASE3 与 CASE4 的所有 type 当前都写 **game 1500 s / wall 1200 s / startTimeout 900 s**，
  时间上限不再由 Java `Spec` 按 type 决定。
- **timeout 对局不评分**：`outcome=="timeout"` 时四个 CASE 的 `evaluate.py` 都写 `score.status="REJECTED"`，
  `total/deduction=null`，只保留原始指标。
- CASE1 还支持 `turnTicks`（或 `turnSeconds`）、`enemyDelaySeconds`；CASE3 没有 briefing 与 begin；
  CASE2/3 只接受 `mode=agent,track=realtime`，CASE4 另外接受 `mode=human`（GUI 人类局）。

## 3. `evaluation` 常用键

| key | 含义 |
|---|---|
| `scoreVersion` / `scoreBaseline` | 评分版本名与 `100 - 扣分` 的基准 |
| `actionDelay` | `cap`、`scale`、`buckets`（`[low, high, weight]`，`high=null` 为开区间） |
| `irrelevant` | `cap` 与 `weights`（violation/failed/waste/noop 等） |
| `cadence` | CASE2 的 `meanSeconds`、`outlierSeconds`、`meanWeight`、`outlierWeight`、`cap` |
| `mechDamage` | CASE1 的 `cap`、`killWeight`、`hpWeight`、`shieldWeight`、`damageScope`（默认 `all`，含阵亡机甲） |
| `collectiveIdle` | CASE1 的 `cap`、`points`、`minSeconds`、`segments`、`fireTauMs` |
| `transportLoss` / `transportIdle` | CASE3 的损失权重、空闲点数/分段；`excludeLoadedReady` / `excludeDecoySorties` |
| `tankLoss` / `tankIdle` | CASE4 的损失系数、空闲权重/最小秒/R；`dropTailInterval` 丢弃最后一个采样到 end 的区间。评分只按 HP 判断是否满血，不读护盾 |
| `duration` | 时长上限、二次函数 `quadraticA`、横坐标 `quadraticSpace`、按 type 的 `byType` 基线 |

CASE3/CASE4 的旧 `baselines.json` 已并入 `evaluation.duration`；`score.py` 只读 `config.json`。

## 4. `map` 的可调项

### CASE1

- `generated.minWidth/maxWidth/minHeight/maxHeight`：程序生成地图的边长范围（格）。
- `generated.cliffsMin/Max`、`poolsMin/Max`：悬崖/水域块数。
- `generated.patchAreaMin/Max`：每块面积；`patchGap`、`spawnClearance`、`centreSpacing`、`maxRetries`。
- `fixedMap`：`task` 第二位为 2 时使用的固定图路径（相对仓库根）。
- `forces.maxPerSide`、`selfType`、`enemyType`、`spawnColumnStep`、`spawnRowStep`。

### CASE2

- `spacing`：矿脉最小间距（格）；`centerClearance`：建造者中心净空。
- `density`：地图边长公式的泊松密度；`credits`：初始资金；`maxSamplingAttempts`。

### CASE3

- `size`：地图边长（格）；`fogMode`：1 为一次性迷雾。
- `targetIsland` / `baseIsland`：`areaMin`、`areaMax`、`centerX`、`centerY`。
- `antiAir`：`arcHalfDegrees`、`coastMinDepth`、`coastMaxDepth`、`minSpacing`、`jitter`。
- `types.<1..4>`：`needs`（类型 → 每级数量）、`transports`、`transportType`、`transportCapacity`、
  `extractors`、`factories`、`credits`、`antiAirTurrets`。

### CASE4

- `subject.type`：任务单位内部名（默认 `bugMeleeT31`，内置自定义单位，无需模组加载）。
- `size.min` / `size.maxExclusive`：地图边长 `[min, maxExclusive)`。
- `region.fraction` / `region.margin`：左上炮塔区的比例与离边界格数。
- `field.radiusMin/Max`、`ellipseRatio`、`baseClearance`：场地椭圆与出生角净空。
- `longRange`：`biasDegrees`、`spreadDegrees`、`randomShare`、`layoutTrials`、`drawAttempts`。
- `spacing`：`long`、`short`、`cross`、`floor`；`jitterTiles`；`layoutVersion`。
- `types.<1..3>`：`tanks`、`bays`、`turrets`（类型 → 每级数量）、`fogMode`。
  `turrets` 的可用字段：`c_turret_t2_gun`、`c_turret_t3_gun`、`c_turret_t2_flame`、
  `c_turret_t1_artillery`、`c_turret_t2_artillery`、`c_turret_t1_lightning`、`c_turret_t2_lightning`。
  不需要的塔写 `0`；数量按 `level` 倍乘。

## 5. 修改时的注意

1. 改 `task` 会同时改场景语法与默认预算；不想动预算时把 `run.gameLimitSeconds` / `wallLimitSeconds` 留 `null`。
2. 改兵力/炮塔/岛屿面积后，旧基线不再可比。CASE3/CASE4 的 `duration.byType` 要跟着重测；CASE4 改落点逻辑后应把 `map.layoutVersion` 加一。
3. 改 `map` 只影响新局；已经收进 `evaluate/output/micro/` 的材料保持原 `meta.json` 不变。
4. `evaluation` 的 cap/权重会改变分数，但不会改变 `result.json` 的事实；报告中的“分数”和“结果”仍分开读。
5. 配置错误会在启动时直接报 `invalid ... config` 或 `Unknown micro option`，不会带着半套参数开局。
6. 同一个进程只允许一局；改完配置必须重启启动器/进程，不能在一局中途改。
