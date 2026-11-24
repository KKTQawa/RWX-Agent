package com.corrodinggames.rts.game.ai.strategy;

import com.corrodinggames.rts.game.ai.AIController;

/**
 * 原版 <b>Impossible</b> 难度专有的 7 个硬编码分支的取值表。
 *
 * <p>调用点的写法固定为“我们的类优先，原版兜底”：</p>
 * <pre>
 * if (rwxImpossibleBranches().isEnabled()) {
 *     value = rwxImpossibleBranches().xxx();      // 本类
 * } else if (isInsaneDifficulty()) {
 *     value = 原版字面量;                          // 原版 Impossible 分支，一字未动
 * }
 * </pre>
 *
 * <p>也就是说：flag 关闭（默认）时完全等于原版，只有 Impossible 走原版分支；
 * flag 打开时任何难度都先吃本类的值。原版分支代码保持原样，没有把字面量搬进本类。</p>
 *
 * <table>
 *   <caption>7 个分支</caption>
 *   <tr><th>#</th><th>分支</th><th>原版非 Impossible</th><th>原版 Impossible = 本类默认</th></tr>
 *   <tr><td>1</td><td>globalTimer 每帧额外衰减</td><td>0</td><td>4.0（叠在基础 1.0 上 → 合计 5×）</td></tr>
 *   <tr><td>2</td><td>防空炮塔放宽</td><td>最多 3 座，第 4 座 0.02÷n</td><td>放宽到 4 座，且不走 0.02 衰减支</td></tr>
 *   <tr><td>3</td><td>工兵队规模</td><td>8</td><td>10</td></tr>
 *   <tr><td>4</td><td>进攻群规模（第 6 支起的陆攻群，<b>不是地图宽度</b>）</td><td>7</td><td>组序&lt;25 时 14 / 否则 18</td></tr>
 *   <tr><td>5</td><td>海上投送群规模</td><td>5</td><td>10</td></tr>
 *   <tr><td>6</td><td>防守分基数</td><td>270</td><td>190（更早转防守姿态）</td></tr>
 *   <tr><td>7</td><td>生产闸门（<b>一个是计时器、一个是建筑数，都不是单位数</b>）</td><td>{@code unitProductionTimer<50}、{@code buildingCount<12}</td><td>&lt;65、&lt;16</td></tr>
 * </table>
 *
 * <p>第 2 条在 {@code BaseZone} 的打分 if 链里，原版分支保持原样；本类只提供
 * {@link #wideAntiAir(AIController)}（flag 或 Impossible）给参数化打分表用。</p>
 *
 * <p>用法：</p>
 * <pre>
 * public class MyImpossible extends AiImpossibleBranches {
 *     public MyImpossible() { defensiveScoreBase = 150f; enable(); }
 * }
 * // AiStrategy 里 return MyImpossible 实例即可
 * </pre>
 */
public class AiImpossibleBranches {

    /** 没有自定义 AI 时共用的实例：enabled=false，行为=原版。 */
    public static final AiImpossibleBranches ORIGINAL = new AiImpossibleBranches();

    private boolean enabled;

    // ---- 旋钮：默认值 = 原版 Impossible ----

    /** 第 1 条：每帧额外衰减（原版在基础衰减后再次调用 4.0f）。 */
    protected float globalTimerExtraDecay = 4.0f;

    /** 第 3 条：一队工程兵能同时干多少活。 */
    protected int builderGroupMaxUnits = 10;

    /** 第 4 条：陆攻群规模。参数是 {@code AIController.mapWidth}——<b>已创建的陆攻群计数，不是地图宽度</b>。 */
    protected int attackGroupMaxUnitsNarrow = 14;

    /** 第 4 条：同上，组序 ≥ 25 之后用的档。 */
    protected int attackGroupMaxUnitsWide = 18;

    /** 第 5 条：海上/运输投送群规模。 */
    protected int seaGroupMaxUnits = 10;

    /** 第 6 条：防守分基数（越低越早转防守，建造节拍也更密）。 */
    protected float defensiveScoreBase = 190.0f;

    /** 第 7 条：补兵闸门，比的是 {@code AIController.unitProductionTimer}（帧），<b>不是单位数</b>。 */
    protected int productionIdleUnitsLimit = 65;

    /** 第 7 条：补海军闸门，比的是 {@code AIController.buildingCount}，<b>不是水面单位数</b>。 */
    protected int productionWaterUnitsLimit = 16;

