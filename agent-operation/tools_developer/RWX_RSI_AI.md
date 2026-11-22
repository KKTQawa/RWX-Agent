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

## 索敌、队形和运输

- `view.search(center, radius)` 返回范围内当前可见目标，`view.canAttack(unit, target)` 筛选武器相性。可用攻击、攻击移动及追击半径、攻击模式来表达主动搜索、进攻或规避。敌方最后观测位置可用作搜索点，失去视野的单位不能用 ID 精确攻击。
- `view.canReach(unit, point)` 检查静态地形连通性。建造和进攻可用 `view.canApproach(unit, point, radius)` 检查目标周边，因为建筑中心或矿点本身可能不可通行。
- `Order.at(..., group, destination)` 使用游戏正常整队路径和编队。 `RsiDecision.formation(units, positions, attackMove)` 为每个单位安排独立位置，可写战列线、屏障、两翼等形状。碰撞、寻路、自动反击和武器结算仍由引擎处理。
- 返回 `Transport(carrier, passengers, pickup, dropoff, untilTick)` 安排运输。任务接手指定运输器和乘客，结束后归还。取消且已有乘客时由默认流程尝试送到原卸载点再交还。自定义 `direct` 可改变路径、装卸节奏与候车点。规划者应选择运输器和乘客都能到达的接送区域。
- 默认节拍沿用经济 25 帧、战术 80 帧、战略 250 帧。 `modules.tacticsEvery(5–600)` 可以用游戏 tick 设置更短或更长的战术节拍。武器和寻路仍每帧由引擎更新。

## 仲裁边界

每个 tick，每个单位最多接受一个主命令，以及可并行的一次攻击模式和一次工厂集结点更改。运输参与者由当前任务独占。重叠编队按顺序先分配已有成员，已被分配的单位不会再分配给后一编队。建造、生产、升级和有费用的技能共用当轮信用点余量；资金与队列在实际执行时仍受引擎校验。

SDK 只返回己方值对象、可见目标、最后观测历史、公开矿点以及静态地形信息。无法从 SDK 得到可写引擎对象。`:core:compileRsiPolicy` 用 SDK 和 JDK 单独编译实验目录，阻止其直接依赖引擎类。实验运行器需另行落实目录写入和 JVM 权限约束。

接口见 [RsiStrategy](../../core/src/main/java/com/corrodinggames/rts/game/ai/custom/rsi/RsiStrategy.java)、[RsiView](../../core/src/main/java/com/corrodinggames/rts/game/ai/custom/rsi/RsiView.java) 和 [RsiDecision](../../core/src/main/java/com/corrodinggames/rts/game/ai/custom/rsi/RsiDecision.java)。
