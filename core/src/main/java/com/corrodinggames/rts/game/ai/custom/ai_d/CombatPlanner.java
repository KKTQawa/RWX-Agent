package com.corrodinggames.rts.game.ai.custom.ai_d;

import com.corrodinggames.rts.game.ai.custom.rsi_sdk.RsiDecision;
import com.corrodinggames.rts.game.ai.custom.rsi_sdk.RsiStrategy;
import com.corrodinggames.rts.game.ai.custom.rsi_sdk.RsiView;
import com.corrodinggames.rts.game.ai.custom.rsi_sdk.RsiView.Contact;
import com.corrodinggames.rts.game.ai.custom.rsi_sdk.RsiView.Point;
import com.corrodinggames.rts.game.ai.custom.rsi_sdk.RsiView.Squad;
import com.corrodinggames.rts.game.ai.custom.rsi_sdk.RsiView.Unit;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

import static com.corrodinggames.rts.game.ai.custom.rsi_sdk.RsiDecision.Kind;
import static com.corrodinggames.rts.game.ai.custom.rsi_sdk.RsiDecision.Order;

/**
 * Per-unit orders inside a squad: shoot what is worth shooting, walk to the squad goal, back out of
 * a fight the squad cannot win.
 *
 * <p>Two disciplines keep the army alive against a bigger economy:
 * <ul>
 *   <li>the squad only closes in when its own power beats the hostile power around it
 *       ({@link Tune#ENGAGE_EDGE}); otherwise it falls back, because trading units at 3.7x their
 *       production is the one way to definitely lose;</li>
 *   <li>targets are ranked by "wounded, valuable, alone", not by distance — shooting the tank in
 *       the middle of their formation means standing in front of a hundred barrels to do it.</li>
 * </ul>
 *
 * <p>Only idle units are re-tasked. A unit that already has a waypoint is executing an attack or a
 * move the engine is still resolving; overwriting it every decision tick would reset its target
 * and cost real damage.
 */
final class CombatPlanner extends RsiStrategy.Tactics {
    private final Blackboard board;

    CombatPlanner(Blackboard board) {
        this.board = board;
    }

    @Override
    protected RsiDecision direct(RsiView view, Squad squad) {
        List<Unit> members = new ArrayList<>(squad.units().size());
        for (long id : squad.units()) {
            Unit unit = view.own.get(id);
            if (unit != null && unit.complete() && unit.carrier() < 0) members.add(unit);
        }
        if (members.isEmpty()) return RsiDecision.delegate();

        Point goal = squad.goal();
        Point centre = centroid(members);
        double mine = power(members);
        double theirs = board.threatAt(view, centre, Tune.ENGAGE_RADIUS * 1.4);
        boolean kite = kite(view, squad, centre, mine, theirs);
        Point retreat = kite ? retreat(view, centre) : null;
        Contact focus = kite ? null : focus(view, members, centre, mine);

        List<Order> orders = new ArrayList<>();
        Set<Long> hold = new HashSet<>();
        List<Long> stance = new ArrayList<>();

        for (long id : squad.units()) {
            Unit unit = view.own.get(id);
            if (unit == null || !unit.complete() || unit.carrier() >= 0) continue;

            if (board.retreating.contains(id)) {
                if (unit.healthFraction() >= Tune.REGROUP_HP) {
                    board.retreating.remove(id);
                } else {
                    if (unit.idle() && board.base != null
                            && unit.at().distanceSquared(board.base) > 900) {
                        orders.add(Order.at(Kind.MOVE, List.of(id), board.base));
                    }
                    continue;
                }
            } else if (unit.healthFraction() < Tune.RETREAT_HP && board.base != null
                    && unit.at().distanceSquared(board.base) > 40_000) {
                board.retreating.add(id);
                orders.add(Order.at(Kind.MOVE, List.of(id), board.base));
                continue;
            }

            stance.add(id);

            if (kite) {
                // Fall back only what is not already walking: re-issuing a move every decision tick
                // would reset the path and turn the retreat into a shuffle.
                if (retreat != null && !moving(unit)) {
                    orders.add(Order.at(Kind.MOVE, List.of(id), retreat));
                }
                continue;
            }

            Contact target = bestTarget(view, unit, focus, mine);
            if (target != null) {
                // A unit that is already shooting keeps its target: the engine resolves the fight
                // and re-acquires when the victim dies.
                if (unit.idle()) orders.add(Order.target(Kind.ATTACK, List.of(id), target.id()));
                continue;
            }
            // A move that makes no progress for a long time is jammed: clear it so the next
            // decision tick can issue a fresh path instead of standing still forever.
            String waypoint = Knowledge.lower(unit.waypoint());
            boolean walking = waypoint.equals("move") || waypoint.equals("attackmove")
                    || waypoint.equals("patrol");
            if (!unit.idle() && walking && board.stuck(id, unit, view.tick)) {
                orders.add(Order.at(Kind.STOP, List.of(id), null));
                board.reportJam(goal, unit.at());
                board.forget(id);
                continue;
            }
            if (!unit.idle() || goal == null) continue;
            if (unit.at().distanceSquared(goal) <= Tune.ARRIVE_DISTANCE * Tune.ARRIVE_DISTANCE) continue;
            if (!view.canReach(unit, goal)) {
                hold.add(id);
                continue;
            }
            orders.add(Order.attackMove(List.of(id), goal, 300));
        }

        // Stance is a separate command channel. Chasing is what turns a push into a base assault:
        // with "only in range" a unit parked at the goal never acquires the command center that
        // sits a few hundred units further in. While backing out, "only in range" keeps the squad
        // from being dragged forward by a stray shot.
        if (!stance.isEmpty()) {
            orders.add(Order.stance(stance, kite ? RsiDecision.Stance.IN_RANGE
                    : RsiDecision.Stance.CHASE));
        }
        return new RsiDecision(orders, hold);
    }

