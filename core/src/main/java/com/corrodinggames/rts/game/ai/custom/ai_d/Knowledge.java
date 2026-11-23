package com.corrodinggames.rts.game.ai.custom.ai_d;

import com.corrodinggames.rts.game.ai.custom.rsi_sdk.RsiView;
import com.corrodinggames.rts.game.ai.custom.rsi_sdk.RsiView.Action;
import com.corrodinggames.rts.game.ai.custom.rsi_sdk.RsiView.Unit;

import java.util.List;
import java.util.Locale;

/**
 * What this strategy knows about the mod's unit set: name predicates, and how much a produced
 * combat unit is worth per credit.
 *
 * <p>Names come from the unit INI files ({@code [core] name}); the engine reports them through
 * {@link RsiView.Unit#type()} and {@link Action#product()}. Nothing here is an engine reference,
 * so the policy stays compilable against the SDK alone.
 */
final class Knowledge {
    private Knowledge() { }

    static String lower(String type) {
        return type == null ? "" : type.toLowerCase(Locale.ROOT);
    }

    static boolean isCommandCenter(String type) {
        String t = lower(type);
        return t.equals("commandcenter") || t.endsWith("commandcenter");
    }

    static boolean isBuilder(String type) {
        String t = lower(type);
        return t.equals("builder") || t.equals("combatengineer") || t.equals("mechengineer");
    }

    static boolean isExtractor(String type) {
        return lower(type).contains("extractor");
    }

    static boolean isFactory(String type) {
        String t = lower(type);
        return t.contains("factory");
    }

    static boolean isTurret(String type) {
        String t = lower(type);
        return t.contains("turret") || t.equals("laserdefence") || t.equals("laserdefense");
    }

    static boolean isFabricator(String type) {
        return lower(type).contains("fabricator");
    }

    static boolean isRepair(String type) {
        String t = lower(type);
        return t.contains("repair");
    }

    static boolean isExpansion(String type) {
        String t = lower(type);
        return t.contains("outpost") || t.contains("laboratory") || t.contains("nuke");
    }

    /**
     * Combat value per credit, measured from the mod's unit files and normalised so a {@code c_tank}
     * is 1.0. The underlying quantity is {@code dps * (1 + hp / 1000) / price}: damage and staying
     * power both matter, and factory seconds are proportional to price, so this is the number that
     * decides which unit is worth building.
     *
     * <p>Zero means "never produce this": buildings, transports, scouts and the 90k novelty chassis.
     * The two balance outliers in this mod are {@code mechLaser} (1080 dps at 310 range for 7000)
     * and {@code c_mammothTank} (2600 hp of front line for 3900).
     */
    static double combatValue(String type) {
        String t = lower(type);
        if (t.isEmpty()) return 0;
        if (t.equals("builder")) return 0;
        if (t.contains("dropship") || t.contains("transport") || t.contains("spydrone")) return 0;
        if (t.contains("nuke")) return 0;
        if (t.contains("modularspider")) return 0;
        if (t.contains("experimental")) return 0.3;
        if (t.contains("factory") || t.contains("turret") || t.contains("extractor")
                || t.contains("fabricator") || t.contains("repair") || t.contains("outpost")
                || t.contains("launcher")) return 0;
        if (t.contains("scout")) return 0.4;
        if (t.equals("lightgunship")) return 0.30;
        if (t.equals("c_helicopter")) return 0.25;
        if (t.equals("bomber")) return 1.2;
        if (t.equals("missileairship")) return 0.5;
        if (t.equals("gunship")) return 0.6;
        if (t.equals("firebee")) return 0.8;
        if (t.equals("heavyinterceptor")) return 0.5;
        if (t.equals("c_interceptor")) return 0.4;
        if (t.equals("c_amphibiousjet") || t.equals("amphibiousjet")) return 0.6;
        if (t.equals("aabeamgunship")) return 0.4;
        // Dedicated anti-air: cheap insurance, not a core.
        if (t.equals("mechmissile") || t.equals("missiletank")) return 0.25;
        // Ships only matter on water maps.
        if (t.contains("ship") || t.contains("sub") || t.contains("boat")) return 0.25;
        // Measured per-credit values.
        if (t.equals("c_tank")) return 1.00;
        if (t.equals("hovertank")) return 0.90;
        if (t.equals("mechgun")) return 1.66;
        if (t.equals("plasmatank")) return 1.30;
        if (t.equals("c_lasertank")) return 0.89;
        if (t.equals("c_artillery")) return 0.45;
        if (t.equals("c_mammothtank")) return 2.08;
        if (t.equals("heavyartillery")) return 0.40;
        if (t.equals("mechartillery")) return 0.55;
        if (t.equals("mechlaser")) return 4.90;
        if (t.equals("mechminigun")) return 0.45;
        if (t.equals("mechflame")) return 0.95;
        if (t.equals("mechlightning")) return 0.88;
        if (t.equals("mechheavymissile")) return 0.66;
        if (t.equals("mechbunker")) return 0.54;
        if (t.equals("combatengineer")) return 0.25;
        if (t.equals("mechengineer")) return 0.15;
        return 0.60;
    }

