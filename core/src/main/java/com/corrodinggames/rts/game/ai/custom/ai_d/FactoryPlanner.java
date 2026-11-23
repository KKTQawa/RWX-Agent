package com.corrodinggames.rts.game.ai.custom.ai_d;

import com.corrodinggames.rts.game.ai.custom.rsi_sdk.RsiDecision;
import com.corrodinggames.rts.game.ai.custom.rsi_sdk.RsiStrategy;
import com.corrodinggames.rts.game.ai.custom.rsi_sdk.RsiView;
import com.corrodinggames.rts.game.ai.custom.rsi_sdk.RsiView.Action;
import com.corrodinggames.rts.game.ai.custom.rsi_sdk.RsiView.ActionKind;
import com.corrodinggames.rts.game.ai.custom.rsi_sdk.RsiView.Point;
import com.corrodinggames.rts.game.ai.custom.rsi_sdk.RsiView.Unit;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/**
 * Factories: builders, factory upgrades, and the army itself.
 *
 * <p>Units are ranked by measured combat value per credit ({@link Knowledge#combatValue}), which on
 * this mod makes {@code mechLaser} the goal: 1080 dps at 310 range for 7000 credits is 4.9x a
 * {@code c_tank} per credit. Everything before it is just staying alive.
 */
final class FactoryPlanner extends RsiStrategy.Production {
    private final Blackboard board;

    FactoryPlanner(Blackboard board) {
        this.board = board;
    }

    @Override
    protected RsiDecision plan(RsiView view, double availableCredits) {
        board.observe(view);
        List<RsiDecision.Order> orders = new ArrayList<>();
        Set<Long> used = new HashSet<>();

        board.savingStrike = siegeReserve(view) > 0;
        factoryUpgrades(view, orders);
        incomeUpgrades(view, orders);
        keepBuilderSupply(view, orders, used);
        rally(view, orders);
        produceArmy(view, orders, used, availableCredits);

        // 全权接管排产：默认补单会按最高价乱买，和这里的兵种表冲突。
        return new RsiDecision(orders, Set.of()).exclusive();
    }

    // ------------------------------------------------------------------ income upgrades

    /**
     * Extractor tiers are the only real income growth available: T1 12 cr/s, T2 18, T3 30, overclock
     * 45 (room x2 doubles all of them). Tier 2 is bought for every pool before any tier 3, because
     * it is the cheapest step and the payback is shortest.
     */
    private void incomeUpgrades(RsiView view, List<RsiDecision.Order> orders) {
        // 掉一个抽取器就等于永久少一份收入：池子还没占满时，先把损失补回来再谈升级。
        int extractors = Knowledge.countAny(view, Knowledge::isExtractor);
        int wanted = Math.min(view.resourcePools.size(), Tune.REBUILD_POOLS);
        if (extractors < wanted) return;
        Unit best = null;
        Action bestAction = null;
        int bestTier = Integer.MAX_VALUE;
        for (Unit unit : view.own.values()) {
            if (!unit.complete() || !Knowledge.isExtractor(unit.type())) continue;
            Action upgrade = Knowledge.upgradeAction(unit);
            if (upgrade == null || !upgrade.ready()) continue;
            int tier = Knowledge.upgradeTier(upgrade.product());
            if (tier < bestTier) {
                bestTier = tier;
                best = unit;
                bestAction = upgrade;
            }
        }
        if (best == null || bestAction == null) return;
        if (view.credits < bestAction.credits() + Tune.UPGRADE_RESERVE) return;
        orders.add(RsiDecision.Order.action(best.id(), bestAction.id(), null, -1));
        board.investPot = Math.max(0, board.investPot - bestAction.credits());
        board.planned(bestAction.product(), best.at());
        board.log(view, "upgrade " + best.type() + " -> " + bestAction.product()
                + " cost=" + bestAction.credits());
    }

    /**
     * Siege doctrine reserve: a small group of {@code mechLaser} (310 range, 1080 dps) outranges
     * every turret in the mod and kills a command center in seconds, so the army is not the win
     * condition any more — the base is. The reserve releases itself the moment the purchase is
     * affordable, so it never deadlocks the factory that has to build the unit.
     */
    private double siegeReserve(RsiView view) {
        if (Tune.LASER_COUNT <= 0) return 0;
        if (!Knowledge.canBuild(view, "mechlaser")) return 0;
        if (Knowledge.count(view, t -> Knowledge.lower(t).equals("mechlaser")) >= Tune.LASER_COUNT) return 0;
        if (view.credits >= Tune.LASER_PRICE) return 0;
        // Never hoard while the base is under real pressure: the strike is only worth it from a
        // position the opponent cannot punish.
        if (board.base != null
                && board.threatAt(view, board.base, Tune.HOME_RADIUS)
                > board.armyPower(view, board.base, Tune.HOME_RADIUS * 1.4) * 0.5) return 0;
        return Tune.LASER_PRICE - view.credits;
    }

