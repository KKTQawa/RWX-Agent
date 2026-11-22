package com.corrodinggames.rts.game.ai.strategy;

import com.corrodinggames.rts.game.ai.AIController;
import com.corrodinggames.rts.game.ai.BaseZone;
import com.corrodinggames.rts.game.units.UnitType;
import com.corrodinggames.rts.game.units.UnitTypeEnum;
import com.corrodinggames.rts.game.units.custom.CustomUnitConfig;
import com.corrodinggames.rts.gameFramework.GameEngine;
import com.corrodinggames.rts.gameFramework.Utility;

/**
 * 建筑选型打分：{@code BaseZone.getBestBuildingToBuild} 那串 if 分支的等价重写。
 *
 * <p><b>只暴露 A / B 两个旋钮（每个建筑）</b>：</p>
 * <ul>
 *   <li><b>A</b> = {@code xxxFirst}：还没有这座建筑（count==0）时的分数，决定“要不要开始建”。</li>
 *   <li><b>B</b> = {@code xxxNext}：第二座之后的衰减分子，实际分 = {@code B ÷ 分母}，分母写死在实现里。</li>
 * </ul>
 * <p>数量上限、分母权重、资金门槛、90% 随机、难度分档全部是私有常量——它们属于“形状”，不是旋钮。</p>
 *
 * <p>默认关闭（{@link #isEnabled()} == false）；关闭时 {@code BaseZone} 逐字执行原版分支。
 * 打开后仍先跑原版分支的形状判断，只是数字来自本表，所以<b>默认值就是原版</b>。</p>
 *
 * <p>用法：</p>
 * <pre>
 * public class MyScores extends AiBuildingScoreTable {
 *     public MyScores() { turretFirst = 0.60f; enable(); }
 * }
 * // AiStrategy 里 return MyScores 实例即可
 * </pre>
 */
public class AiBuildingScoreTable {

    /** 原版用 -2 表示“该建筑被排除”。 */
    public static final float EXCLUDED = -2.0f;

    /** 打分需要的环境快照。资源探测惰性：{@code findClosestResource()} 会消耗随机数并移动地图光标。 */
    public interface ResourceProbe {
        boolean available();
    }

    public static final class Env {
        public double credits;
        public boolean pathfindingOverloaded;
        /** 第 2 条 Impossible 分支是否生效（{@link AiImpossibleBranches#wideAntiAir}）。 */
        public boolean wideAntiAir;
        public boolean hardOrAbove;
        public boolean nukesAllowed = true;
        /** 第 8 条开关（接管 + 实验单位/核弹）：== {@code AiImpossibleBranches#experimentalAndNukesUnlocked()}。 */
        public boolean experimentalAndNukes;
        public ResourceProbe resourceProbe;

        boolean hasResource() {
            return resourceProbe != null && resourceProbe.available();
        }
    }

    // ---- 形状常量（不开放，改了就不是原版语义）----
    private static final float EXTRACTOR_RICH = 0.58f;
    private static final float EXTRACTOR_SECOND = 0.55f;
    private static final float EXTRACTOR_THIRD = 0.40f;
    private static final double EXTRACTOR_LOW_CREDITS = 5000.0d;
    private static final int EXTRACTOR_BUSY_ASSIGN = 3;
    private static final float EXTRACTOR_BUSY_MULTIPLIER = 0.6f;
    private static final int RESOURCE_ROLL_MAX = 100;
    private static final int RESOURCE_ROLL_BELOW = 90;

    /** 三类工厂共用：assign<5 才继续加厂。 */
    private static final int FACTORY_ASSIGN_LIMIT = 5;

    private static final int LAND_FACTORY_MAX_COUNT = 2;
    private static final int AIR_FACTORY_MAX_COUNT = 2;
    private static final int SEA_FACTORY_MAX_COUNT = 1;

    private static final int TURRET_NEXT_MAX_COUNT = 3;
    private static final float TURRET_FADE = 0.025f;
    private static final int TURRET_FADE_MAX_COUNT = 4;

    private static final int ANTI_AIR_NORMAL_MAX_COUNT = 3;
    /** Impossible 档放宽到第 4 座，且不走 0.02 的衰减支。 */
    private static final int ANTI_AIR_INSANE_MAX_COUNT = 4;
    private static final float ANTI_AIR_FADE = 0.02f;

    private static final double FABRICATOR_MIN_CREDITS = 2000.0d;
    private static final int FABRICATOR_MAX_COUNT = 5;
    private static final float FABRICATOR_ASSIGN_WEIGHT = 0.2f;

