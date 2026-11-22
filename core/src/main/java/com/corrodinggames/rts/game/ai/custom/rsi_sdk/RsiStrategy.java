package com.corrodinggames.rts.game.ai.custom.rsi_sdk;

import java.util.List;
import java.util.Map;
import java.util.Objects;

/** One instance per team. Only the host invokes policy callbacks and executes their decisions. */
public abstract class RsiStrategy {
    protected void configure(Modules modules) { }
    protected void onStart(RsiView view, boolean restored) { }
    protected Map<String, String> save() { return Map.of(); }
    protected void load(Map<String, String> state) { }

    public static final class Modules {
        Economy economy = new Economy() { };
        Production production = new Production() { };
        Operations operations = new Operations() { };
        Tactics tactics = new Tactics() { };
        Logistics logistics = new Logistics() { };
        int tacticalTicks;

        Modules() { }

        public void economy(Economy value) { economy = Objects.requireNonNull(value); }
        public void production(Production value) { production = Objects.requireNonNull(value); }
        public void operations(Operations value) { operations = Objects.requireNonNull(value); }
        public void tactics(Tactics value) { tactics = Objects.requireNonNull(value); }
        public void logistics(Logistics value) { logistics = Objects.requireNonNull(value); }
        /** Opt into faster decisions without changing the engine's weapon or pathing updates. */
        public void tacticsEvery(int ticks) {
            if (ticks < 5 || ticks > 600) throw new IllegalArgumentException("Tactical cadence must be 5–600 ticks");
            tacticalTicks = ticks;
        }
    }

    public abstract static class Economy {
        /** Propose construction, builder work and a resource allowance for production. */
        protected RsiDecision.Economy plan(RsiView view) { return RsiDecision.Economy.delegate(); }
    }

    public abstract static class Production {
        /** Produce, upgrade, adjust queues and place rally points at participating factories. */
        protected RsiDecision plan(RsiView view, double availableCredits) { return RsiDecision.delegate(); }
    }

    public abstract static class Operations {
        /** Null delegates. Custom squads claim their members; omitted troops use default squads. */
        protected List<RsiView.Squad> plan(RsiView view) { return null; }
    }

    public abstract static class Tactics {
        /** Unmentioned members can receive default tactical orders. */
        protected RsiDecision direct(RsiView view, RsiView.Squad squad) { return RsiDecision.delegate(); }
    }

    public abstract static class Logistics {
        /** Null retains outstanding missions. A list replaces the desired missions. */
        protected List<RsiView.Transport> plan(RsiView view, List<RsiView.Squad> squads,
                                               List<RsiView.Transport> active) { return null; }

        /** Proposals override default transport orders for the units they actually address. */
        protected RsiDecision direct(RsiView view, RsiView.Transport mission) {
            return RsiDecision.delegate();
        }
    }
}