    // ------------------------------------------------------------------ factory upgrades


    /**
     * Two unlocks matter: {@code landFactory} L2 (plasma, mammoth) is cheap and immediate,
     * {@code mechFactoryT2} (mechLaser) is the expensive one that actually wins the long game.
     */
    private void factoryUpgrades(RsiView view, List<RsiDecision.Order> orders) {
        Unit best = null;
        Action bestAction = null;
        int bestRank = Integer.MAX_VALUE;
        for (Unit unit : view.own.values()) {
            if (!unit.complete() || unit.queued() > 0) continue;
            Action upgrade = Knowledge.upgradeAction(unit);
            if (upgrade == null || !upgrade.ready()) continue;
            int rank = upgradeRank(unit, view);
            if (rank >= bestRank) continue;
            bestRank = rank;
            best = unit;
            bestAction = upgrade;
        }
        if (best == null || bestAction == null) return;
        if (view.credits < bestAction.credits() + Tune.UPGRADE_RESERVE) return;
        orders.add(RsiDecision.Order.action(best.id(), bestAction.id(), null, -1));
        board.investPot = Math.max(0, board.investPot - bestAction.credits());
        board.planned(bestAction.product(), best.at());
        board.log(view, "upgrade " + best.type() + " -> " + bestAction.product()
                + " cost=" + bestAction.credits());
    }

    /**
     * Only one factory per kind is ever upgraded: the level-2 menu is what matters, and the other
     * factories are better left at level 1 where they are cheap production capacity.
     */
    private static int upgradeRank(Unit unit, RsiView view) {
        String type = Knowledge.lower(unit.type());
        if (Knowledge.upgradedMenU(unit)) return 9;
        if (type.equals("landfactory")) {
            if (hasUpgraded(view, "landfactory")) return 9;
            return view.credits >= Tune.LAND_L2_MIN_CREDITS ? 0 : 6;
        }
        if (type.contains("mechfactory")) {
            if (hasUpgraded(view, "mechfactory")) return 9;
            return view.credits >= Tune.MECH_T2_MIN_CREDITS ? 1 : 7;
        }
        if (type.equals("airfactory")) return view.credits >= 4000 ? 3 : 8;
        return 9;
    }

    private static boolean hasUpgraded(RsiView view, String kind) {
        for (Unit unit : view.own.values()) {
            if (!unit.complete() || !Knowledge.lower(unit.type()).contains(kind)) continue;
            if (Knowledge.upgradedMenU(unit)) return true;
        }
        return false;
    }

    // ------------------------------------------------------------------ builders

    private void keepBuilderSupply(RsiView view, List<RsiDecision.Order> orders, Set<Long> used) {
        int builders = Knowledge.builders(view).size();
        for (Unit unit : view.own.values()) {
            if (unit.queued() > 0) builders += unit.queuedTypes().getOrDefault("builder", 0);
        }
        if (builders >= Tune.BUILDERS) return;
        for (Unit factory : view.own.values()) {
            if (!factory.complete() || factory.queued() != 0 || used.contains(factory.id())) continue;
            if (!Knowledge.canProduce(factory, "builder")) continue;
            orders.add(RsiDecision.Order.produce(factory.id(), "builder"));
            used.add(factory.id());
            return;
        }
    }

    /**
     * New units walk to the staging point on their own instead of joining the push one by one.
     * RALLY uses its own command channel, so it never competes with a movement order.
     */
    private void rally(RsiView view, List<RsiDecision.Order> orders) {
        Point stage = board.staging;
        if (stage == null) return;
        if (view.tick - board.lastRally < 600) return;
        board.lastRally = view.tick;
        for (Unit factory : view.own.values()) {
            if (!factory.complete() || !Knowledge.isFactory(factory.type())) continue;
            orders.add(RsiDecision.Order.at(RsiDecision.Kind.RALLY, List.of(factory.id()), stage));
        }
    }

    // ------------------------------------------------------------------ army

