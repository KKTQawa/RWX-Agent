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
 * Construction and income: what to build next, where, and which extractor to upgrade.
 *
 * <p>Two purchases compete for credits: capacity (a factory converts income into army) and income
 * (an extractor returns its price in about half a minute at room income x2, an upgrade in a couple
 * of minutes). The ladder keeps the two balanced — factories up to what the current income can
 * feed, everything else into pools and then their upgrade tiers.
 */
final class BuildPlanner extends RsiStrategy.Economy {
    private final Blackboard board;

    BuildPlanner(Blackboard board) {
        this.board = board;
    }

    @Override
    protected RsiDecision.Economy plan(RsiView view) {
        board.observe(view);
        List<RsiDecision.Order> orders = new ArrayList<>();
        Set<Long> busy = new HashSet<>();

        builders(view, orders, busy);
        repair(view, orders, busy);

        reportRejections(view);
        board.wantIncome = view.resourcePools.size() > Knowledge.countAny(view, Knowledge::isExtractor);
        // 经济段只负责工兵（建造/维修）。建筑的升级动作不在经济段的 allowed 集合里，
        // 必须由排产模块下——那里 allowed 是"所有建筑"。
        return new RsiDecision.Economy(new RsiDecision(orders, Set.of()).exclusive(), 0, 0,
                investmentFloor(view));
    }

    /**
     * Continuous investment budget. A fixed share of income accumulates in the pot; production may
     * not spend below it. The floor collapses the moment the next purchase is affordable, so the
     * purchase itself (issued by the production module) is never blocked by its own reserve.
     */
    private double investmentFloor(RsiView view) {
        int dt = Math.max(0, view.tick - board.potTick);
        board.potTick = view.tick;
        double target = nextInvestment(view);
        if (target <= 0) {
            board.investPot = 0;
            board.savingStrike = false;
            return 0;
        }
        if (dt > 0 && dt < 60) {
            board.investPot += view.income * Tune.INVEST_SHARE * dt / 60.0;
        }
        board.investPot = Math.min(board.investPot, target);
        board.savingStrike = target >= Tune.LASER_PRICE;
        if (Tune.DEBUG && view.tick - board.lastInvestLog >= 900) {
            board.lastInvestLog = view.tick;
            board.log(view, "invest pot=" + Math.round(board.investPot) + " target="
                    + Math.round(target) + " credits=" + Math.round(view.credits));
        }
        if (view.credits >= target) return 0;
        return Math.min(board.investPot, view.credits);
    }

    /** Price of the cheapest thing worth banking for right now, or 0. */
    private double nextInvestment(RsiView view) {
        double cheapest = 0;
        for (Unit unit : view.own.values()) {
            if (!unit.complete()) continue;
            RsiView.Action upgrade = Knowledge.upgradeAction(unit);
            if (upgrade == null || upgrade.credits() <= 0) continue;
            double need = upgrade.credits() + Tune.UPGRADE_RESERVE;
            if (view.credits >= need) continue;
            if (cheapest == 0 || need < cheapest) cheapest = need;
        }
        if (Tune.LASER_COUNT > 0 && Knowledge.canBuild(view, "mechlaser")
                && Knowledge.count(view, t -> Knowledge.lower(t).equals("mechlaser")) < Tune.LASER_COUNT
                && view.credits < Tune.LASER_PRICE
                && (cheapest == 0 || Tune.LASER_PRICE < cheapest)) {
            cheapest = Tune.LASER_PRICE;
        }
        return cheapest;
    }

    /** The SDK hands back a receipt per order; a rejected upgrade would otherwise just repeat. */
    private void reportRejections(RsiView view) {
        if (!Tune.DEBUG) return;
        for (RsiView.Module module : RsiView.Module.values()) {
            RsiView.OrderBatch batch = view.orderFeedback.get(module);
            if (batch == null) continue;
            for (RsiView.OrderResult result : batch.results()) {
                if (result.status() == RsiView.OrderStatus.SUBMITTED) continue;
                if (result.status() == RsiView.OrderStatus.INVALID_PLACEMENT) {
                    board.markBad(result.order().point());
                }
                board.log(view, "rejected " + module + " " + result.order().kind()
                        + " " + result.order().option() + " -> " + result.status());
            }
        }
    }

    // ------------------------------------------------------------------ builders

    private void builders(RsiView view, List<RsiDecision.Order> orders, Set<Long> busy) {
        double budget = view.credits;
        for (Unit builder : Knowledge.builders(view)) {
            if (!builder.idle() || budget < 200) continue;
            Build task = choose(view, builder);
            if (task == null) {
                reclaim(view, builder, orders, busy);
                continue;
            }
            double price = Knowledge.priceOf(board, task.type());
            if (price > budget) continue;
            budget -= price;
            orders.add(RsiDecision.Order.build(builder.id(), task.type(), task.at()));
            busy.add(builder.id());
            board.planned(task.type(), task.at());
            board.log(view, "build " + task.type() + " at " + Math.round(task.at().x()) + ","
                    + Math.round(task.at().y()) + " credits=" + Math.round(view.credits));
        }
    }

