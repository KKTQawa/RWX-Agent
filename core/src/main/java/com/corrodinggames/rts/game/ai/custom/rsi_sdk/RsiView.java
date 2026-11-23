package com.corrodinggames.rts.game.ai.custom.rsi_sdk;

import java.util.List;
import java.util.Map;
import java.util.Optional;

/** A game-thread observation containing values and IDs, never mutable engine entities. */
public final class RsiView {
    public record Point(float x, float y) {
        public double distanceSquared(Point other) {
            double dx = x - other.x;
            double dy = y - other.y;
            return dx * dx + dy * dy;
        }
    }

    public enum ActionKind { BUILD, PRODUCE, UPGRADE, ABILITY, OTHER }

    public record Action(String id, String product, int credits, boolean ready, boolean placement,
                         boolean targeted, boolean queueable, ActionKind kind, boolean requiresPoint) { }

    public enum Module { ECONOMY, PRODUCTION, TACTICS, LOGISTICS }

    public enum OrderStatus {
        SUBMITTED, INVALID_ARGUMENT, OUTSIDE_SCOPE, ACTOR_UNAVAILABLE, CHANNEL_USED,
        INVALID_TARGET, INVALID_PLACEMENT, ACTION_UNAVAILABLE, INSUFFICIENT_CREDITS, ORDER_LIMIT
    }

    /** A group can submit only a subset of its actors. Engine execution can still fail later. */
    public record OrderResult(RsiDecision.Order order, OrderStatus status, List<Long> submittedActors) {
        public OrderResult { submittedActors = List.copyOf(submittedActors); }
    }

    public record OrderBatch(int tick, List<OrderResult> results, int omitted) {
        public OrderBatch { results = List.copyOf(results); }
    }

    public record Unit(long id, String type, Point at, String movement, float healthFraction,
                       boolean building, boolean builder, boolean armed, boolean mobile, boolean idle,
                       boolean complete, long carrier, int passengers, int queued, float range,
                       String waypoint, List<Action> actions, Map<String, Integer> queuedTypes,
                       float health, float maxHealth, float buildProgress) {
        public Unit {
            actions = List.copyOf(actions);
            queuedTypes = Map.copyOf(queuedTypes);
        }
        public boolean transport() { return passengers >= 0; }
    }

    public record Contact(long id, String type, Point at, boolean building, boolean airborne,
                          boolean submerged, float healthFraction, int lastSeenTick) { }
    public record Ally(long id, int teamId, String type, Point at, boolean building, float healthFraction,
                       float buildProgress) { }

    public record Squad(String id, List<Long> units, Point goal) {
        public Squad { units = List.copyOf(units); }
    }

    public record Transport(long carrier, List<Long> passengers, Point pickup, Point dropoff, int untilTick) {
        public Transport { passengers = List.copyOf(passengers); }
    }

    interface Terrain {
        boolean visible(Point at);
        boolean passable(Point at, String movement);
        boolean connected(Point from, Point to, String movement);
        boolean canAttack(long actor, long target);
        boolean canCarry(long carrier, long passenger);
    }

    private final Terrain terrain;
    public final int tick;
    public final int gameTimeMillis;
    public final double credits;
    public final double income;
    public final float width;
    public final float height;
    public final Map<Long, Unit> own;
    public final Map<Long, Contact> visible;
    public final Map<Long, Contact> lastSeen;
    public final Map<Long, Ally> allies;
    public final Map<Long, Point> salvage;
    public final List<Point> resourcePools;
    /** Most recent completed dispatch of each module, excluding SDK fallback orders. */
    public final Map<Module, OrderBatch> orderFeedback;

    RsiView(Terrain terrain, int tick, int gameTimeMillis, double credits, double income,
            float width, float height, Map<Long, Unit> own, Map<Long, Contact> visible,
            Map<Long, Contact> lastSeen, Map<Long, Ally> allies, Map<Long, Point> salvage,
            List<Point> resourcePools, Map<Module, OrderBatch> orderFeedback) {
        this.terrain = terrain;
        this.tick = tick;
        this.gameTimeMillis = gameTimeMillis;
        this.credits = credits;
        this.income = income;
        this.width = width;
        this.height = height;
        this.own = own;
        this.visible = visible;
        this.lastSeen = lastSeen;
        this.allies = allies;
        this.salvage = salvage;
        this.resourcePools = List.copyOf(resourcePools);
        this.orderFeedback = orderFeedback;
    }

    public boolean contains(Point at) {
        return at != null && at.x() >= 0 && at.y() >= 0 && at.x() < width && at.y() < height;
    }

    public boolean visibleAt(Point at) { return contains(at) && terrain.visible(at); }

    public boolean passable(Point at, String movement) {
        return contains(at) && terrain.passable(at, movement);
    }

    /** Static map connectivity. Dynamic obstacles and path execution stay in the engine. */
    public boolean canReach(Unit unit, Point at) {
        return contains(at) && terrain.connected(unit.at(), at, unit.movement());
    }

    /** Building and attack targets can be approached from nearby terrain even if their tile is blocked. */
    public boolean canApproach(Unit unit, Point at, float radius) {
        if (!contains(at) || !Float.isFinite(radius) || radius <= 0) return false;
        if (canReach(unit, at)) return true;
        for (int i = 0; i < 8; i++) {
            double angle = i * Math.PI / 4;
            if (canReach(unit, new Point(at.x() + radius * (float) Math.cos(angle),
                    at.y() + radius * (float) Math.sin(angle)))) return true;
        }
        return false;
    }

    /** Visible contacts in search radius, ordered by distance; historical contacts are separate. */
    public List<Contact> search(Point from, float radius) {
        if (!contains(from) || !Float.isFinite(radius) || radius < 0) return List.of();
        double radiusSquared = (double) radius * radius;
        return visible.values().stream().filter(c -> from.distanceSquared(c.at()) <= radiusSquared)
                .sorted(java.util.Comparator.comparingDouble((Contact c) -> from.distanceSquared(c.at()))
                        .thenComparingLong(Contact::id)).toList();
    }

    public Optional<Unit> unit(long id) { return Optional.ofNullable(own.get(id)); }

    public boolean canAttack(long actor, long target) { return terrain.canAttack(actor, target); }
    public boolean canCarry(long carrier, long passenger) { return terrain.canCarry(carrier, passenger); }
}