    /**
     * 第 8 条（RWX 新增）：<b>只打开实验级陆工厂</b>，默认 true。
     *
     * <p>作用点只有一个、且就在原版判定处：把
     * {@code isHardOrAboveDifficulty() && credits > 15000} 变成
     * {@code (isHardOrAboveDifficulty() || flag) && credits > 15000}。</p>
     *
     * <p>为什么要它：{@code isHardOrAboveDifficulty()} 是 difficulty ≥ 2，所以 <b>Hard(1) 连门槛
     * 都不满足</b>，实验工厂永远不会成为候选。开关只补这一个条件，分数、资金门槛、后续队列全部
     * 保持原版（分数仍是 0.04，所以「允许」不等于「一定建」）。</p>
     *
     * <p>生效条件：{@link #isEnabled()}（= takeover）也为真；关掉接管仍是原版。</p>
     */
    protected boolean experimentalLandFactory = true;

    public boolean isEnabled() {
        return enabled;
    }

    public void setEnabled(boolean enabled) {
        this.enabled = enabled;
    }

    /** 打开接管；返回 this 方便在构造函数里链式写。 */
    public AiImpossibleBranches enable() {
        this.enabled = true;
        return this;
    }

    /**
     * RWX：按配置表批量赋值（键 = 字段名），返回 this 方便链式调用。
     *
     * <p>int 项四舍五入；未知键只记日志。默认值 = 原版 Impossible 字面量，所以
     * {@code enable() + 默认值} 等于原版 Impossible 的这 7 个分支。</p>
     */
    public AiImpossibleBranches applyValues(java.util.Map<String, Float> values) {
        if (values == null || values.isEmpty()) {
            return this;
        }
        for (java.util.Map.Entry<String, Float> entry : values.entrySet()) {
            Float v = entry.getValue();
            if (v == null) {
                continue;
            }
            switch (entry.getKey()) {
                case "globalTimerExtraDecay": this.globalTimerExtraDecay = v; break;
                case "builderGroupMaxUnits": this.builderGroupMaxUnits = Math.round(v); break;
                case "attackGroupMaxUnitsNarrow": this.attackGroupMaxUnitsNarrow = Math.round(v); break;
                case "attackGroupMaxUnitsWide": this.attackGroupMaxUnitsWide = Math.round(v); break;
                case "seaGroupMaxUnits": this.seaGroupMaxUnits = Math.round(v); break;
                case "defensiveScoreBase": this.defensiveScoreBase = v; break;
                case "productionIdleUnitsLimit": this.productionIdleUnitsLimit = Math.round(v); break;
                case "productionWaterUnitsLimit": this.productionWaterUnitsLimit = Math.round(v); break;
                case "experimentalLandFactory":
                case "experimentalAndNukes": // 旧键兼容
                    this.experimentalLandFactory = v >= 0.5f; break;
                default: com.corrodinggames.rts.gameFramework.GameEngine.log(
                        "AiImpossibleBranches: unknown knob " + entry.getKey());
            }
        }
        return this;
    }

    /** 第 1 条：globalTimer 的额外衰减量。 */
    public float globalTimerExtraDecay() {
        return globalTimerExtraDecay;
    }

    /** 第 3 条：工兵队规模。 */
    public int builderGroupMaxUnits() {
        return builderGroupMaxUnits;
    }

    /** 第 4 条：进攻群规模（组序 &lt; 25 用窄档，否则宽档）。 */
    public int attackGroupMaxUnits(int mapWidth) {
        return mapWidth < 25 ? attackGroupMaxUnitsNarrow : attackGroupMaxUnitsWide;
    }

    /** 第 5 条：海上投送群规模。 */
    public int seaGroupMaxUnits() {
        return seaGroupMaxUnits;
    }

    /** 第 6 条：防守分基数。 */
    public float defensiveScoreBase() {
        return defensiveScoreBase;
    }

    /** 第 7 条：补海军时比对的建筑数上限。 */
    public int productionWaterUnitsLimit() {
        return productionWaterUnitsLimit;
    }

    /** 第 7 条：补兵时比对的 {@code unitProductionTimer} 上限（帧）。 */
    public int productionIdleUnitsLimit() {
        return productionIdleUnitsLimit;
    }