    /**
     * An idle builder with nothing left to build goes and reclaims visible wreckage: the SDK exposes
     * the salvage points (`view.salvage`) and a RECLAIM order for builders, so a long attrition game
     * has one more income stream that costs no factories. Nothing else in the ladder competes with
     * it because it only runs when {@link #choose} found no task at all.
     */
    private void reclaim(RsiView view, Unit builder, List<RsiDecision.Order> orders, Set<Long> busy) {
        if (!Tune.RECLAIM || view.salvage.isEmpty()) return;
        long best = -1;
        double distance = Tune.RECLAIM_RADIUS * Tune.RECLAIM_RADIUS;
        for (var entry : view.salvage.entrySet()) {
            double d = builder.at().distanceSquared(entry.getValue());
            if (d >= distance) continue;
            if (!view.canApproach(builder, entry.getValue(), 45)) continue;
            distance = d;
            best = entry.getKey();
        }
        if (best < 0) return;
        orders.add(RsiDecision.Order.target(RsiDecision.Kind.RECLAIM, List.of(builder.id()), best));
        busy.add(builder.id());
        board.log(view, "reclaim #" + best + " d=" + Math.round(Math.sqrt(distance)));
    }

    private record Build(String type, Point at) { }

    private Build choose(RsiView view, Unit builder) {
        if (board.base == null) return null;
        String movement = builder.movement();
        int extractors = total(view, Knowledge::isExtractor);
        int factories = total(view, Knowledge::isFactory);
        int land = total(view, t -> Knowledge.lower(t).equals("landfactory"));
        int mech = total(view, t -> Knowledge.lower(t).contains("mechfactory"));
        int turrets = total(view, Knowledge::isTurret);
        int antiAir = total(view, t -> Knowledge.lower(t).contains("antiair"));
        int fabricators = total(view, Knowledge::isFabricator);
        List<Point> pools = board.freePools(view, builder);
        boolean threatened = !board.raiders(view, 1100).isEmpty();
        int wantFactories = Tune.factoryTarget(view.income);

        if (land < 1) return building(view, builder, movement,
                t -> Knowledge.lower(t).equals("landfactory"), 1, 0);
        if (extractors < 2 && !pools.isEmpty()) return extractor(view, builder, pools);
        // 先插一座炮塔：它每信用点的输出是机动单位的 2-3 倍，而 1.4-3.7 倍收入的对手
        // 第一波进攻通常比"被看见"更早。等挨打再盖就来不及了。
        if (turrets < Tune.EARLY_TURRETS) {
            Build early = building(view, builder, movement, Knowledge::isTurret,
                    Tune.EARLY_TURRETS, 200);
            if (early != null) return early;
        }
        if (factories < wantFactories && view.credits >= 1600) {
            Build capacity = capacity(view, builder, movement, land, mech, wantFactories);
            if (capacity != null) return capacity;
        }
        if (!pools.isEmpty()) return extractor(view, builder, pools);
        if (factories < wantFactories) {
            Build capacity = capacity(view, builder, movement, land, mech, wantFactories);
            if (capacity != null) return capacity;
        }
        if (threatened && turrets < Tune.TURRET_MAX) {
            Build turret = building(view, builder, movement, Knowledge::isTurret,
                    Tune.TURRET_MAX, 300);
            if (turret != null) return turret;
        }
        if (board.enemyAir && antiAir < Tune.ANTI_AIR_MAX) {
            Build aa = building(view, builder, movement,
                    t -> Knowledge.lower(t).contains("antiair"), Tune.ANTI_AIR_MAX, 300);
            if (aa != null) return aa;
        }
        if (mech < 2 && view.credits >= 1200) {
            Build mech2 = building(view, builder, movement,
                    t -> Knowledge.lower(t).contains("mechfactory"), 2, 0);
            if (mech2 != null) return mech2;
        }
        // 陆军到不了对面的图（岛、湖、悬崖）必须有飞到空中的东西，否则整支军队只能站家里。
        if (board.waterSeparated && total(view, t -> Knowledge.lower(t).contains("airfactory"))
                < Tune.AIR_FACTORY_MAX && view.credits >= 1200) {
            Build air = building(view, builder, movement,
                    t -> Knowledge.lower(t).contains("airfactory"), Tune.AIR_FACTORY_MAX, 0);
            if (air != null) return air;
        }
        if (land < Tune.LAND_FACTORY_MAX && view.credits >= 1200) {
            Build more = building(view, builder, movement,
                    t -> Knowledge.lower(t).equals("landfactory"), Tune.LAND_FACTORY_MAX, 0);
            if (more != null) return more;
        }
        if (fabricators < Tune.FABRICATOR_MAX && view.credits >= Tune.FABRICATOR_MIN_CREDITS) {
            Build fabricator = building(view, builder, movement, Knowledge::isFabricator,
                    Tune.FABRICATOR_MAX, 2200);
            if (fabricator != null) return fabricator;
        }
        if (turrets < Tune.TURRET_MAX && view.credits >= 1500) {
            Build turret = building(view, builder, movement, Knowledge::isTurret,
                    Tune.TURRET_MAX, 300);
            if (turret != null) return turret;
        }
        return null;
    }