    private static final double ANTI_NUKE_MIN_CREDITS = 2200.0d;
    private static final int ANTI_NUKE_ASSIGN_LIMIT = 4;
    private static final int ANTI_NUKE_NEXT_MAX_COUNT = 1;
    private static final int ANTI_NUKE_COUNT_WEIGHT = 2;

    private static final double EXPERIMENTAL_MIN_CREDITS = 15000.0d;
    private static final double EXPERIMENTAL_NEXT_CREDITS = 55000.0d;

    // ---- 第 8 条开关（实验单位 + 核弹）：只在这些常量里，不进 21 维记录口径 ----
    /** 开关打开时，第一座实验级陆工厂的分数（原版只有 0.04，永远抢不过工厂）。 */
    private static final float EXPERIMENTAL_UNLOCKED_FIRST = 0.95f;
    private static final int NUKE_MAX_COUNT = 2;
    /** 低于陆工厂 0.8：先起经济，再上核。 */
    private static final float NUKE_FIRST = 0.75f;
    private static final float NUKE_NEXT = 0.35f;

    // ---- 旋钮：每个建筑只有 A（首座）与 B（衰减分子）----

    /** A：资源点建筑首座（钱 <5000 时）。 */
    protected float extractorFirst = 0.98f;
    /** B：第 4 座起 {@code 0.25 ÷ count}。 */
    protected float extractorNext = 0.25f;

    /** A：陆工厂首座。 */
    protected float landFactoryFirst = 0.80f;
    /** B：{@code 0.46 ÷ (assign + 2×count)}。 */
    protected float landFactoryNext = 0.46f;

    /** A：空工厂首座。 */
    protected float airFactoryFirst = 0.48f;
    /** B：{@code 0.29 ÷ (assign + count)}。 */
    protected float airFactoryNext = 0.29f;

    /** A：海工厂首座（仅寻路过载时参与）。 */
    protected float seaFactoryFirst = 0.30f;
    /** B：{@code 0.10 ÷ (assign + 2×count)}。 */
    protected float seaFactoryNext = 0.10f;

    /** A：炮台首座。 */
    protected float turretFirst = 0.47f;
    /** B：{@code 0.35 ÷ count}（count<3）。 */
    protected float turretNext = 0.35f;

    /** A：防空炮塔首座。 */
    protected float antiAirFirst = 0.42f;
    /** B：{@code 0.30 ÷ count}。 */
    protected float antiAirNext = 0.30f;

    /** A：极光防御（只建第一座）。 */
    protected float laserDefenceFirst = 0.018f;

    /** A：修复湾（只建第一座）。 */
    protected float repairbayFirst = 0.02f;

    /** A：资源制造仪首座（钱>2000）。 */
    protected float fabricatorFirst = 0.11f;
    /** B：{@code 0.07 ÷ (0.2×assign + count)}。 */
    protected float fabricatorNext = 0.07f;

    /** A：反核发射井首座（钱>2200 且 assign<4）。 */
    protected float antiNukeFirst = 0.06f;
    /** B：{@code 0.05 ÷ (assign + 2×count)}。 */
    protected float antiNukeNext = 0.05f;

    /** A：实验级陆工厂（Hard+ 且钱>15000，assign==0）。 */
    protected float experimentalFirst = 0.04f;
    /** B：钱>55000 且已有 1 座时的固定分（不是分母）。 */
    protected float experimentalNext = 0.03f;

    private boolean enabled;

    public boolean isEnabled() {
        return enabled;
    }

    public void setEnabled(boolean enabled) {
        this.enabled = enabled;
    }

    /** 打开接管；返回 this 方便在构造函数里链式写。 */
    public AiBuildingScoreTable enable() {
        this.enabled = true;
        return this;
    }

    /** 诊断用：少量样本值，确认配置真的落到表里。 */
    public String describeForLog() {
        return "turretFirst=" + turretFirst + " landFactoryFirst=" + landFactoryFirst
                + " experimentalFirst=" + experimentalFirst + " laserDefenceFirst=" + laserDefenceFirst;
    }

