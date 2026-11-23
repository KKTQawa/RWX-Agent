# 编写 RWX RSI 策略

在 AI 列表选择 **AI RSI**，注册 ID 为 `rwx.ai-rsi`，经济倍率为 1.0。实验写入目录是 [custom/ai_rsi](../../core/src/main/java/com/corrodinggames/rts/game/ai/custom/ai_rsi/)。入口 `ExperimentAi` 继承 `RsiStrategy`。空入口会执行 SDK 默认经营、出兵、分队和战斗。默认逻辑由宿主执行，并遵守同一套观察规则。

## 可扩展的类

策略可继承 `RsiStrategy`，以及其嵌套的 `Economy`、`Production`、`Operations`、`Tactics`、`Logistics`。用 `configure` 安装所需模块。业务状态放在自己的字段里。需随存档保留的状态可通过 `save` 和 `load` 读写最多 128 个字符串键值。编队和运输任务由策略在恢复后重新提出。

| 模块 | 回调 | 作用范围 |
|---|---|---|
| Economy | `plan(view)` | 己方建造者的建造、维修、资源回收和移动。可保留现金，也可保护一笔留给生产的预算 |
| Production | `plan(view, availableCredits)` | 工厂和建筑的出兵、升级、合法动作及集结点 |
| Operations | `plan(view)` | 为己方单位指定编队和目标。未分配单位进入默认编队，结果只在战略节拍或初始化时更新 |
| Tactics | `direct(view, squad)` | 对当前编队索敌、选靶、集火、移动、巡逻、护卫、改攻击模式、使用技能和控制队形 |
| Logistics | `plan(view, squads, active)`、`direct(view, mission)` | 提交或取消任务，选择运输器、乘客、接送点和期限。未覆写的动作由 SDK 运输流程处理 |

默认几个模块都返回委托。只需要改一个决策时，返回针对那个单位的命令，其他单位继续用默认逻辑。需要维持某个单位的当前任务时，返回 `RsiDecision.hold(ids)`。如需长期保持，每次该模块被调用时都返回 HOLD。HOLD 与同一单位的主命令应二选一。命令无效时，未被占用的单位还能使用同轮默认决策。

回调返回 `decision.exclusive()` 时，SDK 跳过这次回调范围内的默认命令。空独占决策可以让整批工厂暂停排产，战术独占只影响当次编队。运输取消或到期后，宿主仍负责将已经上船的乘客送到原卸载点。

## 动作与命令回执

- 从 `unit.actions()` 查找 `kind()` 对应的动作。允许 AI 使用且当前可见的自定义升级或技能可通过 `Order.action(unit.id(), action.id(), point, targetId)` 下达。无单位目标传 `-1`，无点位传 `null`。当 `requiresPoint()` 为真时提供点位。建造和排产分别使用 `Order.build` 和 `Order.produce`。
- 用 `ready()` 检查快照上的可用性。SDK 在提交时重新核对单位归属、动作条件、目标和预算。建造与技能都进入普通引擎命令队列。
- `view.orderFeedback.get(RsiView.Module.PRODUCTION)` 读取生产模块最近一批回执。其他提交模块用对应枚举值。每条回执带原订单、结果和实际提交的单位 ID。编队可以部分提交。每模块每批最多保存 256 条，超出数见 `omitted()`。回执中的 `SUBMITTED` 表示指令已加入队列，完成情况可从之后的动作、队列和单位状态观察。
- `view.own` 含己方当前血量、最大血量和建造比例。 `view.allies` 含通过己方视野判定的盟友位置和基本状态。盟友不参与可下令单位的仲裁。

## 索敌、队形和运输

- `view.search(center, radius)` 返回范围内当前可见目标，`view.canAttack(unit, target)` 筛选武器相性。可用攻击、攻击移动及追击半径、攻击模式来表达主动搜索、进攻或规避。敌方最后观测位置可用作搜索点，失去视野的单位不能用 ID 精确攻击。
- `view.canReach(unit, point)` 检查静态地形连通性。建造和进攻可用 `view.canApproach(unit, point, radius)` 检查目标周边，因为建筑中心或矿点本身可能不可通行。
- `Order.at(..., group, destination)` 使用游戏正常整队路径和编队。 `RsiDecision.formation(units, positions, attackMove)` 为每个单位安排独立位置，可写战列线、屏障、两翼等形状。碰撞、寻路、自动反击和武器结算仍由引擎处理。
- 返回 `Transport(carrier, passengers, pickup, dropoff, untilTick)` 安排运输。任务接手指定运输器和乘客，结束后归还。取消且已有乘客时由默认流程尝试送到原卸载点再交还。自定义 `direct` 可改变路径、装卸节奏与候车点。规划者应选择运输器和乘客都能到达的接送区域。
- 默认节拍沿用经济 25 帧、战术 80 帧、战略 250 帧。 `modules.tacticsEvery(5–600)` 可以用游戏 tick 设置更短或更长的战术节拍。武器和寻路仍每帧由引擎更新。

## 仲裁边界

每个 tick，每个单位最多接受一个主命令，以及可并行的一次攻击模式和一次工厂集结点更改。运输参与者由当前任务独占。重叠编队按顺序先分配已有成员，已被分配的单位不会再分配给后一编队。建造、生产、升级和有费用的技能共用当轮信用点余量；资金与队列在实际执行时仍受引擎校验。

`RsiDecision.Economy` 中 `reserveCredits` 是经济和生产共同保留的现金，`productionCredits` 是建造留给排产的份额，`economyCredits` 是排产留给建造的份额。它们在每轮宏观决策里作为花费底线。生产回调的 `availableCredits` 已扣除适用底线。

SDK 通过只读值和命令提案与策略交换数据。`:core:compileRsiPolicy` 当前用 SDK 和 JDK 单独编译 `custom/ai_d/`，限制直接链接的类。实验运行器负责目录写入和 JVM 权限约束。

接口见 [RsiStrategy](../../core/src/main/java/com/corrodinggames/rts/game/ai/custom/rsi_sdk/RsiStrategy.java)、[RsiView](../../core/src/main/java/com/corrodinggames/rts/game/ai/custom/rsi_sdk/RsiView.java) 和 [RsiDecision](../../core/src/main/java/com/corrodinggames/rts/game/ai/custom/rsi_sdk/RsiDecision.java)。
