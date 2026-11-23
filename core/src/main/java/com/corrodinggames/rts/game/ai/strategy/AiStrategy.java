package com.corrodinggames.rts.game.ai.strategy;


import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.IOException;

/** One strategy instance per custom AI team. All callbacks run on the simulation thread.
 * Time arguments are simulation frames (60 frames = one second), not milliseconds.
 * Issue orders through AiContext.command; do not mutate unit orders or resources directly.
 */
public interface AiStrategy {
    /** Stable save identifier. Change this when replacing the strategy with an incompatible one. */
    String id();

    /** Called on the first active update, after readState when restoring a save. */
    default void onStart(AiContext context, boolean restored) { }

    /** Fine-grained targeting, attack modes, ability use, and movement decisions. */
    default void onFrame(AiContext context, float deltaFrames) { }

    /** Economy, construction, production, repairs, reclaiming, and upgrades (~25 frames). */
    default void onEconomy(AiContext context, float elapsedFrames) { }

    /** Replaces the original base AI's non-building production when enabled below. */
    default boolean overridesUnitProduction() { return false; }

    /**
     * Take over combat-unit production only: builders, harvesters and transports keep being
     * produced by the original AI, which otherwise is not touched at all.
     */
    default boolean overridesCombatUnitProduction() { return false; }

    /** Decide when and which non-building units to queue; called on each economy cadence. */
    default void onUnitProduction(AiContext context, float elapsedFrames) { }

    /** Replaces the original base AI's building choice, placement and construction when enabled below. */
    default boolean overridesBuildingProduction() { return false; }

    /** 非 0 时只“限流”原版建造节拍（按帧计），不改变选型与落点；0 表示完全原版。 */
    default float buildingAttemptFrames() { return 0f; }

    /**
     * 非 null 且已 enable 时接管原版建筑选型打分（{@link AiBuildingScoreTable}）。
     * 默认 null = 原版硬编码分支；这是“只换数、不换流程”的入口，与 overridesBuildingProduction 互不影响。
     */
    default AiBuildingScoreTable buildingScoreTable() { return null; }

    /**
     * 原版 Impossible 专有的 7 个分支（衰减/编队/防守分/生产闸门…）。
     * 默认 {@link AiImpossibleBranches#ORIGINAL}：只有 Impossible 生效，等价原版；
     * 返回自己 enable 过的实例即可让任意难度都吃这些数值。
     */
    default AiImpossibleBranches rwxImpossibleBranches() { return AiImpossibleBranches.ORIGINAL; }

    default RwxOriginalAiTuning originalTuning() { return RwxOriginalAiTuning.ORIGINAL; }

    /** Interval for the native base timer. Zero leaves the built-in timer selection in place. */
    default float originalBuildingIntervalFrames() { return 0f; }

    /** Decide which buildings to place, where, and which builder places them; called on each economy cadence. */
    default void onBuildingProduction(AiContext context, float elapsedFrames) { }

    /** Replaces the original AI's upgrade draw (the random cm() / high-priority action lottery). */
    default boolean overridesUpgrades() { return false; }

    /** 原版升级门槛（默认 4100）；自定义 AI 只换这个数，不换升级流程。 */
    default float upgradeBankCredits() { return 4100f; }

    /** 升级段的额外冷却（帧）。0 = 每个策略节拍都跑，即原版行为。 */
    default float upgradeIntervalFrames() { return 0f; }

    /** 每次升级段最多处理几个单位。0 = 不限制，即原版行为。 */
    default int upgradeMaxPerCycle() { return 0; }

    /** 每个战术节拍最多下几个战斗单位生产单（12 = 原版 productionAttemptsPerCycle）。 */
    default int combatUnitsPerCycle() { return 12; }

    /** Changes legacy land-reinforcement transport staging without replacing transport execution. */
    default boolean overridesTransportWaiting() { return false; }

    /** Decide which buildings upgrade and in which order; called on each economy cadence. */
    default void onUpgrades(AiContext context, float elapsedFrames) { }

    /** Recruitment, grouping, attack, retreat, scouting, and transport (~80 frames). */
    default void onTactics(AiContext context, float elapsedFrames) { }

    /** Expansion, tech choices, army composition, and long-term goals (~250 frames). */
    default void onStrategy(AiContext context, float elapsedFrames) { }

    /** Releases transient resources when the team leaves this custom policy. Do not issue commands here. */
    default void onStop(AiContext context) { }

    /** Save only your strategy's state; add your own payload version if the layout may change. */
    default void writeState(DataOutputStream output) throws IOException { }

    /** Called before onStart. Resolve saved unit IDs in onStart, after the world has loaded. */
    default void readState(DataInputStream input) throws IOException { }
}
