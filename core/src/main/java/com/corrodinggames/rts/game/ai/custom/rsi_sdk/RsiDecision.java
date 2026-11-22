package com.corrodinggames.rts.game.ai.custom.rsi_sdk;

import java.util.ArrayList;
import java.util.Collection;
import java.util.List;
import java.util.Set;

/** Proposed orders. A HOLD preserves the current order and suppresses fallback for this decision. */
public record RsiDecision(List<Order> orders, Set<Long> hold) {
    public RsiDecision {
        orders = List.copyOf(orders);
        hold = Set.copyOf(hold);
    }

    public static RsiDecision delegate() { return new RsiDecision(List.of(), Set.of()); }
    public static RsiDecision of(Order... orders) { return new RsiDecision(List.of(orders), Set.of()); }
    public static RsiDecision hold(Collection<Long> units) { return new RsiDecision(List.of(), Set.copyOf(units)); }

    public record Economy(RsiDecision work, double reserveCredits, double productionCredits) {
        public Economy(RsiDecision work, double reserveCredits) { this(work, reserveCredits, 0); }
        public static Economy delegate() { return new Economy(RsiDecision.delegate(), 0, 0); }
    }

    public enum Kind {
        MOVE, ATTACK_MOVE, ATTACK, GUARD, PATROL, STOP, ATTACK_MODE,
        BUILD, PRODUCE, ACTION, RALLY, REPAIR, RECLAIM, LOAD, UNLOAD
    }

    public enum Stance { IN_RANGE, RETURN_FIRE, HOLD_FIRE, GUARD, CHASE }

    /** Group orders use the normal engine formation. Use formation() for explicit slots. */
    public record Order(Kind kind, List<Long> actors, RsiView.Point point, long target,
                        String option, float pursuit, boolean queued) {
        public Order { actors = List.copyOf(actors); }

        public static Order at(Kind kind, Collection<Long> actors, RsiView.Point point) {
            return new Order(kind, List.copyOf(actors), point, -1, null, -1, false);
        }

        public static Order attackMove(Collection<Long> actors, RsiView.Point point, float pursuit) {
            return new Order(Kind.ATTACK_MOVE, List.copyOf(actors), point, -1, null, pursuit, false);
        }

        public static Order target(Kind kind, Collection<Long> actors, long target) {
            return new Order(kind, List.copyOf(actors), null, target, null, -1, false);
        }

        public static Order build(long builder, String type, RsiView.Point point) {
            return new Order(Kind.BUILD, List.of(builder), point, -1, type, -1, false);
        }

        public static Order produce(long factory, String type) {
            return new Order(Kind.PRODUCE, List.of(factory), null, -1, type, -1, false);
        }

        public static Order action(long actor, String actionId, RsiView.Point point, long target) {
            return new Order(Kind.ACTION, List.of(actor), point, target, actionId, -1, false);
        }

        public static Order stance(Collection<Long> actors, Stance stance) {
            return new Order(Kind.ATTACK_MODE, List.copyOf(actors), null, -1, stance.name(), -1, false);
        }

        public Order append() { return new Order(kind, actors, point, target, option, pursuit, true); }
    }

    /** Assign explicit positions. The engine still calculates paths, collision and weapons. */
    public static RsiDecision formation(List<Long> units, List<RsiView.Point> positions, boolean attackMove) {
        if (units.size() != positions.size() || Set.copyOf(units).size() != units.size()) {
            throw new IllegalArgumentException("A formation requires one slot per distinct unit");
        }
        List<Order> orders = new ArrayList<>(units.size());
        for (int i = 0; i < units.size(); i++) {
            orders.add(Order.at(attackMove ? Kind.ATTACK_MOVE : Kind.MOVE,
                    List.of(units.get(i)), positions.get(i)));
        }
        return new RsiDecision(orders, Set.of());
    }
}