    /**
     * Absolute combat power of one unit of this type, in "credits worth of c_tank": combat value per
     * credit times what the unit costs. Used by the influence map, where what matters is the total
     * strength in an area rather than the price/performance ratio.
     */
    static double power(String type) {
        String t = lower(type);
        double value = combatValue(t);
        if (value <= 0) return 0;
        return value * priceGuess(t);
    }

    private static double priceGuess(String t) {
        return switch (t) {
            case "c_tank" -> 350;
            case "hoverTank", "hover_tank" -> 450;
            case "mechgun" -> 600;
            case "plasmatank" -> 1000;
            case "c_mammothtank" -> 3900;
            case "mechlaser" -> 7000;
            case "c_artillery" -> 900;
            case "mechartillery" -> 1400;
            case "heavyartillery" -> 3100;
            case "c_lasertank" -> 1600;
            case "mechminigun" -> 1200;
            case "mechflame" -> 1500;
            case "mechlightning" -> 1800;
            case "mechheavymissile" -> 2200;
            case "missiletank" -> 2500;
            case "mechmissile" -> 900;
            case "heavyinterceptor" -> 1800;
            case "bomber" -> 1400;
            default -> 500;
        };
    }

    /**
     * Weapon range in world units. The SDK exposes it per live unit, but the *candidate* types only
     * exist in a factory's action list, so the table is the fallback for units we never owned.
     */
    static float rangeGuess(String type) {
        String t = lower(type);
        return switch (t) {
            case "c_artillery", "mechartillery" -> 290;
            case "heavyartillery", "mechlaser" -> 310;
            case "missiletank" -> 340;
            case "c_tank", "hovertank" -> 165;
            case "mechgun" -> 130;
            case "plasmatank", "c_lasertank" -> 190;
            case "c_mammothtank" -> 180;
            case "c_antiairturret", "c_antiairturrett2" -> 230;
            default -> 150;
        };
    }

    /**
     * What an enemy building is worth destroying, before distance is taken into account.
     *
     * <p>Production first: a killed factory is up to 30 credits/s of their throughput that cannot
     * be replaced while the building is down. Extractors next, because their income multiplier
     * makes every one of them worth several of ours. Anti-air and the command center are cheap in
     * this ranking on purpose — the win condition is the last thing to break, not the first, and a
     * turret cluster is the most expensive thing on the map to walk into.
     */
    static double priorityOf(String type) {
        String t = lower(type);
        if (t.isEmpty()) return 0;
        if (t.contains("factory")) return 3.0;
        if (t.contains("extractor")) return 2.6;
        if (t.contains("outpost") || t.contains("laboratory") || t.contains("launcher")) return 2.0;
        if (t.contains("fabricator") || t.contains("repair")) return 1.6;
        if (isCommandCenter(t)) return 1.0;
        if (t.contains("turret") || t.contains("defence") || t.contains("defense")) return 0.12;
        return 0.5;
    }

    /** Units whose whole job is shooting aircraft. */
    static boolean isAntiAir(String type) {
        String t = lower(type);
        return t.equals("mechmissile") || t.equals("missiletank") || t.contains("antiair");
    }

    /**
     * Score for "what should this factory build next". Factory time and credits are both roughly
     * proportional to price, so the ranking is combat value per credit: an expensive unit has to
     * be that much better to be worth the same factory seconds.
     */
    static double productionScore(String type, int price) {
        return Math.max(0, combatValue(type));
    }

    static boolean isCombatUnit(Unit unit) {
        return unit != null && unit.complete() && !unit.building() && unit.armed() && unit.mobile();
    }

    /** Name-based movement guess for a type we have not seen on the field yet. */
    static String movementGuess(String type) {
        String t = lower(type);
        if (t.contains("ship") && !t.contains("gunship") && !t.contains("airship")) return "WATER";
        if (t.contains("sub")) return "WATER";
        if (t.contains("boat")) return "WATER";
        if (t.contains("hover")) return "HOVER";
        if (t.contains("jet") || t.contains("gunship") || t.contains("interceptor")
                || t.contains("helicopter") || t.contains("bomber") || t.contains("airship")
                || t.contains("drone") || t.contains("bee")) return "AIR";
        return "LAND";
    }

