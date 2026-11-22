package com.corrodinggames.rts.game.ai.custom.rsi_sdk;

import com.corrodinggames.rts.game.ai.custom.util.AiMapGraph;
import com.corrodinggames.rts.game.ai.strategy.AiContext;
import com.corrodinggames.rts.game.map.TileMap;
import com.corrodinggames.rts.game.units.*;
import com.corrodinggames.rts.game.units.actions.AbstractUnitAction;
import com.corrodinggames.rts.game.units.actions.ActionType;
import com.corrodinggames.rts.game.units.buildings.FactoryQueueInterface;
import com.corrodinggames.rts.gameFramework.GameEngine;
import java.util.*;

final class RsiWorld implements RsiView.Terrain {
    final AiContext context;
    final Map<Long, OrderableUnit> own = new TreeMap<>();
    final Map<Long, BaseUnit> targets = new TreeMap<>();
    final RsiView view;
    final Map<String, UnitType> types;
    private final GameEngine engine = GameEngine.getInstance();

    RsiWorld(AiContext context, Map<Long, RsiView.Contact> memory, Map<String, UnitType> types,
             List<RsiView.Point> resourcePools) {
        this.context = context;
        this.types = types;
        Map<Long, RsiView.Unit> units = new TreeMap<>();
        Map<Long, RsiView.Contact> contacts = new TreeMap<>();
        for (OrderableUnit unit : context.ownUnits()) {
            own.put(unit.objectId, unit);
            units.put(unit.objectId, describe(unit));
        }
        for (BaseUnit unit : context.visibleEnemies()) {
            if (unit.transportContainer != null || !visible(point(unit))) continue;
            targets.put(unit.objectId, unit);
            RsiView.Contact seen = new RsiView.Contact(unit.objectId, unit.r().v(), point(unit),
                    unit.r().isBuildingUnit(), unit.i(), unit.Q(), health(unit), context.tick());
            contacts.put(unit.objectId, seen);
            memory.put(unit.objectId, seen);
        }
        Map<Long, RsiView.Point> salvage = new TreeMap<>();
        for (BaseUnit unit : BaseUnit.bE) {
            if (unit.isDead || unit.team == null || unit.team.teamId >= 0 || unit.transportContainer != null
                    || !visible(point(unit)) || unit.getResourceRate() <= 0) continue;
            targets.put(unit.objectId, unit);
            salvage.put(unit.objectId, point(unit));
        }
        memory.values().removeIf(c -> !contacts.containsKey(c.id())
                && (visible(c.at()) || context.tick() - c.lastSeenTick() > 22_500));
        view = new RsiView(this, context.tick(), engine.gameTimeMillis, context.credits(),
                context.team().getScaledIncomeRate(), engine.tileMap.getWorldWidth(), engine.tileMap.getWorldHeight(),
                Collections.unmodifiableMap(units), Collections.unmodifiableMap(contacts),
                Collections.unmodifiableMap(new TreeMap<>(memory)), Collections.unmodifiableMap(salvage), resourcePools);
    }

    private RsiView.Unit describe(OrderableUnit unit) {
        List<RsiView.Action> actions = new ArrayList<>();
        Map<String, Integer> queued = new TreeMap<>();
        for (AbstractUnitAction action : unit.getAvailableActions()) {
            if (!usable(action, unit)) continue;
            UnitType product = action.getUnitType();
            boolean placement = action.getActionType() == ActionType.placeBuilding
                    || product != null && product.isBuildingUnit() && action.isBuildOption() && !action.isQueuable();
            String type = product == null ? null : product.v();
            actions.add(new RsiView.Action(action.getActionIdString(), type, action.getPrice().a(), ready(action, unit),
                    placement, action.usesActionTarget(), action.isQueuable()));
            if (type != null && unit instanceof FactoryQueueInterface factory) {
                int count = factory.h(product);
                if (count > 0) queued.put(type, count);
            }
        }
        UnitCommand current = unit.getCurrentWaypoint();
        return new RsiView.Unit(unit.objectId, unit.r().v(), point(unit), unit.getMovementType().name(),
                health(unit), unit.r().isBuildingUnit(), unit.r().m(), unit.canAttack(),
                unit.canExecuteMovementCommands(), unit.hasNoCurrentWaypoint(), unit.buildProgress >= 1,
                unit.transportContainer == null ? -1 : unit.transportContainer.objectId,
                unit instanceof TransportUnitInterface carrier && unit.canTransportUnits()
                        ? carrier.getTransportedUnitCount() : -1,
                unit instanceof FactoryQueueInterface factory ? factory.f(false) : -1,
                unit.m(), current == null ? "" : current.getCommandType().name(),
                actions, queued);
    }

