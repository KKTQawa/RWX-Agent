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
 *   <tr><td>4</td><td>进攻群规模（大图）</td><td>7</td><td>宽&lt;25 图 14 / 否则 18</td></tr>
 *   <tr><td>5</td><td>海上投送群规模</td><td>5</td><td>10</td></tr>
 *   <tr><td>6</td><td>防守分基数</td><td>270</td><td>190（更早转防守姿态）</td></tr>
 *   <tr><td>7</td><td>生产闸门（单位数，不是计时器）</td><td>闲置战斗单位&lt;50、闲置水面&lt;12</td><td>&lt;65、&lt;16</td></tr>
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

    /** 第 4 条：宽 &lt; 25 的地图的进攻群规模。 */
    protected int attackGroupMaxUnitsNarrow = 14;

    /** 第 4 条：宽 ≥ 25 的地图的进攻群规模。 */
    protected int attackGroupMaxUnitsWide = 18;

    /** 第 5 条：海上/运输投送群规模。 */
    protected int seaGroupMaxUnits = 10;

    /** 第 6 条：防守分基数（越低越早转防守，建造节拍也更密）。 */
    protected float defensiveScoreBase = 190.0f;

    /** 第 7 条：全局“闲置战斗单位”数上限（补兵闸门：`idleUnits < 本值` 才继续出兵）。 */
    protected int productionIdleUnitsLimit = 65;

    /** 第 7 条：全局“闲置水面战斗单位”数上限（寻路过载时补海军的闸门）。 */
    protected int productionWaterUnitsLimit = 16;

    /**
     * 第 8 条（RWX 新增）：<b>实验单位 + 核弹的总开关</b>，默认 true。
     *
     * <p>原版对这一块只有半开：实验级陆工厂被"难度 ≥ Hard 且钱 &gt; 15000"锁着，而且分数只有
     * 0.04（永远竞争不过工厂 0.8），实际等于不建；进攻性核弹（{@code NukeLaucher}）则根本
     * 没有任何 AI 分支，AI 只会造反核。这里用一个开关同时放开两者：</p>
     * <ul>
     *   <li>实验级陆工厂：钱够就直接建第一座（之后由它的生产队列出实验坦克/悬浮坦克）。</li>
     *   <li>核弹发射井：钱够就打分（补弹/发射仍走原版，本开关不新增战术）。</li>
     * </ul>
     *
     * <p><b>优先级低于房间的禁核开关</b>：房间 NO NUKES 时 {@code PlaceBuildingAction} 会拒绝
     * 放置核设施，打分表也先看 {@code nukesAllowed}，所以这里不需要、也不允许绕过它。</p>
     *
     * <p>生效条件是 {@link #isEnabled()}（= takeover）也为真：关掉接管时仍然是原版行为。</p>
     */
    protected boolean experimentalAndNukes = true;

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
                case "experimentalAndNukes": this.experimentalAndNukes = v >= 0.5f; break;
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

    /** 第 4 条：进攻群规模（宽 &lt; 25 用窄档，否则宽档）。 */
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

    /** 第 7 条：补海军时的闲置水面战斗单位上限。 */
    public int productionWaterUnitsLimit() {
        return productionWaterUnitsLimit;
    }

    /** 第 7 条：补兵时的全局闲置战斗单位上限。 */
    public int productionIdleUnitsLimit() {
        return productionIdleUnitsLimit;
    }

    /** 第 8 条：配置里写的开关原值（不看 takeover）。 */
    public boolean experimentalAndNukes() {
        return experimentalAndNukes;
    }

    /** 第 8 条：真正生效的开关 = takeover 打开 且 本项没被关掉。 */
    public boolean experimentalAndNukesUnlocked() {
        return enabled && experimentalAndNukes;
    }

    /** 第 8 条：显式关掉（配置里写 {@code experimentalAndNukes: 0}）。 */
    public void setExperimentalAndNukes(boolean experimentalAndNukes) {
        this.experimentalAndNukes = experimentalAndNukes;
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