    static Unit find(RsiView view, long id) {
        return id < 0 ? null : view.own.get(id);
    }

    /** The team's command center, or the healthiest own building when it is gone. */
    static Unit base(RsiView view) {
        Unit best = null;
        for (Unit unit : view.own.values()) {
            if (!unit.building() || !unit.complete()) continue;
            if (isCommandCenter(unit.type())) {
                if (best == null || unit.healthFraction() > best.healthFraction()) best = unit;
            } else if (best == null) {
                best = unit;
            } else if (!isCommandCenter(best.type()) && unit.at().distanceSquared(best.at()) < 0
                    && unit.healthFraction() > best.healthFraction()) {
                best = unit;
            }
        }
        return best;
    }

    static int count(RsiView view, java.util.function.Predicate<String> typeTest) {
        int count = 0;
        for (Unit unit : view.own.values()) {
            if (unit.complete() && typeTest.test(unit.type())) count++;
        }
        return count;
    }

    /** Buildings that exist or are still being constructed, so nothing is ordered twice. */
    static int countAny(RsiView view, java.util.function.Predicate<String> typeTest) {
        int count = 0;
        for (Unit unit : view.own.values()) {
            if (unit.building() && typeTest.test(unit.type())) count++;
        }
        return count;
    }

    static List<Unit> builders(RsiView view) {
        List<Unit> result = new java.util.ArrayList<>();
        for (Unit unit : view.own.values()) {
            if (unit.complete() && unit.builder() && unit.mobile() && unit.carrier() < 0) result.add(unit);
        }
        return result;
    }

    /** First own unit that can produce the given type, preferring an empty queue. */
    static Unit factoryFor(RsiView view, String type) {
        Unit best = null;
        for (Unit unit : view.own.values()) {
            if (!unit.complete() || unit.queued() < 0) continue;
            if (!canProduce(unit, type)) continue;
            if (best == null || unit.queued() < best.queued()) best = unit;
        }
        return best;
    }

    /** Last known price of a type, from the action table or the blackboard's learned prices. */
    static double priceOf(Blackboard board, String type) {
        Integer known = board.price.get(lower(type));
        return known == null ? 700 : known;
    }

    /** True when one of our completed factories has this production action at all. */
    static boolean canBuild(RsiView view, String type) {
        for (Unit unit : view.own.values()) {
            if (!unit.complete() || unit.building()) continue;
            for (Action action : unit.actions()) {
                if (action.kind() != RsiView.ActionKind.PRODUCE) continue;
                if (type.equals(lower(action.product()))) return true;
            }
        }
        return false;
    }

    static boolean canProduce(Unit factory, String type) {
        for (Action action : factory.actions()) {
            if (action.product() == null || !action.product().equals(type)) continue;
            if (action.kind() != RsiView.ActionKind.PRODUCE) continue;
            if (action.ready()) return true;
        }
        return false;
    }

    /** The next-tier action of a building, or null. Built-in factories report no product here. */
    static Action upgradeAction(Unit unit) {
        for (Action action : unit.actions()) {
            if (action.kind() == RsiView.ActionKind.UPGRADE) return action;
        }
        return null;
    }

    /**
     * True when this factory already has its level-2 menu. The engine keeps the same type name for
     * both levels, so the menu itself is the only honest signal available through the SDK.
     */
    static boolean upgradedMenU(Unit factory) {
        for (Action action : factory.actions()) {
            String product = lower(action.product());
            if (product.equals("c_mammothtank") || product.equals("plasmatank")
                    || product.equals("heavytank") || product.equals("c_lasertank")
                    || product.equals("mechlaser") || product.equals("mechminigun")
                    || product.equals("mechflame") || product.equals("heavyartillery")
                    || product.equals("combatengineer")) {
                return true;
            }
        }
        return false;
    }

    /** Upgrade ordering key: extractor tier 2 before tier 3 before the overclocked branch. */
    static int upgradeTier(String product) {
        String t = lower(product);
        if (t.isEmpty()) return 3;
        if (t.contains("overclock") || t.contains("reinforced")) return 6;
        for (int i = t.length() - 1; i >= 0; i--) {
            char c = t.charAt(i);
            if (c >= '0' && c <= '9') return c - '0';
        }
        return 3;
    }

    /** Price the engine quotes for producing this type right now (0 when unknown). */
    static int priceOf(Unit factory, String type) {
        for (Action action : factory.actions()) {
            if (type.equals(action.product()) && !action.placement()) return action.credits();
        }
        return 0;
    }
}