    static RsiView.Point point(BaseUnit unit) { return new RsiView.Point(unit.posX, unit.posY); }

    static List<RsiView.Point> resourcePools() {
        TileMap map = GameEngine.getInstance().tileMap;
        List<RsiView.Point> pools = new ArrayList<>();
        for (int x = 0; x < map.tileCountX; x++) {
            for (int y = 0; y < map.tileCountY; y++) {
                var tile = map.getPathingOverrideTileAt(x, y);
                if (tile != null && tile.isResourcePool) {
                    pools.add(new RsiView.Point(AiMapGraph.tileCenterX(x), AiMapGraph.tileCenterY(y)));
                }
            }
        }
        return List.copyOf(pools);
    }

    private static float health(BaseUnit unit) {
        return unit.maxHealth > 0 ? unit.currentHealth / unit.maxHealth : 0;
    }

    static boolean usable(AbstractUnitAction action, OrderableUnit actor) {
        return action != null && action.getActionId() != null && !action.isAiDisabled(actor)
                && !action.isDisplayOnly() && action.getActionType() != ActionType.infoOnly
                && action.getActionType() != ActionType.pingMap
                && (action.getUnitType() == null || !action.getUnitType().w());
    }

    static boolean ready(AbstractUnitAction action, OrderableUnit actor) {
        return usable(action, actor) && action.b(actor) && !action.isNotAvailable(actor)
                && action.canAfford(actor, false)
                && !(action.isQueuable() && GameEngine.getInstance().isDemo);
    }

    @Override
    public boolean visible(RsiView.Point at) {
        return engine.tileMap.isWorldPointVisibleForTeam(at.x(), at.y(), context.team());
    }

    @Override
    public boolean passable(RsiView.Point at, String movement) {
        UnitMovementType type = movement(movement);
        if (type == UnitMovementType.AIR || type == UnitMovementType.NONE) return true;
        AiMapGraph graph = type == null ? null : AiMapGraph.of(type);
        return graph != null && graph.passable(AiMapGraph.worldToTileX(at.x()), AiMapGraph.worldToTileY(at.y()));
    }

    @Override
    public boolean connected(RsiView.Point from, RsiView.Point to, String movement) {
        UnitMovementType type = movement(movement);
        return type != null && AiMapGraph.sameRegion(from.x(), from.y(), to.x(), to.y(), type);
    }

    @Override
    public boolean canAttack(long actor, long target) {
        OrderableUnit unit = own.get(actor);
        BaseUnit enemy = targets.get(target);
        return unit != null && enemy != null && view.visible.containsKey(target)
                && unit.canAttack() && unit.canAttackUnitType(enemy);
    }

    @Override
    public boolean canCarry(long carrier, long passenger) {
        OrderableUnit ship = own.get(carrier);
        OrderableUnit unit = own.get(passenger);
        return ship != null && unit != null && ship != unit && ship.canTransportUnits() && ship.d(unit, false);
    }

    private static UnitMovementType movement(String name) {
        if (name == null) return null;
        for (UnitMovementType type : UnitMovementType.values()) {
            if (type.name().equals(name)) return type;
        }
        return null;
    }
}
