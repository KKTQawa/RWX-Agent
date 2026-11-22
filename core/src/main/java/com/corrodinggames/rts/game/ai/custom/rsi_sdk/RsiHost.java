package com.corrodinggames.rts.game.ai.custom.rsi_sdk;

import com.corrodinggames.rts.game.ai.custom.ai_rsi.ExperimentAi;
import com.corrodinggames.rts.game.ai.strategy.AiContext;
import com.corrodinggames.rts.game.ai.strategy.AiDefinition;
import com.corrodinggames.rts.game.ai.strategy.AiStrategy;
import com.corrodinggames.rts.game.units.UnitType;

import static com.corrodinggames.rts.game.ai.custom.rsi_sdk.RsiOrders.Scope;
import static com.corrodinggames.rts.game.ai.custom.rsi_sdk.RsiView.*;

import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.IOException;
import java.util.*;

/** The experimental AI uses the existing scheduler and a fog-safe default policy. */
public final class RsiHost implements AiStrategy {
    private final RsiStrategy strategy = new ExperimentAi();
    private final RsiStrategy.Modules modules = new RsiStrategy.Modules();
    private final Map<String, UnitType> types = new HashMap<>();
    private final Map<Long, Contact> memory = new TreeMap<>();
    private final RsiOrders orders = new RsiOrders();
    private final Map<Long, Delivery> deliveries = new TreeMap<>();
    private List<Squad> plan;
    private List<Point> resourcePools;
    private RsiWorld world;
    private int lastTactics = Integer.MIN_VALUE;

    private RsiHost() { strategy.configure(modules); }

    public static AiDefinition definition() {
        return AiDefinition.custom(21, "rwx.ai-rsi", "AI RSI", "AI RSI", RsiHost::new);
    }

    @Override public String id() { return "rwx.ai-rsi.v1"; }

    @Override
    public void onStart(AiContext context, boolean restored) {
        for (UnitType type : context.unitTypes()) types.put(type.v(), type);
        resourcePools = RsiWorld.resourcePools();
        strategy.onStart(world(context).view, restored);
        onStrategy(context, 0);
    }

    @Override
    public void onFrame(AiContext context, float deltaFrames) {
        if (modules.tacticalTicks > 0 && (lastTactics == Integer.MIN_VALUE
                || context.tick() - lastTactics >= modules.tacticalTicks)) {
            onTactics(context, deltaFrames);
        }
    }

    @Override
    public void onEconomy(AiContext context, float elapsedFrames) {
        RsiWorld current = world(context);
        RsiView view = current.view;
        Set<Long> transport = participants();
        Set<Long> builders = new TreeSet<>();
        Set<Long> producers = new TreeSet<>();
        for (Unit u : view.own.values()) {
            if (transport.contains(u.id())) continue;
            if (u.builder() && u.mobile()) builders.add(u.id());
            if (u.queued() >= 0 || u.building()) producers.add(u.id());
        }
        RsiDecision.Economy budget = modules.economy.plan(view);
        if (budget == null) budget = RsiDecision.Economy.delegate();
        double reserve = nonnegative(budget.reserveCredits());
        double economyFloor = reserve + nonnegative(budget.productionCredits());
        orders.apply(current, budget.work(), builders, Scope.ECONOMY, economyFloor);
        orders.apply(current, RsiDefaults.economy(current), builders, Scope.ECONOMY, economyFloor);
        orders.apply(current, modules.production.plan(view, Math.max(0, orders.credits() - reserve)),
                producers, Scope.PRODUCTION, reserve);
        orders.apply(current, RsiDefaults.production(current), producers, Scope.PRODUCTION, reserve);
    }

    @Override
    public void onStrategy(AiContext context, float elapsedFrames) {
        List<Squad> proposed = modules.operations.plan(world(context).view);
        plan = proposed == null ? null : List.copyOf(proposed);
    }

    @Override
    public void onTactics(AiContext context, float elapsedFrames) {
        if (lastTactics == context.tick() || modules.tacticalTicks > 0 && lastTactics != Integer.MIN_VALUE
                && context.tick() - lastTactics < modules.tacticalTicks) return;
        lastTactics = context.tick();
        RsiWorld current = world(context);
        RsiView view = current.view;
        updateDeliveries(view, squads(view, Set.of()));
        Set<Long> reserved = participants();
        for (Delivery delivery : deliveries.values()) {
            Transport mission = delivery.mission;
            Set<Long> allowed = delivery.participants();
            if (!delivery.cancelled && view.tick < mission.untilTick()) {
                orders.apply(current, modules.logistics.direct(view, mission), allowed, Scope.LOGISTICS, 0);
            }
            orders.apply(current, RsiDefaults.transport(view, mission, delivery.delivered,
                    delivery.cancelled || view.tick >= mission.untilTick()), allowed, Scope.LOGISTICS, 0);
        }
        for (Squad squad : squads(view, reserved)) {
            orders.apply(current, modules.tactics.direct(view, squad), squad.units(), Scope.TACTICS, 0);
            orders.apply(current, RsiDefaults.tactics(view, squad), squad.units(), Scope.TACTICS, 0);
        }
    }

