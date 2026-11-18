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
    private final Map<Long, Float> retreatingUntil = new HashMap<>();
    private final Map<Long, Integer> attackHoldUntilTick = new HashMap<>();

    @Override
    public String id() {
        return STATE_ID;
    }

    @Override
    public void onStart(AiContext context, boolean restored) {
        config = AiRlConfig.current().forSlot(context.team().teamId);
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
    public boolean overridesUpgrades() {
        return config != null && config.overrideUpgrades;
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

    // ---------------------------------------------------------------- building production

    @Override
    public void onBuildingProduction(AiContext context, float elapsedFrames) {
        AiRlConfig cfg = config;
        if (cfg == null) return;
        buildingTimer += elapsedFrames;
        if (buildingTimer < cfg.buildingAttemptFrames) return;
        buildingTimer = 0f;
        if (context.credits() < cfg.buildingBankCredits) return;
        List<BaseZone> bases = context.originalBases();
        if (bases.isEmpty()) return;
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
        if (cfg == null) return;
        if (cfg.unitReinforcement) {
            for (BaseZone base : context.originalBases()) {
                if (base != null && !base.isDestroyed) base.requestReinforcement();
            }
        }
        if (cfg.unitWeights.isEmpty()) return;
        int queued = 0;
        for (OrderableUnit unit : context.ownUnits()) {
            if (queued >= cfg.unitMaxPerCycle) return;
            if (!(unit instanceof FactoryQueueInterface) || unit.isDead) continue;
            if (context.credits() < cfg.unitReserveCredits) return;
            UnitType type = chooseUnit(context, cfg);
            if (type == null) return;
            if (context.orders().tryProduceUnit(type, unit)) queued++;
        }
    }

    /** Deterministic weighted choice: the same tick and team always pick the same type. */
    private UnitType chooseUnit(AiContext context, AiRlConfig cfg) {
        Map<String, UnitType> byName = typesByName(context);
        List<String> names = new ArrayList<>();
        List<Float> weights = new ArrayList<>();
        float total = 0f;
        for (Map.Entry<String, Float> entry : cfg.unitWeights.entrySet()) {
            UnitType type = byName.get(entry.getKey());
            if (type == null || type.isBuildingUnit()) continue;
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

    // ---------------------------------------------------------------- upgrades

    @Override
    public void onUpgrades(AiContext context, float elapsedFrames) {
        AiRlConfig cfg = config;
        if (cfg == null) return;
        upgradeTimer += elapsedFrames;
        if (upgradeTimer < cfg.upgradeIntervalFrames) return;
        upgradeTimer = 0f;
        if (context.credits() < cfg.upgradeBankCredits) return;
        int done = 0;
        for (OrderableUnit unit : context.ownUnits()) {
            if (done >= cfg.upgradeMaxPerCycle) return;
            if (!unit.bI() || unit.isDead) continue;
            if (context.orders().tryUpgrade(unit, null)) done++;
        }
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