    /**
     * True when the squad should break contact instead of engaging.
     *
     * <p>Latched: once a retreat starts it runs for {@link Tune#KITE_TICKS} and only ends when the
     * local balance actually improves, so the squad does not oscillate at the boundary. A squad
     * already at home never falls back — that is what the turrets and the repair buildings are for.
     */
    private boolean kite(RsiView view, Squad squad, Point centre, double mine, double theirs) {
        if (!Tune.KITE || theirs <= 0) return false;
        if (squad.id().equals("home") || squad.id().equals("raid")) return false;
        // A two-unit group has nothing to save: it is already the cheapest thing on the field, and
        // a group that keeps backing off is not the nuisance it was sent out to be.
        if (mine < Tune.KITE_MIN_POWER) return false;
        if (board.base != null && centre.distanceSquared(board.base) < 900 * 900) return false;
        if (view.tick < board.kiteUntil(squad.id())) return theirs > mine * Tune.KITE_RELEASE;
        if (theirs < mine * Tune.KITE_RATIO) return false;
        board.kiteFor(squad.id(), view.tick + Tune.KITE_TICKS);
        board.log(view, "kite " + squad.id() + " mine=" + Math.round(mine)
                + " theirs=" + Math.round(theirs));
        return true;
    }

    /** Walk away from the hostile mass, or home when home is behind us anyway. */
    private Point retreat(RsiView view, Point centre) {
        Point home = board.base;
        Point enemy = enemyCentre(view, centre, Tune.ENGAGE_RADIUS * 1.4);
        if (enemy == null) return home;
        double dx = centre.x() - enemy.x();
        double dy = centre.y() - enemy.y();
        double length = Math.hypot(dx, dy);
        if (length < 1) return home;
        double step = 500;
        Point away = new Point(centre.x() + (float) (dx / length * step),
                centre.y() + (float) (dy / length * step));
        if (home != null) {
            double hx = home.x() - centre.x();
            double hy = home.y() - centre.y();
            if (hx * hx + hy * hy > 1 && (hx * dx + hy * dy) / (Math.sqrt(hx * hx + hy * hy) * length) > 0.2) {
                return home;
            }
        }
        return view.contains(away) ? away : home;
    }

    private static Point enemyCentre(RsiView view, Point at, double radius) {
        double limit = radius * radius;
        double x = 0;
        double y = 0;
        double weight = 0;
        for (Contact contact : view.visible.values()) {
            if (contact.building()) continue;
            if (contact.at().distanceSquared(at) > limit) continue;
            double w = Math.max(0.1, Knowledge.power(contact.type()));
            x += contact.at().x() * w;
            y += contact.at().y() * w;
            weight += w;
        }
        return weight <= 0 ? null : new Point((float) (x / weight), (float) (y / weight));
    }

