package com.corrodinggames.rts.game.ai.custom.rsi_sdk;

import com.corrodinggames.rts.game.ai.custom.rsi_sdk.RsiView.Module;
import com.corrodinggames.rts.game.units.*;
import com.corrodinggames.rts.game.units.actions.AbstractUnitAction;
import com.corrodinggames.rts.game.units.actions.ActionId;
import com.corrodinggames.rts.game.units.actions.ActionType;
import com.corrodinggames.rts.gameFramework.Command;
import io.github.rwx.geometry.PointF;

import static com.corrodinggames.rts.game.ai.custom.rsi_sdk.RsiDecision.Kind;
import static com.corrodinggames.rts.game.ai.custom.rsi_sdk.RsiView.*;
import static com.corrodinggames.rts.game.ai.custom.rsi_sdk.RsiView.OrderStatus.*;

import java.util.*;

final class RsiOrders {
    private enum Channel { ORDER, STANCE, RALLY }
    private static final int ORDER_LIMIT_PER_TICK = 256;
    private static final int FEEDBACK_LIMIT = 256;

    private static final class PendingBatch {
        final int tick;
        final List<OrderResult> results = new ArrayList<>();
        int omitted;

        PendingBatch(int tick) { this.tick = tick; }
    }

    private final Map<Long, EnumSet<Channel>> used = new HashMap<>();
    private final Map<Module, PendingBatch> feedback = new EnumMap<>(Module.class);
    private int tick = Integer.MIN_VALUE;
    private double remaining;
    private int issued;

    void begin(RsiView view) {
        if (tick == view.tick) return;
        tick = view.tick;
        used.clear();
        remaining = view.credits;
        issued = 0;
    }

    double credits() { return Math.max(0, remaining); }

    void beginModule(Module module) { feedback.put(module, new PendingBatch(tick)); }

    Map<Module, OrderBatch> feedback() {
        Map<Module, OrderBatch> snapshot = new EnumMap<>(Module.class);
        feedback.forEach((module, batch) -> snapshot.put(module, new OrderBatch(batch.tick, batch.results, batch.omitted)));
        return Collections.unmodifiableMap(snapshot);
    }

    boolean applyPolicy(RsiWorld world, RsiDecision decision, Collection<Long> allowed, Module scope,
                        double reserve) {
        apply(world, decision, allowed, scope, reserve, feedback.get(scope));
        return decision == null || decision.useFallback();
    }

    void apply(RsiWorld world, RsiDecision decision, Collection<Long> allowed, Module scope,
               double reserve) {
        apply(world, decision, allowed, scope, reserve, null);
    }

    private void apply(RsiWorld world, RsiDecision decision, Collection<Long> allowed, Module scope,
                       double reserve, PendingBatch batch) {
        if (decision == null) return;
        Set<Long> scopeIds = Set.copyOf(allowed);
        for (long id : decision.hold()) {
            if (scopeIds.contains(id)) mark(id, Channel.ORDER);
        }
        for (RsiDecision.Order order : decision.orders()) {
            if (issued >= ORDER_LIMIT_PER_TICK && batch == null) break;
            boolean record = batch != null && batch.results.size() < FEEDBACK_LIMIT;
            List<Long> submitted = record ? new ArrayList<>() : null;
            OrderStatus status;
            if (issued >= ORDER_LIMIT_PER_TICK) status = ORDER_LIMIT;
            else if (order.kind() == null) status = INVALID_ARGUMENT;
            else if (!permits(scope, order.kind())) status = OUTSIDE_SCOPE;
            else status = send(world, order, scopeIds, Math.max(0, reserve), submitted);
            if (record) batch.results.add(new OrderResult(order, status, submitted));
            else if (batch != null) batch.omitted++;
        }
    }

    private static boolean permits(Module scope, Kind kind) {
        return switch (kind) {
            case BUILD, REPAIR, RECLAIM -> scope == Module.ECONOMY;
            case PRODUCE, RALLY -> scope == Module.PRODUCTION;
            case LOAD, UNLOAD -> scope == Module.LOGISTICS;
            case ACTION, STOP -> true;
            case ATTACK, ATTACK_MOVE, ATTACK_MODE, GUARD, PATROL -> scope == Module.TACTICS;
            case MOVE -> scope != Module.PRODUCTION;
        };
    }