    /**
     * RWX：按配置表批量赋值（键 = 字段名，值 = 分数），返回 this 方便链式调用。
     *
     * <p>未知键只在日志里提示，不影响其它项；值为 null 的项跳过。配置缺省时等价于
     * {@link #enable()} + 全默认值（= 原版字面量）。</p>
     */
    public AiBuildingScoreTable applyValues(java.util.Map<String, Float> values) {
        if (values == null || values.isEmpty()) {
            return this;
        }
        for (java.util.Map.Entry<String, Float> entry : values.entrySet()) {
            Float v = entry.getValue();
            if (v == null) {
                continue;
            }
            switch (entry.getKey()) {
                case "extractorFirst": this.extractorFirst = v; break;
                case "extractorNext": this.extractorNext = v; break;
                case "landFactoryFirst": this.landFactoryFirst = v; break;
                case "landFactoryNext": this.landFactoryNext = v; break;
                case "airFactoryFirst": this.airFactoryFirst = v; break;
                case "airFactoryNext": this.airFactoryNext = v; break;
                case "seaFactoryFirst": this.seaFactoryFirst = v; break;
                case "seaFactoryNext": this.seaFactoryNext = v; break;
                case "turretFirst": this.turretFirst = v; break;
                case "turretNext": this.turretNext = v; break;
                case "antiAirFirst": this.antiAirFirst = v; break;
                case "antiAirNext": this.antiAirNext = v; break;
                case "laserDefenceFirst": this.laserDefenceFirst = v; break;
                case "repairbayFirst": this.repairbayFirst = v; break;
                case "fabricatorFirst": this.fabricatorFirst = v; break;
                case "fabricatorNext": this.fabricatorNext = v; break;
                case "antiNukeFirst": this.antiNukeFirst = v; break;
                case "antiNukeNext": this.antiNukeNext = v; break;
                case "experimentalFirst": this.experimentalFirst = v; break;
                case "experimentalNext": this.experimentalNext = v; break;
                default: GameEngine.log("AiBuildingScoreTable: unknown knob " + entry.getKey());
            }
        }
        return this;
    }

    /**
     * 真实入口：从基地/AI 抽取环境后转调 {@link #score(Env, UnitType, boolean, int, int, int)}。
     *
     * @param count    基地内该建筑（含 relatedUnits）的现存数量
     * @param assign   已被派去建造该建筑（含 relatedUnits）的工兵数
     * @param airCount 原版用来判断“已有空军产出能力”的单位数
     */
    public float score(BaseZone zone, AIController ai, UnitType type, boolean custom,
                       int count, int assign, int airCount) {
        Env env = new Env();
        env.credits = ai.credits;
        env.pathfindingOverloaded = ai.isPathfindingOverloaded();
        // 第 2 条 Impossible 分支（防空放宽到 4 座、不衰减）跟着这个走。
        env.wideAntiAir = ai.rwxImpossibleBranches().wideAntiAir(ai);
        env.hardOrAbove = ai.isHardOrAboveDifficulty();
        env.experimentalAndNukes = ai.rwxImpossibleBranches().experimentalAndNukesUnlocked();
        GameEngine engine = GameEngine.getInstance();
        boolean inGameOrLobby = engine.isInGameOrLobby();
        env.nukesAllowed = !inGameOrLobby || !engine.networkEngine.roomSettings.noNukes;
        env.resourceProbe = new ResourceProbe() {
            @Override
            public boolean available() {
                return zone.findClosestResource() != null;
            }
        };
        return score(env, type, custom, count, assign, airCount);
    }