    private void produceArmy(RsiView view, List<RsiDecision.Order> orders, Set<Long> used,
                             double availableCredits) {
        // 投资的钱已经由经济段的地板留出来了，这里把剩下的全花在兵上；
        // 攒刺杀组时只留一小股，避免为了一个单位把整支部队停掉。
        double share = board.savingStrike ? Tune.SIEGE_SHARE : 1.0;
        double budget = Math.max(0, availableCredits) * share;
        double spent = 0;

        if (board.enemyAir && antiAirCount(view) < Tune.ANTI_AIR_MAX) {
            for (Unit factory : view.own.values()) {
                if (!factory.complete() || factory.queued() != 0 || used.contains(factory.id())) continue;
                String aa = firstReady(factory, ActionKind.PRODUCE, Knowledge::isAntiAir);
                if (aa == null) continue;
                orders.add(RsiDecision.Order.produce(factory.id(), aa));
                used.add(factory.id());
                board.record(aa);
                board.log(view, "produce anti-air " + aa);
                return;
            }
        }

        board.savingFor = 0;
        for (Unit factory : view.own.values()) {
            if (!factory.complete() || factory.queued() != 0 || used.contains(factory.id())) continue;
            if (Knowledge.isCommandCenter(factory.type())) continue;
            Choice choice = chooseUnit(view, factory);
            if (choice == null) continue;
            if (choice.type() == null) continue;
            int price = Knowledge.priceOf(factory, choice.type());
            if (spent + price > budget) continue;
            spent += price;
            orders.add(RsiDecision.Order.produce(factory.id(), choice.type()));
            used.add(factory.id());
            board.record(choice.type());
            board.log(view, "produce " + choice.type() + " at " + factory.type()
                    + " credits=" + Math.round(view.credits));
        }
    }

    /** Either the unit to build now, or "save for this instead" ({@code type == null}). */
    private record Choice(String type, double missing) { }

    private Choice chooseUnit(RsiView view, Unit factory) {
        String affordable = null;
        double affordableScore = 0;
        String best = null;
        double bestScore = 0;
        int bestPrice = 0;
        for (Action action : factory.actions()) {
            String product = action.product();
            if (product == null || action.kind() != ActionKind.PRODUCE) continue;
            if (Boolean.FALSE.equals(board.armed(product))) continue;
            double score = Knowledge.productionScore(product, action.credits());
            if (score <= 0) continue;
            score *= movementBonus(product);
            // 拆家阶段优先能打到炮塔外面的兵种：射程 290+ 的单位可以在对方炮塔射程外
            // 直接拆指挥中心，这是唯一"不跟大军换血"的赢法。
            if (board.siegeMode && board.range(product) >= Tune.SIEGE_RANGE) {
                score *= Tune.SIEGE_BIAS;
            }
            if (score > bestScore) {
                bestScore = score;
                best = product;
                bestPrice = action.credits();
            }
            if (!action.ready()) continue;
            if (score > affordableScore) {
                affordableScore = score;
                affordable = product;
            }
        }
        // 一个价值 4.9 倍的单位值得让工厂空转等钱；被打了就不等。
        if (best != null && bestScore >= Tune.SAVE_FOR_UNIT_SCORE && bestPrice > view.credits
                && board.raiders(view, 900).isEmpty() && board.armyCount(view) >= Tune.ARMY_FLOOR) {
            return new Choice(null, bestPrice - view.credits);
        }
        return affordable == null ? null : new Choice(affordable, 0);
    }

    /**
     * On a map where the enemy base is in another land region only hover and air units can ever
     * arrive, so the same credits are worth more on those movement types.
     */
    private double movementBonus(String product) {
        if (!(board.waterSeparated || board.offensiveBlocked) || !Tune.AUTO_HOVER) return 1.0;
        String movement = board.movement(product);
        if (movement == null) return 1.0;
        return switch (movement) {
            case "AIR" -> 1.6;
            case "HOVER", "OVER_CLIFF_WATER", "OVER_CLIFF" -> 2.4;
            case "WATER" -> 0.4;
            default -> 0.2;
        };
    }

    private static int antiAirCount(RsiView view) {
        int count = 0;
        for (Unit unit : view.own.values()) {
            if (unit.complete() && Knowledge.isAntiAir(unit.type())) count++;
        }
        return count;
    }

    private static String firstReady(Unit factory, ActionKind kind,
                                     java.util.function.Predicate<String> test) {
        for (Action action : factory.actions()) {
            String product = action.product();
            if (product == null || action.kind() != kind || !action.ready()) continue;
            if (test.test(product)) return product;
        }
        return null;
    }
}