    /**
     * One target for the whole squad: the most valuable, most wounded, least supported hostile
     * unit nearby. Concentrated fire kills faster than spreading damage, and it is the only way a
     * smaller army wins an exchange at all.
     */
    private Contact focus(RsiView view, List<Unit> members, Point centre, double mine) {
        if (!Tune.FOCUS_FIRE || !board.attrition) return null;
        double limit = Tune.ENGAGE_RADIUS * 2.0;
        limit *= limit;
        Contact best = null;
        double bestScore = 0;
        for (Contact contact : view.visible.values()) {
            if (contact.building()) continue;
            if (centre.distanceSquared(contact.at()) > limit) continue;
            double value = Math.max(0.2, Knowledge.power(contact.type()) / 1000.0);
            double isolation = 1 / (1 + board.threatAt(view, contact.at(), 320) / Math.max(300, mine));
            double score = value * (1.4 - contact.healthFraction()) * isolation;
            if (score > bestScore) {
                bestScore = score;
                best = contact;
            }
        }
        return best;
    }

    /**
     * What this unit should shoot right now. In doctrine 1 the enemy army comes first: a unit only
     * goes after the command center when their garrison there is thin enough that the army can
     * actually survive the walk in. Buildings still compete — a factory or an extractor is worth
     * the detour — but a turret cluster is not.
     */
    private Contact bestTarget(RsiView view, Unit unit, Contact focus, double mine) {
        if (focus != null && view.canAttack(unit.id(), focus.id())
                && unit.at().distanceSquared(focus.at()) <= 900 * 900) {
            return focus;
        }
        // The win condition still ends the game, so it is not ignored — it is gated on their
        // garrison. Doctrine 0 keeps the old unconditional priority so both can be measured.
        float ccReach = Tune.COMMAND_CENTER_PRIORITY;
        double ccReachSquared = (double) ccReach * ccReach;
        for (Contact contact : view.visible.values()) {
            if (!Knowledge.isCommandCenter(contact.type())) continue;
            if (unit.at().distanceSquared(contact.at()) > ccReachSquared) continue;
            if (!view.canAttack(unit.id(), contact.id())) continue;
            if (board.attrition && Tune.DOCTRINE != 0
                    && board.threatAt(view, contact.at(), 800) > mine * Tune.CC_GARRISON) continue;
            return contact;
        }
        // An ATTACK order makes the engine walk the unit into range, so the acquisition radius is
        // deliberately larger than the weapon range.
        float range = Math.max(Tune.ENGAGE_RADIUS, unit.range() * (float) Tune.ENGAGE_MARGIN);
        double rangeSquared = (double) range * range;
        Contact best = null;
        double bestScore = Double.MAX_VALUE;
        for (Contact contact : view.visible.values()) {
            if (!view.canAttack(unit.id(), contact.id())) continue;
            double distance = unit.at().distanceSquared(contact.at());
            if (distance > rangeSquared) continue;
            double score;
            if (board.attrition) {
                double value = Math.min(2.0, Knowledge.power(contact.type()) / 1000.0);
                // Wounded first, then value, then proximity. Clusters are penalised: shooting into a
                // formation is how a small army loses its tanks one by one.
                score = contact.healthFraction() + 0.55 * distance / rangeSquared - 0.45 * value
                        + Tune.ISOLATION * board.threatAt(view, contact.at(), 320)
                        / Math.max(300, mine);
                if (contact.building()) {
                    score += 0.9 - 0.45 * Knowledge.priorityOf(contact.type());
                    // The current campaign objective outranks everything the unit can see.
                    if (board.campaignPoint != null
                            && contact.at().distanceSquared(board.campaignPoint) < 300 * 300) {
                        score -= 1.2;
                    }
                }
            } else {
                // 兵力不吃亏时的老打分：最近的、血最少的先打，建筑往后放。
                score = contact.healthFraction();
                if (Knowledge.isCommandCenter(contact.type())) score -= 1.5;
                if (contact.building()) score += 0.35;
                score += distance / rangeSquared * 0.5;
            }
            if (score < bestScore) {
                bestScore = score;
                best = contact;
            }
        }
        return best;
    }

    private static boolean moving(Unit unit) {
        String waypoint = Knowledge.lower(unit.waypoint());
        return waypoint.equals("move") || waypoint.equals("attackmove") || waypoint.equals("patrol");
    }

    private static Point centroid(List<Unit> units) {
        double x = 0;
        double y = 0;
        for (Unit unit : units) {
            x += unit.at().x();
            y += unit.at().y();
        }
        return new Point((float) (x / units.size()), (float) (y / units.size()));
    }

    /** Absolute strength of the squad in "credits worth of c_tank", the same scale the enemy uses. */
    private static double power(List<Unit> units) {
        double power = 0;
        for (Unit unit : units) power += Knowledge.power(unit.type());
        return power;
    }
}