    /**
     * The next production building. Roughly one mech factory per three land factories: mech units
     * carry the mechLaser unlock, land factories are the cheaper way to turn income into units.
     */
    private Build capacity(RsiView view, Unit builder, String movement, int land, int mech,
                           int wantFactories) {
        int wantMech = Math.max(1, wantFactories / 3);
        if (mech < wantMech) {
            Build mechFactory = building(view, builder, movement,
                    t -> Knowledge.lower(t).contains("mechfactory"), wantMech, 0);
            if (mechFactory != null) return mechFactory;
        }
        return building(view, builder, movement,
                t -> Knowledge.lower(t).equals("landfactory"), wantFactories, 0);
    }

    /** Existing plus already-ordered buildings of this kind, so the ladder is not double-spent. */
    private int total(RsiView view, java.util.function.Predicate<String> kind) {
        return Knowledge.countAny(view, kind) + board.pending(kind);
    }

    private Build extractor(RsiView view, Unit builder, List<Point> pools) {
        String type = pickBuildable(builder, Knowledge::isExtractor);
        if (type == null) return null;
        if (view.credits < Tune.EXTRACTOR_MIN_CREDITS) return null;
        if (total(view, Knowledge::isExtractor) >= Tune.EXTRACTOR_MAX) return null;
        for (Point pool : pools) {
            if (board.repeat(type, pool)) continue;
            return new Build(type, pool);
        }
        return null;
    }

    /** Build a type matching {@code kind} next to the base, if the builder has such an action. */
    private Build building(RsiView view, Unit builder, String movement,
                           java.util.function.Predicate<String> kind, int cap, int minCredits) {
        if (total(view, kind) >= cap) return null;
        String type = pickBuildable(builder, kind);
        if (type == null) return null;
        int price = priceOf(builder, type);
        if (view.credits < price + minCredits) return null;
        // Widen the ring when the close one is full: a base packed with extractors and turrets has
        // no free slot inside 300 units, and a builder with nowhere to put a factory sits idle with
        // the whole bank in hand (that is how a team AI ends a match with 165k credits and no army).
        for (float[] ring : new float[][]{{80, 300}, {250, 620}, {500, 1_000}}) {
            for (Point spot : board.spots(view, board.base, ring[0], ring[1], movement, 105)) {
                if (board.repeat(type, spot)) continue;
                if (!view.canReach(builder, spot)) continue;
                return new Build(type, spot);
            }
        }
        return null;
    }

    private static String pickBuildable(Unit builder, java.util.function.Predicate<String> kind) {
        String best = null;
        int bestPrice = Integer.MAX_VALUE;
        for (Action action : builder.actions()) {
            String product = action.product();
            if (product == null || action.kind() != ActionKind.BUILD || !kind.test(product)) continue;
            if (!action.ready()) continue;
            if (action.credits() < bestPrice) {
                bestPrice = action.credits();
                best = product;
            }
        }
        return best;
    }

    private static int priceOf(Unit builder, String type) {
        for (Action action : builder.actions()) {
            if (type.equals(action.product())) return action.credits();
        }
        return 0;
    }

    // ------------------------------------------------------------------ repair

    private void repair(RsiView view, List<RsiDecision.Order> orders, Set<Long> busy) {
        // 血量低、离工兵近、是关键建筑的先修。
        for (Unit builder : Knowledge.builders(view)) {
            if (!builder.idle() || busy.contains(builder.id())) continue;
            Unit patient = repairTarget(view, builder);
            if (patient == null) continue;
            orders.add(RsiDecision.Order.target(RsiDecision.Kind.REPAIR,
                    List.of(builder.id()), patient.id()));
            busy.add(builder.id());
            board.log(view, "repair " + patient.type() + " hp=" + patient.healthFraction());
        }
    }

    private Unit repairTarget(RsiView view, Unit builder) {
        Unit best = null;
        double bestScore = 0;
        for (Unit unit : view.own.values()) {
            if (!unit.building() || unit.healthFraction() >= 0.92) continue;
            if (!view.canReach(builder, unit.at())) continue;
            double value = Knowledge.isCommandCenter(unit.type()) ? 4.0
                    : Knowledge.isFactory(unit.type()) ? 2.0
                    : Knowledge.isExtractor(unit.type()) ? 2.5 : 1.0;
            double missing = 1 - unit.healthFraction();
            double score = value * missing
                    / (1 + builder.at().distanceSquared(unit.at()) / 2_000_000.0);
            if (score > bestScore) {
                bestScore = score;
                best = unit;
            }
        }
        return bestScore > 0.02 ? best : null;
    }
}