    /**
     * 纯数值分支：与原版 {@code BaseZone.getBestBuildingToBuild} 的 if 链逐条对应。
     * 返回 {@link #EXCLUDED} 表示不建这个建筑。
     */
    public float score(Env env, UnitType type, boolean custom, int count, int assign, int airCount) {
        float f2 = EXCLUDED;
        if (type.p() && !custom) {
            if (env.hasResource() && Utility.getRandomIntInRange(0, RESOURCE_ROLL_MAX) < RESOURCE_ROLL_BELOW) {
                if (count == 0) {
                    f2 = env.credits < EXTRACTOR_LOW_CREDITS ? extractorFirst : EXTRACTOR_RICH;
                } else if (count == 1) {
                    f2 = EXTRACTOR_SECOND;
                } else if (count == 2) {
                    f2 = EXTRACTOR_THIRD;
                } else {
                    f2 = extractorNext / count;
                }
                if (assign >= EXTRACTOR_BUSY_ASSIGN) {
                    f2 *= EXTRACTOR_BUSY_MULTIPLIER;
                }
            }
        }
        if (type == UnitTypeEnum.landFactory && (assign < FACTORY_ASSIGN_LIMIT || airCount == 0)) {
            if (assign == 0) {
                f2 = landFactoryFirst;
            } else if (count < LAND_FACTORY_MAX_COUNT) {
                f2 = landFactoryNext / (assign + count * 2);
            }
        }
        if (type == UnitTypeEnum.seaFactory && env.pathfindingOverloaded
                && (assign < FACTORY_ASSIGN_LIMIT || airCount == 0)) {
            if (assign == 0) {
                f2 = seaFactoryFirst;
            } else if (count < SEA_FACTORY_MAX_COUNT) {
                f2 = seaFactoryNext / (assign + count * 2);
            }
        }
        if (type == UnitTypeEnum.airFactory && (assign < FACTORY_ASSIGN_LIMIT || airCount == 0)) {
            if (assign == 0) {
                f2 = airFactoryFirst;
            } else if (count < AIR_FACTORY_MAX_COUNT) {
                f2 = airFactoryNext / (assign + count);
            }
        }
        if (type == UnitTypeEnum.turret) {
            if (count == 0) {
                f2 = turretFirst;
            } else if (count < TURRET_NEXT_MAX_COUNT) {
                f2 = turretNext / count;
            } else if (count < TURRET_FADE_MAX_COUNT) {
                f2 = TURRET_FADE / count;
            }
        }
        if (type == UnitTypeEnum.laserDefence && count == 0) {
            f2 = laserDefenceFirst;
        }
        if (type == UnitTypeEnum.repairbay && count == 0) {
            f2 = repairbayFirst;
        }
        if (type == UnitTypeEnum.antiAirTurret) {
            if (count == 0) {
                f2 = antiAirFirst;
            } else if (env.wideAntiAir) {
                if (count < ANTI_AIR_INSANE_MAX_COUNT) {
                    f2 = antiAirNext / count;
                }
            } else if (count < ANTI_AIR_NORMAL_MAX_COUNT) {
                f2 = antiAirNext / count;
            } else if (count < ANTI_AIR_INSANE_MAX_COUNT) {
                f2 = ANTI_AIR_FADE / count;
            }
        }
        if (type == UnitTypeEnum.fabricator && env.credits > FABRICATOR_MIN_CREDITS
                && count < FABRICATOR_MAX_COUNT) {
            if (assign == 0) {
                f2 = fabricatorFirst;
            } else {
                f2 = fabricatorNext / (FABRICATOR_ASSIGN_WEIGHT * assign + count);
            }
        }
        if (type == UnitTypeEnum.AntiNukeLaucher && env.nukesAllowed
                && env.credits > ANTI_NUKE_MIN_CREDITS && assign < ANTI_NUKE_ASSIGN_LIMIT) {
            if (assign == 0) {
                f2 = antiNukeFirst;
            } else if (count < ANTI_NUKE_NEXT_MAX_COUNT) {
                f2 = antiNukeNext / (assign + count * ANTI_NUKE_COUNT_WEIGHT);
            }
        }
        if (custom) {
            CustomUnitConfig config = (CustomUnitConfig) type;
            // 自定义建筑的值来自 ini 真值，本表不接管；这里只是把原版判定原样搬过来。
            if (!config.disableUse
                    && (assign < config.maxGlobal || config.maxGlobal == -1)
                    && (count < config.maxEachBase || config.maxEachBase == -1)) {
                f2 = config.buildPriority;
                if (count < config.recommendedInEachBaseNum) {
                    f2 = config.recommendedInEachBasePriorityIfUnmet;
                }
                if (count == 0) {
                    f2 += config.nonInBaseExtraPriority;
                }
                if (assign == 0) {
                    f2 += config.nonGlobalExtraPriority;
                }
                if (type.p() && !env.hasResource()) {
                    f2 = EXCLUDED;
                }
            }
        }
        if (env.hardOrAbove && type == UnitTypeEnum.experimentalLandFactory
                && env.credits > EXPERIMENTAL_MIN_CREDITS) {
            if (assign == 0) {
                f2 = experimentalFirst;
            }
            if (env.credits > EXPERIMENTAL_NEXT_CREDITS && assign == 1) {
                f2 = experimentalNext;
            }
        }
        // 第 8 条开关：只负责「打开」，不改其它任何逻辑——问价用建筑自己的造价，房间禁核优先。
        if (env.experimentalAndNukes) {
            if (type == UnitTypeEnum.experimentalLandFactory && count == 0 && assign == 0
                    && env.credits > type.c()) {
                f2 = EXPERIMENTAL_UNLOCKED_FIRST;
            }
            if (type == UnitTypeEnum.NukeLaucher && env.nukesAllowed && assign < 2
                    && env.credits > type.c() && count < NUKE_MAX_COUNT) {
                if (count == 0) {
                    f2 = NUKE_FIRST;
                } else if (env.credits > type.c() * 2.0d) {
                    f2 = NUKE_NEXT / (assign + count);
                }
            }
        }
        return f2;
    }

    /**
     * 模板：继承后改 A/B 再 {@link #enable()}，守卫条件、数量分档、资金阶梯全部沿用原版。
     * 复制这个类改成自己的策略即可，不要直接用它。
     */
    public static class TurretHeavy extends AiBuildingScoreTable {
        public TurretHeavy() {
            this.turretFirst = 0.60f;
            this.turretNext = 0.45f;
            this.antiAirFirst = 0.50f;
            enable();
        }
    }
}
