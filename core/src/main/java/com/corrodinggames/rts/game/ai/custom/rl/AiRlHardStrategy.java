package com.corrodinggames.rts.game.ai.custom.rl;

import com.corrodinggames.rts.game.ai.BaseZone;
import com.corrodinggames.rts.game.ai.strategy.AiCadence;
import com.corrodinggames.rts.game.ai.strategy.AiContext;
import com.corrodinggames.rts.game.ai.strategy.AiDefinition;
import com.corrodinggames.rts.game.ai.strategy.AiOrders;
import com.corrodinggames.rts.game.ai.strategy.AiPhase;
import com.corrodinggames.rts.game.ai.strategy.AiStrategy;
import com.corrodinggames.rts.game.units.BaseUnit;
import com.corrodinggames.rts.game.units.OrderableUnit;
import com.corrodinggames.rts.game.units.UnitType;
import com.corrodinggames.rts.game.units.buildings.FactoryQueueInterface;

import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.IOException;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * "RL Hard-up": the original AI with its numbers moved into {@code evaluate/RL/AI Hard-up/ai.json}.
 *
 * <p>The default document extends the entire original difficulty (Hard by default) and switches every
 * takeover off, so the AI behaves exactly like that difficulty. Each gate in the config then swaps one
 * original decision for a config-driven one: which buildings to place, which units to queue, which
 * upgrades to take, the maintenance passes, and a small aggression layer for idle combat units.</p>
 *
 * <p>Only the strategy hooks the engine already exposes are used, so no engine file changes: building
 * placement and builder selection still come from the original {@link BaseZone#tryBuildUnit}, and unit
 * orders go through {@link AiOrders} which re-validates affordability, queue capacity and legality.</p>
 */
public final class AiRlHardStrategy implements AiStrategy {
    /** Stable registration code; custom codes are >= 4 and must never be reused. */
    public static final int CODE = 20;
    public static final String ID = "rwx.ai-rl-hard";
    private static final String STATE_ID = "rwx.ai-rl-hard.v1";
    /**
     * 只接管战斗单位时给原版建造留的余钱：原版 updateZoneStrategy 的建造门槛按优先级从
     * hasCredits(1300) 一直到 4800，炮塔实测需要攒到 ~2800 才会被选中。
     */

    public static AiDefinition definition() {
        AiRlConfig config = AiRlConfig.current();
        AiDefinition definition = AiDefinition
                .custom(CODE, ID, "RL Hard-up", "RL Hard-up", AiRlHardStrategy::new)
                .withIncomeMultiplier(config.incomeMultiplier)
                .withCadence(config.cadence);
        if (config.extendsOriginal) {
            definition = definition.withOriginalPhases(config.baseDifficulty,
                    config.originalPhases.toArray(new AiPhase[0]));
        }
        System.out.println("RWX_RL_AI_BASE " + config.base
                + " difficulty=" + config.baseDifficulty
                + " income=" + config.incomeMultiplier
                + " phases=" + config.originalPhases);
        return definition;
    }

    private AiRlConfig config;
    private float buildingTimer;
    private float upgradeTimer;
    private float tacticsTimer;
    private boolean dumpedUnits;
    private final Map<Long, Float> retreatingUntil = new HashMap<>();
    private final Map<Long, Integer> attackHoldUntilTick = new HashMap<>();

    @Override
    public String id() {
        return STATE_ID;
    }

    /**
     * 建筑选型打分表：只有 {@code buildingScore.enabled=true} 时才返回实例，否则 null =
     * 原版 {@code BaseZone.getBestBuildingToBuild} 的 if 链逐字执行。
     */
    @Override
    public com.corrodinggames.rts.game.ai.strategy.AiBuildingScoreTable buildingScoreTable() {
        return config == null ? null : config.buildingScoreTable();
    }

    /**
     * Impossible 的 7 个分支：只有 {@code impossible.enabled=true} 时才返回配置实例，
     * 否则 {@code ORIGINAL}（enabled=false）= 原版行为。
     */
    @Override
    public com.corrodinggames.rts.game.ai.strategy.AiImpossibleBranches rwxImpossibleBranches() {
        return config == null
                ? com.corrodinggames.rts.game.ai.strategy.AiImpossibleBranches.ORIGINAL
                : config.impossibleBranches();
    }

    @Override
    public void onStart(AiContext context, boolean restored) {
        config = AiRlConfig.current().forSlot(context.team().teamId);
        // 只接管战斗单位时，权重灌进原版选兵表：原版的配比/门槛/节流/采样照旧，
        // 权重是唯一的变量（等权 = 与内置 Hard 同分布）。
        if (config.overrideCombatUnitProduction && !config.overrideUnitProduction
                && !config.unitWeights.isEmpty()) {
            context.team().rwxApplyCombatUnitWeights(config.unitWeights);
        }
        if (!restored) {
            // Start ready to act on the first cadence rather than after a full interval.
            buildingTimer = config.buildingAttemptFrames;
            upgradeTimer = config.upgradeIntervalFrames;
            tacticsTimer = config.tacticsIntervalFrames;
        }
    }

    // ---------------------------------------------------------------- definition-level gates

    @Override
    public boolean overridesBuildingProduction() {
        return config != null && config.overrideBuildingProduction;
    }

    @Override
    public boolean overridesUnitProduction() {
        return config != null && config.overrideUnitProduction;
    }

    @Override
    public boolean overridesCombatUnitProduction() {
        return config != null && config.overrideCombatUnitProduction;
    }

    @Override
    public boolean overridesUpgrades() {
        // 升级不再整段接管：原版两段抽签照跑，配置只提供门槛/冷却/每次处理数。
        return false;
    }

    @Override
    public float upgradeBankCredits() {
        AiRlConfig cfg = config;
        return cfg != null && cfg.overrideUpgrades ? cfg.upgradeBankCredits : 4100f;
    }

    @Override
    public float upgradeIntervalFrames() {
        AiRlConfig cfg = config;
        // 配置里给的是“多久跑一次”，原版是每个策略节拍（250 帧）都跑，所以这里换算成额外冷却。
        return cfg != null && cfg.overrideUpgrades ? Math.max(0f, cfg.upgradeIntervalFrames - 250f) : 0f;
    }

    @Override
    public int upgradeMaxPerCycle() {
        AiRlConfig cfg = config;
        return cfg != null && cfg.overrideUpgrades ? cfg.upgradeMaxPerCycle : 0;
    }

    @Override
    public int combatUnitsPerCycle() {
        AiRlConfig cfg = config;
        return cfg != null && cfg.overrideCombatUnitProduction ? cfg.unitMaxPerCycle : 12;
    }

    @Override
    public boolean overridesTransportWaiting() {
        return config != null && config.overrideTransportWaiting;
    }

    // ---------------------------------------------------------------- economy maintenance

    /**
     * The original economy phase does these passes on its own. When its phases are retained this
     * callback must stay silent, so each pass is only re-issued when the config asks for it and the
     * original ECONOMY phase is switched off.
     */
    @Override
    public void onEconomy(AiContext context, float elapsedFrames) {
        AiRlConfig cfg = config;
        if (cfg == null || !cfg.economyMaintenance) return;
        for (BaseZone base : context.originalBases()) {
            if (base == null || base.isDestroyed) continue;
            if (cfg.economyHarvesters) base.buildRecommendedHarvesters();
            if (cfg.economyReclaim) base.sendHarvesterToReclaim();
            if (cfg.economyRepair) base.repairDamagedBuildings();
            if (cfg.economyRetarget) base.retargetHarvestersToBetterBuilding();
        }
    }

    @Override
    public float buildingAttemptFrames() {
        AiRlConfig cfg = config;
        // 只有接管建造时才改动原版的建造节拍；闸门关着必须返回 0（= 原版自己的 270+id%15），
        // 否则“默认值”就已经不是原版行为了。
        if (cfg == null || !cfg.overrideBuildingProduction) return 0f;
        return cfg.buildingAttemptFrames;
    }

    // ---------------------------------------------------------------- building production

    @Override
    public void onBuildingProduction(AiContext context, float elapsedFrames) {
        AiRlConfig cfg = config;
        // AiRuntime 每帧无条件调用所有回调，闸门必须在回调自己身上：开关关着就一个字都不能动，
        // 否则 building.priority 非空就等于偷偷接管了建造（曾让“全关=原版”的配置 200 局全败）。
        if (cfg == null || !cfg.overrideBuildingProduction) return;
        buildingTimer += elapsedFrames;
        if (buildingTimer < cfg.buildingAttemptFrames) return;
        buildingTimer = 0f;
        List<BaseZone> bases = context.originalBases();
        if (bases.isEmpty()) return;
        // 没有自定义建造优先级时，行为与原版完全一致：只把“多久跑一次”
        // 交给 building.attemptIntervalFrames 控制，选什么、放哪里都用原版逻辑。
        if (cfg.buildingPriority.isEmpty()) {
            context.setCustomBuildingTick(true);
            try {
                for (BaseZone base : bases) {
                    if (base == null || base.isDestroyed || base.getStage() == null) continue;
                    base.rwxRunEconomyTick();
                }
            } finally {
                context.setCustomBuildingTick(false);
            }
            return;
        }
        if (context.credits() < cfg.buildingBankCredits) return;
        List<OrderableUnit> own = context.ownUnits();
        Map<String, UnitType> byName = typesByName(context);
        for (String wanted : cfg.buildingPriority) {
            if (cfg.buildingDisabled.contains(wanted)) continue;
            UnitType type = byName.get(wanted);
            if (type == null || !type.isBuildingUnit()) continue;
            int cap = cfg.buildingMaxCount.getOrDefault(wanted, -1);
            if (cap >= 0 && countOwn(own, wanted) >= cap) continue;
            for (BaseZone base : bases) {
                if (base == null || base.isDestroyed) continue;
                if (base.tryBuildUnit(type)) return;
            }
        }
    }

    // ---------------------------------------------------------------- unit production

    @Override
    public void onUnitProduction(AiContext context, float elapsedFrames) {
        AiRlConfig cfg = config;
        // 全量接管才走自定义抽签；只接管战斗单位时由原版流程生产（权重已在上面的 override 表里）。
        if (cfg == null || !cfg.overrideUnitProduction) return;
        if (cfg.unitReinforcement) {
            for (BaseZone base : context.originalBases()) {
                if (base != null && !base.isDestroyed) base.requestReinforcement();
            }
        }
        if (cfg.unitWeights.isEmpty()) return;
        dumpFactoriesOnce(context, cfg);
        int queued = 0;
        for (OrderableUnit unit : context.ownUnits()) {
            if (queued >= cfg.unitMaxPerCycle) return;
            if (!(unit instanceof FactoryQueueInterface) || unit.isDead) continue;
            // 只接管战斗单位时，必须给原版的建造/补工程车留出钱：
            // 原版 updateZoneStrategy 的最低门槛是 hasCredits(1300)
            float reserve = cfg.unitReserveCredits;
            if (reserve <= 0f && cfg.overrideCombatUnitProduction) reserve = cfg.buildingReserveCredits;
            if (context.credits() < reserve) return;
            UnitType type = chooseUnit(context, cfg, unit);
            // One factory that cannot build anything must not stop the others.
            if (type == null) continue;
            if (context.orders().tryProduceUnit(type, unit)) queued++;
        }
    }

    /**
     * Weighted choice restricted to what <em>this</em> factory can actually build. The engine owns the
     * legality check ({@link OrderableUnit#getUnitAction(UnitType)}), so a weight list may name types
     * from several factories and each one only gets the subset it produces.
     */
    private UnitType chooseUnit(AiContext context, AiRlConfig cfg, OrderableUnit factory) {
        Map<String, UnitType> byName = typesByName(context);
        List<String> names = new ArrayList<>();
        List<Float> weights = new ArrayList<>();
        float total = 0f;
        for (Map.Entry<String, Float> entry : cfg.unitWeights.entrySet()) {
            UnitType type = byName.get(entry.getKey());
            if (type == null || type.isBuildingUnit()) continue;
            // 只挑战斗单位：建造者、运输、采集类留给原版 AI
            if (type.l()) continue;
            if (BaseUnit.findAttackDamageSource(type) instanceof OrderableUnit source
                    && source.canTransportUnits()) continue;
            if (factory.getUnitAction(type) == null) continue;
            names.add(entry.getKey());
            weights.add(entry.getValue());
            total += entry.getValue();
        }
        if (names.isEmpty() || total <= 0f) return null;
        long salt = context.tick() * 31L + context.team().teamId * 1000003L + names.size();
        float pick = (Math.floorMod(salt * 1103515245L + 12345L, 1000) / 1000f) * total;
        for (int index = 0; index < names.size(); index++) {
            pick -= weights.get(index);
            if (pick <= 0f) return byName.get(names.get(index));
        }
        return byName.get(names.get(names.size() - 1));
    }

    /**
     * Diagnostic used by {@code evaluate/RL/AI Hard-up/optimize.py} when it needs the real
     * factory -> producible-unit mapping. Enabled with {@code -Drwx.rl.dumpUnits=1}.
     */
    private void dumpFactoriesOnce(AiContext context, AiRlConfig cfg) {
        // At the first production call only the command center exists, which says nothing about
        // unit factories; wait until the base has had time to put factories down.
        if (dumpedUnits || context.tick() < 6000 || System.getProperty("rwx.rl.dumpUnits") == null) return;
        dumpedUnits = true;
        Map<String, UnitType> byName = typesByName(context);
        for (OrderableUnit unit : context.ownUnits()) {
            if (!(unit instanceof FactoryQueueInterface) || unit.isDead) continue;
            List<String> feasible = new ArrayList<>();
            for (Map.Entry<String, Float> entry : cfg.unitWeights.entrySet()) {
                UnitType type = byName.get(entry.getKey());
                if (type == null || type.isBuildingUnit()) continue;
                if (unit.getUnitAction(type) != null) feasible.add(entry.getKey());
            }
            System.out.println("RWX_RL_FACTORY " + unit.r().v()
                    + " feasible=[" + String.join(", ", feasible) + "]");
        }
    }

    // ---------------------------------------------------------------- upgrades

    @Override
    public void onUpgrades(AiContext context, float elapsedFrames) {
        // 已改为“原版流程 + 数值注入”（见 upgradeBankCredits / upgradeIntervalFrames /
        // upgradeMaxPerCycle），这里不再接管，留空避免双份升级动作。
    }

    // ---------------------------------------------------------------- tactics

    /**
     * Small aggression/retreat layer. It only touches units with no current order, so with the
     * original TACTICS phase retained the group AI keeps priority and this becomes a filler.
     */
    @Override
    public void onTactics(AiContext context, float elapsedFrames) {
        AiRlConfig cfg = config;
        if (cfg == null || !cfg.tacticsEnabled) return;
        tacticsTimer += elapsedFrames;
        if (tacticsTimer < cfg.tacticsIntervalFrames) return;
        tacticsTimer = 0f;

        List<OrderableUnit> own = context.ownUnits();
        List<BaseUnit> enemies = context.visibleEnemies();
        float homeX = 0f;
        float homeY = 0f;
        int homes = 0;
        for (OrderableUnit unit : own) {
            if (!unit.bI()) continue;
            homeX += unit.posX;
            homeY += unit.posY;
            homes++;
        }
        if (homes == 0) {
            for (OrderableUnit unit : own) {
                homeX += unit.posX;
                homeY += unit.posY;
                homes++;
            }
        }
        if (homes == 0) return;
        homeX /= homes;
        homeY /= homes;

        int now = context.tick();
        for (OrderableUnit unit : own) {
            if (unit.bI() || unit.isBuilder || unit.isDead) continue;
            float hpPercent = unit.maxHealth <= 0f ? 100f : unit.currentHealth / unit.maxHealth * 100f;
            Float retreatUntil = retreatingUntil.get(unit.objectId);
            boolean retreating = retreatUntil != null && now < retreatUntil;
            if (hpPercent < cfg.retreatHpPercent && !retreating) {
                retreatingUntil.put(unit.objectId, (float) (now + 300));
                context.orders().move(homeX, homeY, unit);
                continue;
            }
            if (retreating) continue;
            if (hpPercent >= cfg.resumeHpPercent) retreatingUntil.remove(unit.objectId);
            if (unit.getCurrentWaypoint() != null) continue;
            Integer hold = attackHoldUntilTick.get(unit.objectId);
            if (hold != null && now < hold) continue;
            attackHoldUntilTick.put(unit.objectId, now + 90);
            BaseUnit target = nearest(enemies, unit);
            if (target == null) continue;
            if (cfg.tacticsFocusFire) {
                context.orders().attack(target, unit);
            } else if (cfg.tacticsAttackMove) {
                double dx = target.posX - unit.posX;
                double dy = target.posY - unit.posY;
                double length = Math.max(1e-4, Math.hypot(dx, dy));
                float distance = Math.min((float) length, cfg.stagingDistance);
                context.orders().attackMove(
                        unit.posX + (float) (dx / length * distance),
                        unit.posY + (float) (dy / length * distance),
                        unit);
            } else {
                context.orders().attack(target, unit);
            }
        }
    }

    private static BaseUnit nearest(List<BaseUnit> enemies, OrderableUnit unit) {
        BaseUnit best = null;
        double bestDistance = Double.MAX_VALUE;
        for (BaseUnit enemy : enemies) {
            if (enemy == null || enemy.isDead || enemy.team == null) continue;
            double distance = Math.hypot(enemy.posX - unit.posX, enemy.posY - unit.posY);
            if (distance < bestDistance) {
                bestDistance = distance;
                best = enemy;
            }
        }
        return best;
    }

    // ---------------------------------------------------------------- shared helpers

    /**
     * Counts the configured type plus its upgrade chain (`landFactory` also counts
     * `landFactoryT2`), so a cap survives buildings upgrading themselves. Types whose own name
     * already carries a tier (`extractorT1`) only match that exact tier.
     */
    private static int countOwn(List<OrderableUnit> own, String typeName) {
        int count = 0;
        for (OrderableUnit unit : own) {
            String name = unit.r().v();
            if (name.equalsIgnoreCase(typeName)) {
                count++;
            } else if (typeName.toLowerCase(java.util.Locale.ROOT).matches(".*t[0-9]$") == false
                    && name.toLowerCase(java.util.Locale.ROOT).startsWith(typeName.toLowerCase(java.util.Locale.ROOT) + "t")) {
                count++;
            }
        }
        return count;
    }

    private static Map<String, UnitType> typesByName(AiContext context) {
        Map<String, UnitType> result = new HashMap<>();
        for (UnitType type : context.unitTypes()) {
            result.put(type.v().toLowerCase(java.util.Locale.ROOT), type);
        }
        return result;
    }

    // ---------------------------------------------------------------- save state

    @Override
    public void writeState(DataOutputStream output) throws IOException {
        output.writeInt(1);
        output.writeFloat(buildingTimer);
        output.writeFloat(upgradeTimer);
        output.writeFloat(tacticsTimer);
    }

    @Override
    public void readState(DataInputStream input) throws IOException {
        int version = input.readInt();
        if (version != 1) throw new IOException("Unsupported RL AI state version: " + version);
        buildingTimer = input.readFloat();
        upgradeTimer = input.readFloat();
        tacticsTimer = input.readFloat();
    }

    @SuppressWarnings("unused")
    private static AiCadence standardCadence() {
        return AiCadence.STANDARD;
    }

    @SuppressWarnings("unused")
    private static Comparator<UnitType> byName() {
        return Comparator.comparing(UnitType::v);
    }
}