    /** 第 8 条：配置里写的开关原值（不看 takeover）。 */
    public boolean experimentalLandFactory() {
        return experimentalLandFactory;
    }

    /** 第 8 条：真正生效的开关 = takeover 打开 且 本项没被关掉。 */
    public boolean experimentalLandFactoryUnlocked() {
        return enabled && experimentalLandFactory;
    }

    /** 第 8 条：显式关掉（配置里写 {@code experimentalLandFactory: 0}）。 */
    public void setExperimentalLandFactory(boolean experimentalLandFactory) {
        this.experimentalLandFactory = experimentalLandFactory;
    }

    /**
     * 第 2 条：防空炮塔是否放宽到第 4 座且不走 0.02 衰减支。
     * 原版分支在 {@code BaseZone} 里不改，这里给参数化打分表提供 flag 或 Impossible 的判断。
     */
    public boolean wideAntiAir(AIController ai) {
        return enabled || ai.isInsaneDifficulty();
    }

    // ---- 兼容重载：早期部署的 core 包按 `xxx(AIController)` / `xxx(boolean)` 取值 --------------
    //
    // 11-21 11:16 那版 libs-core 里，AIController/BaseZone 调的是下面这些签名（当时这两个字段
    // 还叫 productionBuildingLimit / productionTimerLimit）。同一份源码要能同时服务新旧调用方，
    // 所以保留这组重载：参数只用来判断"没开接管时按难度回落到原版字面量"。

    /** 旧签名：该难度是否走接管（开接管 = 任何难度都走）。 */
    public boolean active(AIController ai) {
        return enabled || ai.isInsaneDifficulty();
    }

    public boolean active(boolean isInsane) {
        return enabled || isInsane;
    }

    public float globalTimerExtraDecay(AIController ai) {
        return globalTimerExtraDecay(ai.isInsaneDifficulty());
    }

    public float globalTimerExtraDecay(boolean isInsane) {
        return (enabled || isInsane) ? globalTimerExtraDecay : 0.0f;
    }

    public int builderGroupMaxUnits(AIController ai) {
        return builderGroupMaxUnits(ai.isInsaneDifficulty());
    }

    public int builderGroupMaxUnits(boolean isInsane) {
        return (enabled || isInsane) ? builderGroupMaxUnits : 8;
    }

    public int attackGroupMaxUnits(int mapWidth, AIController ai) {
        return attackGroupMaxUnits(mapWidth, ai.isInsaneDifficulty());
    }

    public int attackGroupMaxUnits(int mapWidth, boolean isInsane) {
        if (enabled || isInsane) {
            return mapWidth < 25 ? attackGroupMaxUnitsNarrow : attackGroupMaxUnitsWide;
        }
        return 7;
    }

    public int seaGroupMaxUnits(AIController ai) {
        return seaGroupMaxUnits(ai.isInsaneDifficulty());
    }

    public int seaGroupMaxUnits(boolean isInsane) {
        return (enabled || isInsane) ? seaGroupMaxUnits : 5;
    }

    public float defensiveScoreBase(AIController ai) {
        return defensiveScoreBase(ai.isInsaneDifficulty());
    }

    public float defensiveScoreBase(boolean isInsane) {
        return (enabled || isInsane) ? defensiveScoreBase : 270.0f;
    }

    /** 旧字段名：补兵闸门（现名 productionIdleUnitsLimit）。 */
    public int productionBuildingLimit(AIController ai) {
        return productionBuildingLimit(ai.isInsaneDifficulty());
    }

    public int productionBuildingLimit(boolean isInsane) {
        return (enabled || isInsane) ? productionIdleUnitsLimit : 50;
    }

    /** 旧字段名：水面补兵闸门（现名 productionWaterUnitsLimit）。 */
    public int productionTimerLimit(AIController ai) {
        return productionTimerLimit(ai.isInsaneDifficulty());
    }

    public int productionTimerLimit(boolean isInsane) {
        return (enabled || isInsane) ? productionWaterUnitsLimit : 12;
    }

    /**
     * 模板：继承后改你要的那个数再 {@link #enable()}。
     * 复制这个类改成自己的策略即可，不要直接用它。
     */
    public static class Veterans extends AiImpossibleBranches {
        public Veterans() {
            this.defensiveScoreBase = 150.0f;
            this.builderGroupMaxUnits = 12;
            enable();
        }
    }
}

