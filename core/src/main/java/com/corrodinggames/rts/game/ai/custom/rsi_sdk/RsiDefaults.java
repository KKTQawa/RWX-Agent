package com.corrodinggames.rts.game.ai.custom.rsi_sdk;

import com.corrodinggames.rts.game.units.BaseUnit;

import static com.corrodinggames.rts.game.ai.custom.rsi_sdk.RsiDecision.Kind;
import static com.corrodinggames.rts.game.ai.custom.rsi_sdk.RsiDecision.Order;
import static com.corrodinggames.rts.game.ai.custom.rsi_sdk.RsiView.*;

import java.util.*;

final class RsiDefaults {
    private RsiDefaults() { }

    static RsiDecision economy(RsiWorld world) {
        RsiView view = world.view;
        List<Order> result = new ArrayList<>();
        List<Point> reserved = new ArrayList<>();
        boolean hasFactory = view.own.values().stream().anyMatch(u -> u.type().endsWith("Factory"));
        for (Unit builder : view.own.values()) {
            if (!builder.builder() || !builder.mobile() || !builder.idle()) continue;
            if (!hasFactory) {
                for (Point slot : nearby(view, builder.at())) {
                    result.add(Order.build(builder.id(), "landFactory", slot));
                }
            }
            for (Point ore : view.resourcePools.stream()
                    .filter(p -> view.canApproach(builder, p, 60) && !occupied(view, p)
                            && reserved.stream().noneMatch(q -> q.distanceSquared(p) < 400))
                    .sorted(Comparator.comparingDouble(builder.at()::distanceSquared)).limit(3).toList()) {
                boolean proposed = false;
                for (Action action : builder.actions()) {
                    var type = action.product() == null ? null : world.types.get(action.product());
                    if (action.ready() && action.kind() == ActionKind.BUILD && type != null && type.p()) {
                        result.add(Order.build(builder.id(), action.product(), ore));
                        proposed = true;
                    }
                }
                if (proposed) reserved.add(ore);
            }
            if (hasFactory && view.credits >= 4500) {
                for (Point slot : nearby(view, builder.at())) {
                    result.add(Order.build(builder.id(), "fabricator", slot));
                }
            }
        }
        return new RsiDecision(result, Set.of());
    }

    private static boolean occupied(RsiView view, Point at) {
        return view.own.values().stream().anyMatch(u -> u.building() && u.at().distanceSquared(at) < 1600)
                || view.visible.values().stream().anyMatch(u -> u.building() && u.at().distanceSquared(at) < 1600);
    }

    private static List<Point> nearby(RsiView view, Point center) {
        List<Point> slots = new ArrayList<>();
        for (int i = 0; i < 8; i++) {
            double angle = Math.PI * i / 4;
            Point at = new Point(center.x() + (float) Math.cos(angle) * 110,
                    center.y() + (float) Math.sin(angle) * 110);
            if (view.contains(at) && !occupied(view, at)) slots.add(at);
        }
        return slots;
    }

    static RsiDecision production(RsiWorld world) {
        List<Order> result = new ArrayList<>();
        long builders = world.view.own.values().stream().filter(u -> u.builder() && u.mobile()).count();
        builders += world.view.own.values().stream().mapToInt(u -> u.queuedTypes().getOrDefault("builder", 0)).sum();
        for (Unit producer : world.view.own.values()) {
            if (!producer.complete() || producer.queued() > 0) continue;
            if (builders < 2 && producer.actions().stream().anyMatch(a -> a.ready()
                    && a.kind() == ActionKind.PRODUCE && "builder".equals(a.product()))) {
                result.add(Order.produce(producer.id(), "builder"));
                builders++;
            }
            producer.actions().stream()
                    .filter(a -> a.ready() && a.kind() == ActionKind.PRODUCE && combat(world, a.product()))
                    .sorted(Comparator.comparingInt(Action::credits).reversed().thenComparing(Action::id))
                    .limit(5).forEach(a -> result.add(Order.produce(producer.id(), a.product())));
        }
        return new RsiDecision(result, Set.of());
    }

    private static boolean combat(RsiWorld world, String id) {
        var type = world.types.get(id);
        if (type == null || type.isBuildingUnit()) return false;
        BaseUnit unit = BaseUnit.getPrototypeForUnitType(type);
        return unit != null && unit.canAttack();
    }

