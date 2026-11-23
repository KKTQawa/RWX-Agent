package com.corrodinggames.rts.game.ai.custom.ai_d;

import com.corrodinggames.rts.game.ai.custom.rsi_sdk.RsiStrategy;
import com.corrodinggames.rts.game.ai.custom.rsi_sdk.RsiView;
import com.corrodinggames.rts.game.ai.custom.rsi_sdk.RsiView.Action;
import com.corrodinggames.rts.game.ai.custom.rsi_sdk.RsiView.Unit;

import java.util.Map;

/**
 * AI RSI-1 — a strategy built on the RSI SDK alone.
 *
 * <p>Four modules, all reading the same {@link Blackboard}:
 * <ul>
 *   <li>{@link BuildPlanner}: what to build and where (income first, then production capacity);</li>
 *   <li>{@link FactoryPlanner}: builders, combat units, upgrades;</li>
 *   <li>{@link ArmyPlanner}: one push group plus a small home guard;</li>
 *   <li>{@link CombatPlanner}: focus fire, attack-move, retreat when hurt.</li>
 * </ul>
 * The SDK default policy stays active for anything this strategy does not address, and every
 * unaddressed builder/factory is explicitly held so the fallback cannot spend the same credits.
 */
public final class AiRsiOne extends RsiStrategy {
    private final Blackboard board = new Blackboard();

    @Override
    protected void configure(Modules modules) {
        modules.economy(new BuildPlanner(board));
        modules.production(new FactoryPlanner(board));
        modules.operations(new ArmyPlanner(board));
        modules.tactics(new CombatPlanner(board));
        modules.tacticsEvery(Tune.TACTICS_TICKS);
    }

    @Override
    protected void onStart(RsiView view, boolean restored) {
        Tune.print();
        board.reset();
        board.observe(view);
        System.out.println("RWX_AIRSI start restored=" + restored + " tick=" + view.tick
                + " credits=" + Math.round(view.credits) + " income=" + view.income
                + " own=" + view.own.size() + " pools=" + view.resourcePools.size()
                + " map=" + Math.round(view.width) + "x" + Math.round(view.height));
        if (Tune.DEBUG) dump(view);
    }

    /** One line per own unit and its actions: the ground truth for tuning the build orders. */
    private void dump(RsiView view) {
        for (Unit unit : view.own.values()) {
            StringBuilder text = new StringBuilder();
            for (Action action : unit.actions()) {
                if (text.length() > 0) text.append(" | ");
                text.append(action.id()).append("->").append(action.product())
                        .append(" c=").append(action.credits())
                        .append(action.ready() ? "" : " (not ready)")
                        .append(action.placement() ? " place" : "")
                        .append(action.queueable() ? " queue" : "")
                        .append(action.targeted() ? " target" : "");
            }
            System.out.println("RWX_AIRSI unit " + unit.type() + "#" + unit.id()
                    + " move=" + unit.movement() + " hp=" + unit.healthFraction()
                    + " building=" + unit.building() + " builder=" + unit.builder()
                    + " armed=" + unit.armed() + " queue=" + unit.queued()
                    + " actions=[" + text + "]");
        }
        System.out.println("RWX_AIRSI pools=" + view.resourcePools.size() + " " + view.resourcePools);
    }

    @Override
    protected Map<String, String> save() {
        return board.save();
    }

    @Override
    protected void load(Map<String, String> state) {
        board.load(state);
    }
}