    private List<Squad> squads(RsiView view, Set<Long> reserved) {
        List<Squad> result = new ArrayList<>();
        Set<Long> used = new HashSet<>(reserved);
        if (plan != null) {
            for (Squad squad : plan) {
                List<Long> valid = new ArrayList<>();
                for (long id : squad.units()) {
                    Unit unit = view.own.get(id);
                    if (unit != null && unit.complete() && unit.carrier() < 0 && used.add(id)) valid.add(id);
                }
                if (!valid.isEmpty()) result.add(new Squad(squad.id(), valid,
                        view.contains(squad.goal()) ? squad.goal() : null));
            }
        }
        result.addAll(RsiDefaults.squads(view, used));
        return List.copyOf(result);
    }

    private void updateDeliveries(RsiView view, List<Squad> squads) {
        deliveries.values().removeIf(delivery -> delivery.finished(view));
        List<Transport> proposed = modules.logistics.plan(view, squads,
                deliveries.values().stream().map(delivery -> delivery.mission).toList());
        if (proposed == null) return;
        Set<Long> retained = new HashSet<>();
        Set<Long> used = participants();
        for (Transport mission : proposed) {
            Delivery current = deliveries.get(mission.carrier());
            if (current != null) {
                retained.add(mission.carrier());
                if (current.mission.passengers().equals(mission.passengers()) && validMission(view, mission)) {
                    current.mission = mission;
                }
            } else if (validMission(view, mission) && !used.contains(mission.carrier())
                    && mission.passengers().stream().noneMatch(used::contains)) {
                Delivery delivery = new Delivery(mission);
                deliveries.put(mission.carrier(), delivery);
                used.addAll(delivery.participants());
                retained.add(mission.carrier());
            }
        }
        // A cancellation with passengers aboard becomes a normal unload at the existing dropoff.
        deliveries.values().removeIf(delivery -> {
            if (retained.contains(delivery.mission.carrier())) return false;
            delivery.cancelled = true;
            return !delivery.hasPassengersAboard(view);
        });
    }

    private static boolean validMission(RsiView view, Transport mission) {
        Unit carrier = view.own.get(mission.carrier());
        return carrier != null && carrier.transport() && carrier.complete()
                && mission.untilTick() > view.tick && view.contains(mission.pickup())
                && view.contains(mission.dropoff()) && !mission.passengers().isEmpty()
                && mission.passengers().stream().allMatch(id -> id != mission.carrier() && view.own.containsKey(id));
    }

    private Set<Long> participants() {
        Set<Long> result = new HashSet<>();
        for (Delivery delivery : deliveries.values()) result.addAll(delivery.participants());
        return result;
    }

    private RsiWorld world(AiContext context) {
        if (world == null || world.view.tick != context.tick()) {
            world = new RsiWorld(context, memory, types, resourcePools);
        }
        orders.begin(world.view);
        return world;
    }

    private static double nonnegative(double value) {
        return Double.isFinite(value) ? Math.max(0, value) : 0;
    }

    @Override
    public void writeState(DataOutputStream out) throws IOException {
        Map<String, String> state = new TreeMap<>(strategy.save());
        if (state.size() > 128) throw new IOException("RSI strategy state exceeds 128 entries");
        out.writeInt(state.size());
        for (var entry : state.entrySet()) {
            out.writeUTF(entry.getKey());
            out.writeUTF(entry.getValue());
        }
    }

    @Override
    public void readState(DataInputStream in) throws IOException {
        int count = in.readInt();
        if (count < 0 || count > 128) throw new IOException("Invalid RSI strategy state");
        Map<String, String> state = new LinkedHashMap<>();
        for (int i = 0; i < count; i++) state.put(in.readUTF(), in.readUTF());
        strategy.load(Collections.unmodifiableMap(state));
    }

    private static final class Delivery {
        Transport mission;
        final Set<Long> embarked = new HashSet<>();
        final Set<Long> delivered = new HashSet<>();
        boolean cancelled;

        Delivery(Transport mission) { this.mission = mission; }

        boolean finished(RsiView view) {
            Unit carrier = view.own.get(mission.carrier());
            if (carrier == null) return true;
            for (long id : mission.passengers()) {
                Unit unit = view.own.get(id);
                if (unit == null || embarked.contains(id) && unit.carrier() < 0) delivered.add(id);
                else if (unit.carrier() == carrier.id()) embarked.add(id);
            }
            return delivered.containsAll(mission.passengers())
                    || (cancelled || view.tick >= mission.untilTick()) && !hasPassengersAboard(view);
        }

        boolean hasPassengersAboard(RsiView view) {
            return mission.passengers().stream().map(view.own::get)
                    .anyMatch(unit -> unit != null && unit.carrier() == mission.carrier());
        }

        Set<Long> participants() {
            Set<Long> result = new HashSet<>(mission.passengers());
            result.removeAll(delivered);
            result.add(mission.carrier());
            return result;
        }
    }
}