    static List<Squad> squads(RsiView view, Set<Long> reserved) {
        Map<String, List<Long>> byMovement = new TreeMap<>();
        for (Unit unit : view.own.values()) {
            if (!unit.mobile() || !unit.armed() || unit.builder() || unit.transport() || unit.carrier() >= 0
                    || reserved.contains(unit.id())) continue;
            byMovement.computeIfAbsent(unit.movement(), ignored -> new ArrayList<>()).add(unit.id());
        }
        List<Squad> result = new ArrayList<>();
        for (var entry : byMovement.entrySet()) {
            List<Long> units = entry.getValue();
            Unit lead = view.own.get(units.getFirst());
            Point goal = view.lastSeen.values().stream().filter(c -> view.canReach(lead, c.at()))
                    .min(Comparator.comparingDouble(c -> lead.at().distanceSquared(c.at())))
                    .map(Contact::at).orElseGet(() -> scout(view, lead));
            result.add(new Squad("default-" + entry.getKey(), units, goal));
        }
        return result;
    }

    private static Point scout(RsiView view, Unit lead) {
        Point center = new Point(view.width / 2, view.height / 2);
        return view.resourcePools.stream().filter(p -> !view.visibleAt(p) && view.canReach(lead, p))
                .min(Comparator.comparingDouble(lead.at()::distanceSquared))
                .orElse(view.canReach(lead, center) ? center : lead.at());
    }

    static RsiDecision tactics(RsiView view, Squad squad) {
        List<Order> result = new ArrayList<>();
        List<Long> moving = new ArrayList<>();
        for (long id : squad.units()) {
            Unit unit = view.own.get(id);
            if (unit == null || !unit.idle()) continue;
            Contact enemy = view.search(unit.at(), Math.max(350, unit.range())).stream()
                    .filter(c -> view.canAttack(id, c.id()))
                    .findFirst().orElse(null);
            if (enemy != null) result.add(Order.target(Kind.ATTACK, List.of(id), enemy.id()));
            else if (squad.goal() != null && unit.at().distanceSquared(squad.goal()) > 2500
                    && view.canReach(unit, squad.goal())) moving.add(id);
        }
        if (!moving.isEmpty()) result.add(Order.attackMove(moving, squad.goal(), 160));
        return new RsiDecision(result, Set.of());
    }

    static RsiDecision transport(RsiView view, Transport mission, Set<Long> delivered, boolean finishTrip) {
        Unit carrier = view.own.get(mission.carrier());
        List<Order> result = new ArrayList<>();
        List<Long> waiting = new ArrayList<>();
        boolean ourPassengersAboard = false;
        for (long id : mission.passengers()) {
            Unit unit = view.own.get(id);
            if (unit == null || delivered.contains(id)) continue;
            if (unit.carrier() == carrier.id()) ourPassengersAboard = true;
            else if (unit.carrier() < 0) waiting.add(id);
        }
        boolean nearPickup = carrier.at().distanceSquared(mission.pickup()) < 8100;
        boolean canTakeMore = waiting.stream().anyMatch(id -> view.canCarry(carrier.id(), id));
        if (ourPassengersAboard && (finishTrip || !canTakeMore || waiting.isEmpty() || !nearPickup)) {
            if (carrier.at().distanceSquared(mission.dropoff()) < 2500) {
                result.add(Order.at(Kind.UNLOAD, List.of(carrier.id()), null));
            } else if (carrier.idle() || nearPickup) {
                result.add(Order.at(Kind.MOVE, List.of(carrier.id()), mission.dropoff()));
            }
        } else if (!finishTrip && !waiting.isEmpty()) {
            if (!nearPickup && carrier.idle()) result.add(Order.at(Kind.MOVE, List.of(carrier.id()), mission.pickup()));
            for (long id : waiting) {
                Unit unit = view.own.get(id);
                if (nearPickup && unit.at().distanceSquared(carrier.at()) < 14400 && view.canCarry(carrier.id(), id)) {
                    if (!"loadInto".equals(unit.waypoint())) result.add(Order.target(Kind.LOAD, List.of(id), carrier.id()));
                } else if (unit.idle() && unit.at().distanceSquared(mission.pickup()) > 900) {
                    result.add(Order.at(Kind.MOVE, List.of(id), mission.pickup()));
                }
            }
        }
        return new RsiDecision(result, Set.of());
    }
}