    private OrderStatus send(RsiWorld world, RsiDecision.Order order, Set<Long> allowed, double reserve,
                             List<Long> submitted) {
        Kind kind = order.kind();
        RsiView.Point at = order.point();
        if (at != null && !world.view.contains(at) || order.actors().isEmpty()) return INVALID_ARGUMENT;
        BaseUnit ownTarget = world.own.get(order.target());
        BaseUnit target = world.targets.get(order.target());
        Channel channel = switch (kind) {
            case ATTACK_MODE -> Channel.STANCE;
            case RALLY -> Channel.RALLY;
            default -> Channel.ORDER;
        };
        List<OrderableUnit> actors = new ArrayList<>();
        OrderStatus rejected = ACTOR_UNAVAILABLE;
        for (long id : new LinkedHashSet<>(order.actors())) {
            OrderableUnit unit = world.own.get(id);
            if (unit == null || !eligible(unit)) continue;
            if (!allowed.contains(id)) {
                rejected = OUTSIDE_SCOPE;
                continue;
            }
            EnumSet<Channel> channels = used.get(id);
            if (channels != null && channels.contains(channel)) {
                rejected = CHANNEL_USED;
                continue;
            }
            boolean suitable = switch (kind) {
                case MOVE, ATTACK_MOVE, PATROL -> at != null && unit.canExecuteMovementCommands();
                case ATTACK -> world.canAttack(id, order.target());
                case GUARD -> ownTarget != null && ownTarget != unit && unit.canExecuteMovementCommands();
                case REPAIR -> ownTarget != null && unit.canRepairTarget(ownTarget);
                case RECLAIM -> target != null && world.view.salvage.containsKey(order.target())
                        && unit.canReclaimTarget(target);
                case LOAD -> ownTarget != null && allowed.contains(order.target())
                        && world.canCarry(order.target(), id);
                case UNLOAD -> unit instanceof TransportUnitInterface carrier
                        && unit.canTransportUnits() && !carrier.isTransportUnloadingActive();
                case RALLY -> at != null && unit instanceof com.corrodinggames.rts.game.units.buildings.FactoryQueueInterface;
                default -> true;
            };
            if (suitable) actors.add(unit);
            else rejected = INVALID_TARGET;
        }
        if (actors.isEmpty()) return rejected;
        AttackMode mode = attackMode(order.option());
        if (kind == Kind.ATTACK_MODE && mode == null) return INVALID_ARGUMENT;

        AbstractUnitAction action = null;
        UnitType type = order.option() == null ? null : world.types.get(order.option());
        OrderableUnit first = actors.getFirst();
        if (kind == Kind.BUILD || kind == Kind.PRODUCE || kind == Kind.ACTION || kind == Kind.UNLOAD) {
            if (actors.size() != 1) return INVALID_ARGUMENT;
            if (kind == Kind.BUILD && (type == null || !type.isBuildingUnit() || at == null)) return INVALID_ARGUMENT;
            action = switch (kind) {
                case BUILD -> first.findActionForUnitType(type, true);
                case PRODUCE -> type != null && !type.isBuildingUnit() ? first.getUnitAction(type) : null;
                case UNLOAD -> findAction(first, first.getUnloadActionId());
                default -> findAction(first, order.option());
            };
            if (!RsiWorld.usable(action, first) || !RsiWorld.available(action, first)) return ACTION_UNAVAILABLE;
            ActionKind actionKind = RsiWorld.actionKind(action, first);
            if (kind == Kind.BUILD) {
                if (actionKind != ActionKind.BUILD) return ACTION_UNAVAILABLE;
                if (!world.context.canPlaceBuilding(type, at.x(), at.y())) return INVALID_PLACEMENT;
            } else if (kind == Kind.PRODUCE) {
                if (actionKind != ActionKind.PRODUCE) return ACTION_UNAVAILABLE;
            } else if (kind == Kind.ACTION) {
                if (actionKind == ActionKind.BUILD || actionKind == ActionKind.PRODUCE
                        || actionKind == ActionKind.OTHER && (action.isBuildOption()
                        || action.isQueuable() && !action.isCancel() && !action.isAiHighPriority(first))) {
                    return ACTION_UNAVAILABLE;
                }
                if (order.target() >= 0 && ownTarget == null && target == null
                        || action.getActionType() == ActionType.targetGround && at == null
                        || at != null && !first.a(action, at.x(), at.y())) return INVALID_TARGET;
            }
            int cost = action.isCancel() ? 0 : Math.max(0, action.getPrice().a());
            if (cost > 0 && cost > remaining - reserve) return INSUFFICIENT_CREDITS;
            if (!action.canAfford(first, false)) return ACTION_UNAVAILABLE;
            remaining -= cost;
        }

        Command command = world.context.command(actors.toArray(OrderableUnit[]::new));
        switch (kind) {
            case MOVE -> command.setMoveTarget(at.x(), at.y());
            case ATTACK_MOVE -> {
                command.setAttackMoveTarget(at.x(), at.y());
                if (Float.isFinite(order.pursuit()) && order.pursuit() >= 0) {
                    command.unitCommand.attackMoveRange = Math.min(order.pursuit(),
                            Math.max(world.view.width, world.view.height));
                }
            }
            case ATTACK -> command.setAttackTarget(target);
            case GUARD -> command.setGuardTarget(ownTarget);
            case PATROL -> command.setPatrolTarget(at.x(), at.y());
            case STOP -> command.setClearExistingOrders();
            case ATTACK_MODE -> command.setAttackMode(mode);
            case REPAIR -> command.setRepairTarget(ownTarget);
            case RECLAIM -> command.setReclaimTarget(target);
            case LOAD -> command.setLoadIntoTarget(ownTarget);
            case RALLY -> command.setRallyPoint(new PointF(at.x(), at.y()));
            case BUILD -> {
                if (action.usesActionTarget()) command.setActionTarget(action.getActionId(), new PointF(at.x(), at.y()), null);
                else command.setBuildTarget(at.x(), at.y(), type, action.getQueueSize());
            }
            case ACTION -> {
                if (at != null || ownTarget != null || target != null || action.isCancel()) {
                    command.setActionTarget(action.getActionId(), at == null ? null : new PointF(at.x(), at.y()),
                            ownTarget != null ? ownTarget : target);
                    if (action.isCancel()) command.stopCurrentAction = true;
                } else command.setActionId(action.getQueueId());
            }
            case PRODUCE, UNLOAD -> command.setActionId(action.getQueueId());
        }
        if (order.queued() && command.unitCommand != null) command.isQueued = true;
        for (OrderableUnit unit : actors) {
            mark(unit.objectId, channel);
            if (submitted != null) submitted.add(unit.objectId);
        }
        issued++;
        return SUBMITTED;
    }

    private static boolean eligible(OrderableUnit unit) {
        return !unit.isDead && unit.buildProgress >= 1 && unit.transportContainer == null
                && !unit.canNotBeGivenOrdersByPlayer();
    }

    private void mark(long id, Channel channel) {
        used.computeIfAbsent(id, ignored -> EnumSet.noneOf(Channel.class)).add(channel);
    }

    private static AbstractUnitAction findAction(OrderableUnit actor, ActionId id) {
        return id == null ? null : findAction(actor, id.getId());
    }

    private static AbstractUnitAction findAction(OrderableUnit actor, String id) {
        if (id == null) return null;
        for (AbstractUnitAction action : actor.getAvailableActions()) {
            if (id.equals(action.getActionIdString())) return action;
        }
        return null;
    }

    private static AttackMode attackMode(String name) {
        if (name == null) return null;
        return switch (name) {
            case "IN_RANGE" -> AttackMode.onlyInRange;
            case "RETURN_FIRE" -> AttackMode.returnFire;
            case "HOLD_FIRE" -> AttackMode.holdFire;
            case "GUARD" -> AttackMode.guardArea;
            case "CHASE" -> AttackMode.aggressive;
            default -> null;
        };
    }
}
