package com.corrodinggames.rts.game.ai.custom.ai_d;

import com.corrodinggames.rts.game.ai.custom.rsi_sdk.RsiView;
import com.corrodinggames.rts.game.ai.custom.rsi_sdk.RsiView.Contact;
import com.corrodinggames.rts.game.ai.custom.rsi_sdk.RsiView.Point;
import com.corrodinggames.rts.game.ai.custom.rsi_sdk.RsiView.Unit;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * State shared by the four modules. The host calls the modules in a fixed order every decision
 * tick (economy, production, operations, tactics), so a value written by one module is visible to
 * the next one in the same tick.
 */
final class Blackboard {
    /** Own command center (or the healthiest remaining building). */
    Point base;
    /** Where the army should push this cycle. */
    Point goal;
    /** True when the enemy base sits in another land region, so only hover/air can get there. */
    boolean waterSeparated;
    /** The enemy has shown aircraft, so ground-only units need anti-air cover. */
    boolean enemyAir;
    /** The push has stalled next to the enemy base: units keep jamming on the way in. */
    boolean offensiveBlocked;
    private int blockedUntil;
    private int jamSignals;
    /** Credits still missing for an upgrade the army is waiting on; 0 when nothing is pending. */
    double savingFor;
    /** Latched defensive posture so the army does not oscillate between attacking and defending. */
    boolean defending;
    /** A push wave is on the way; only its members keep attacking, new units gather again. */
    boolean waveActive;
    int waveSize;
    final Set<Long> waveUnits = new HashSet<>();
    /** Where fresh units wait for the next wave; also used as the factory rally point. */
    Point staging;
    int lastRally = -100_000;
    /** The economy is currently banking for a siege strike, so production only trickles. */
    boolean savingStrike;
    /**
     * Credits accumulated for the next investment. Production may not spend below it, and the
     * floor releases itself as soon as the target purchase is affordable — otherwise the bank
     * would sit exactly at the floor and never afford anything.
     */
    double investPot;
    int potTick = -100_000;

    /** True when their army outclasses ours: the war of attrition is on (写 by {@link ArmyPlanner}). */
    boolean attrition;
    /** Doctrine 1: the building the army dismantles next. Economy and production before the center. */
    Point campaignPoint;
    long campaignId = -1;
    int campaignTick = -100_000;
    /** Spots where a remembered building turned out to be gone, so it is not targeted again. */
    private final Map<String, Integer> cleared = new HashMap<>();
    /** Per-squad tick until which the squad keeps backing out of a fight it cannot win. */
    private final Map<String, Integer> kiteUntil = new HashMap<>();

    /** Combat units currently alive; production keeps a floor of them before saving for upgrades. */
    int armyCount(RsiView view) {
        int count = 0;
        for (Unit unit : view.own.values()) {
            if (Knowledge.isCombatUnit(unit) && unit.carrier() < 0) count++;
        }
        return count;
    }
    /** A resource pool is still unclaimed, so income buildings come before more army. */
    boolean wantIncome;
    /** Last observed position per unit, used to notice a move order that is not making progress. */
    private final Map<Long, float[]> lastSeenAt = new HashMap<>();
    private final Map<Long, Integer> lastMovedTick = new HashMap<>();
    /** Enemy command center position, once seen. */
    Point enemyBase;
    /** Command centers already destroyed; their contact memory outlives them. */
    private final Set<Long> lostBases = new HashSet<>();
    int planTick = -100_000;
    int lastLogTick = -100_000;
    int lastDumpTick = -100_000;
    int lastInvestLog = -100_000;
    /** Units currently walking home to heal; they are not re-tasked until they recover. */
    final Set<Long> retreating = new HashSet<>();
    float range(String type) {
        Float known = rangeOf.get(Knowledge.lower(type));
        return known != null ? known : Knowledge.rangeGuess(type);
    }

    /** Last known price per produced type, learned from factory actions. */
    final Map<String, Integer> price = new HashMap<>();
    /** Weapon range per unit type, learned from our own units (the table fills the gaps). */
    final Map<String, Float> rangeOf = new HashMap<>();
    /** Siege posture: the enemy base is known, so long-range units are the ones that can hit it. */
    boolean siegeMode;
    /** Movement type per unit type, learned by looking at our own units. */
    final Map<String, String> movementOf = new HashMap<>();
    /** Whether a unit type carries a weapon, learned from our own units. */
    final Map<String, Boolean> armedOf = new HashMap<>();
    /** Building types ordered but not yet on the map, with the tick they were ordered at. */
    private final Map<String, Integer> orderedType = new HashMap<>();
    private final Map<String, Integer> orderedTick = new HashMap<>();
    /** Point -> tick a placement was rejected on; receipts turn "try and fail" into "remember". */
    private final Map<String, Integer> badSpots = new HashMap<>();

    void markBad(Point at) {
        if (at == null) return;
        badSpots.put(spotKey(at), tick + Tune.BAD_SPOT_TICKS);
    }

    /**
     * A campaign target we walked up to and did not find: remember it so the army does not keep
     * marching at a hole in the ground that the contact memory has not dropped yet.
     */
    void clearSpot(Point at) {
        if (at != null) cleared.put(spotKey(at), tick + Tune.BAD_SPOT_TICKS);
    }

    boolean clearedSpot(Point at) {
        if (at == null) return true;
        Integer until = cleared.get(spotKey(at));
        return until != null && tick < until;
    }

    int kiteUntil(String squad) {
        return kiteUntil.getOrDefault(squad, -100_000);
    }

    void kiteFor(String squad, int until) {
        kiteUntil.put(squad, until);
    }

    boolean bad(Point at) {
        if (at == null) return true;
        Integer until = badSpots.get(spotKey(at));
        return until != null && tick < until;
    }

    private static String spotKey(Point at) {
        return Math.round(at.x() / 20f) + "," + Math.round(at.y() / 20f);
    }

    /** type@point -> tick of the last build order, so a rejected placement is not retried forever. */
    private final Map<String, Integer> orderedAt = new HashMap<>();
    private int tick;
    /** Diagnostics counters. */
    final Map<String, Integer> built = new LinkedHashMap<>();

    void observe(RsiView view) {
        tick = view.tick;
        Unit home = Knowledge.base(view);
        if (home != null) base = home.at();
        for (Unit unit : view.own.values()) {
            if (unit.mobile()) {
                movementOf.putIfAbsent(Knowledge.lower(unit.type()), unit.movement());
                if (unit.range() > 0) rangeOf.putIfAbsent(Knowledge.lower(unit.type()), unit.range());
                armedOf.putIfAbsent(Knowledge.lower(unit.type()), unit.armed());
            }
            for (RsiView.Action action : unit.actions()) {
                String product = action.product();
                if (product != null && !action.placement() && action.credits() > 0) {
                    price.putIfAbsent(Knowledge.lower(product), action.credits());
                }
            }
        }
        if (base == null) base = new Point(view.width / 2, view.height / 2);
        enemyAir = false;
        for (Contact contact : view.lastSeen.values()) {
            if (contact.airborne()) {
                enemyAir = true;
                break;
            }
        }
    }

    void reset() {
        base = null;
        goal = null;
        enemyBase = null;
        campaignPoint = null;
        campaignId = -1;
        campaignTick = -100_000;
        cleared.clear();
        kiteUntil.clear();
        lostBases.clear();
        badSpots.clear();
        defending = false;
        savingStrike = false;
        waveActive = false;
        waveUnits.clear();
        staging = null;
        investPot = 0;
        potTick = -100_000;
        waterSeparated = false;
        retreating.clear();
        built.clear();
        price.clear();
    }

    Map<String, String> save() {
        Map<String, String> state = new LinkedHashMap<>();
        if (goal != null) state.put("goal", goal.x() + "," + goal.y());
        if (enemyBase != null) state.put("enemyBase", enemyBase.x() + "," + enemyBase.y());
        if (!built.isEmpty()) {
            StringBuilder text = new StringBuilder();
            for (Map.Entry<String, Integer> entry : built.entrySet()) {
                if (text.length() > 0) text.append(';');
                text.append(entry.getKey()).append('=').append(entry.getValue());
            }
            state.put("built", text.toString());
        }
        return state;
    }

    void load(Map<String, String> state) {
        goal = parse(state.get("goal"));
        enemyBase = parse(state.get("enemyBase"));
        built.clear();
        String text = state.get("built");
        if (text == null) return;
        for (String item : text.split(";")) {
            int at = item.indexOf('=');
            if (at <= 0) continue;
            try {
                built.put(item.substring(0, at), Integer.parseInt(item.substring(at + 1)));
            } catch (NumberFormatException ignored) {
                // A corrupt counter is not worth failing a save over.
            }
        }
    }

    private static Point parse(String text) {
        if (text == null) return null;
        int comma = text.indexOf(',');
        if (comma <= 0) return null;
        try {
            return new Point(Float.parseFloat(text.substring(0, comma)),
                    Float.parseFloat(text.substring(comma + 1)));
        } catch (NumberFormatException ignored) {
            return null;
        }
    }

    void record(String type) {
        built.merge(Knowledge.lower(type), 1, Integer::sum);
    }

    /** Remember a building order so the same ladder step is not bought twice in a row. */
    void planned(String type, Point at) {
        String key = Knowledge.lower(type);
        orderedType.merge(key, 1, Integer::sum);
        orderedTick.put(key, tick);
        if (at != null) orderedAt.put(key + "@" + Math.round(at.x()) + "," + Math.round(at.y()), tick);
    }

    /**
     * True when this exact building was already ordered at this exact spot recently. Placement is
     * validated by the engine, so a rejected order is silent: without this the builder would keep
     * re-issuing the same impossible foundation instead of trying the next candidate.
     */
    boolean repeat(String type, Point at) {
        if (at == null) return false;
        String key = Knowledge.lower(type) + "@" + Math.round(at.x()) + "," + Math.round(at.y());
        Integer at1 = orderedAt.get(key);
        if (at1 == null) return false;
        if (tick - at1 > 600) {
            orderedAt.remove(key);
            return false;
        }
        return true;
    }

    /** Candidate building spots around {@code center}, nearest ring first. */
    List<Point> spots(RsiView view, Point center, float minRadius, float maxRadius,
                      String movement, double spacing) {
        List<Point> result = new ArrayList<>();
        for (int ring = 0; ring < 4; ring++) {
            float radius = minRadius + (maxRadius - minRadius) * ring / 3f;
            for (int i = 0; i < 16; i++) {
                double angle = Math.PI * 2 * i / 16 + ring * 0.19634954084936207;
                Point at = new Point(center.x() + (float) Math.cos(angle) * radius,
                        center.y() + (float) Math.sin(angle) * radius);
                if (!view.passable(at, movement)) continue;
                if (!clear(view, at, spacing)) continue;
                result.add(at);
            }
        }
        return result;
    }

    /**
     * Orders issued recently that have not produced a building yet. The window is generous on
     * purpose: a builder may have to walk across the base before the foundation exists.
     */
    int pending(java.util.function.Predicate<String> kind) {
        int count = 0;
        for (var entry : orderedType.entrySet()) {
            if (!kind.test(entry.getKey())) continue;
            if (tick - orderedTick.getOrDefault(entry.getKey(), tick) > 420) continue;
            count += entry.getValue();
        }
        return count;
    }

    /**
     * True when a unit has been trying to move for a long time without changing position: it is
     * jammed against terrain or in a crowd, and the engine will not re-path on its own.
     */
    boolean stuck(long id, RsiView.Unit unit, int now) {
        float[] last = lastSeenAt.get(id);
        if (last == null) {
            lastSeenAt.put(id, new float[]{unit.at().x(), unit.at().y()});
            lastMovedTick.put(id, now);
            return false;
        }
        double dx = last[0] - unit.at().x();
        double dy = last[1] - unit.at().y();
        if (dx * dx + dy * dy > 900) {
            last[0] = unit.at().x();
            last[1] = unit.at().y();
            lastMovedTick.put(id, now);
            return false;
        }
        Integer since = lastMovedTick.get(id);
        return since != null && now - since > Tune.STUCK_TICKS;
    }

    /**
     * A unit that had to be unstuck close to the push goal is a signal that the approach is
     * impassable for its movement type (a destroyed bridge, a cliff shelf, a walled-in base).
     */
    void reportJam(Point goal, Point at) {
        if (goal == null || at == null) return;
        if (at.distanceSquared(goal) > 800 * 800) return;
        jamSignals++;
    }

    void updateOffence(int now) {
        if (jamSignals > 5) {
            jamSignals = 0;
            if (!offensiveBlocked) {
                offensiveBlocked = true;
                blockedUntil = now + 5400;
            }
        }
        if (offensiveBlocked && now > blockedUntil) offensiveBlocked = false;
    }

    void forget(long id) {
        lastSeenAt.remove(id);
        lastMovedTick.remove(id);
    }

    /** False only when a unit of this type has been seen and it carries no weapon. */
    Boolean armed(String type) {
        return armedOf.get(Knowledge.lower(type));
    }

    /** Movement type of a produced unit: learned from our own units, else guessed from its name. */
    String movement(String type) {
        String learned = movementOf.get(Knowledge.lower(type));
        return learned != null ? learned : Knowledge.movementGuess(type);
    }

    // ---------------------------------------------------------------- enemy picture

    /**
     * Where to attack. The win condition is the enemy command center, so that is the only real
     * target: once it has been seen the position is remembered, and until then the symmetric map
     * assumption (opponent sits across the map center from us) gives the army somewhere useful to
     * march instead of standing at home.
     */
    /**
     * Influence map, cheap form: total hostile combat power inside a radius of a point. Enemy units
     * are only known within our vision, so this is a lower bound — exactly what a defending force
     * should react to, and never a reason to attack blindly.
     */
    double threatAt(RsiView view, Point at, double radius) {
        double limit = radius * radius;
        double power = 0;
        for (Contact contact : view.visible.values()) {
            if (contact.building()) continue;
            if (contact.at().distanceSquared(at) > limit) continue;
            power += Knowledge.power(contact.type());
        }
        return power;
    }

    /** The visible hostile combat unit with the most backup near it, or null. */
    Contact threatCentre(RsiView view, Point near, double radius) {
        Contact best = null;
        double bestPower = 0;
        double limit = radius * radius;
        for (Contact contact : view.visible.values()) {
            if (contact.building() || Knowledge.power(contact.type()) <= 0) continue;
            if (contact.at().distanceSquared(near) > limit) continue;
            double power = threatAt(view, contact.at(), 400);
            if (power > bestPower) {
                bestPower = power;
                best = contact;
            }
        }
        return best;
    }

    /** Our own combat power within radius of a point. */
    double armyPower(RsiView view, Point at, double radius) {
        double limit = radius * radius;
        double power = 0;
        for (Unit unit : view.own.values()) {
            if (!Knowledge.isCombatUnit(unit) || unit.carrier() >= 0) continue;
            if (at != null && unit.at().distanceSquared(at) > limit) continue;
            power += Knowledge.power(unit.type());
        }
        return power;
    }

    /**
     * Everything we can currently account for on their side: what is visible plus what was seen in
     * the last 40 seconds. Buildings are excluded — this is the number that decides whether a war
     * of annihilation or a war of position is the right strategy.
     */
    double enemyArmyPower(RsiView view) {
        double power = 0;
        for (Contact contact : view.visible.values()) {
            if (!contact.building()) power += Knowledge.power(contact.type());
        }
        for (Contact contact : view.lastSeen.values()) {
            if (contact.building() || view.visible.containsKey(contact.id())) continue;
            if (tick - contact.lastSeenTick() > 2400) continue;
            power += Knowledge.power(contact.type());
        }
        return power;
    }

    /**
     * Doctrine 1 target: the enemy building that is worth the most and can be dismantled soonest
     * without walking into their army.
     *
     * <p>Value comes from {@link Knowledge#priorityOf}; the penalty terms are travel distance and
     * the hostile power parked around the building. Both terms are relative to our own army power,
     * so the ranking means the same thing at 10 units and at 40. The command center is only cheap
     * here — if it is the only building we know, it is still the answer.
     */
    Point campaign(RsiView view, Point from, double power) {
        retireDestroyed(view);
        Contact commandCenter = pick(view, true);
        if (commandCenter != null) enemyBase = commandCenter.at();
        if (from == null) from = base == null ? new Point(view.width / 2, view.height / 2) : base;

        Contact current = campaignId >= 0 ? view.lastSeen.get(campaignId) : null;
        if (current != null && !view.visible.containsKey(campaignId)
                && from.distanceSquared(current.at()) < 450 * 450) {
            // The army is standing on it and does not see it: the contact memory is stale.
            clearSpot(current.at());
            current = null;
            campaignId = -1;
        }
        boolean keep = current != null && campaignPoint != null && !clearedSpot(campaignPoint)
                && tick - campaignTick < Tune.CAMPAIGN_TICKS
                && (view.visible.containsKey(campaignId) || tick - current.lastSeenTick() < 1800);
        if (keep) {
            campaignPoint = current.at();
            return campaignPoint;
        }

        Contact best = null;
        double bestScore = 0;
        for (Contact contact : view.lastSeen.values()) {
            if (!contact.building() || clearedSpot(contact.at())) continue;
            if (lostBases.contains(contact.id())) continue;
            double value = Knowledge.priorityOf(contact.type());
            if (value <= 0) continue;
            double distance = Math.sqrt(from.distanceSquared(contact.at()));
            double guard = threatAt(view, contact.at(), Tune.GUARD_RADIUS);
            // Halfway along the approach: an objective behind their army is not worth the walk,
            // however undefended the building itself is.
            Point mid = new Point((from.x() + contact.at().x()) / 2f,
                    (from.y() + contact.at().y()) / 2f);
            double traffic = threatAt(view, mid, Tune.GUARD_RADIUS * 0.8);
            double score = value / (1 + distance / 1500)
                    / (1 + Tune.GUARD_WEIGHT * guard / Math.max(300, power))
                    / (1 + Tune.GUARD_WEIGHT * 0.5 * traffic / Math.max(300, power));
            if (score > bestScore) {
                bestScore = score;
                best = contact;
            }
        }
        if (best == null) return target(view);
        campaignId = best.id();
        campaignPoint = best.at();
        campaignTick = tick;
        if (Tune.DEBUG) {
            log(view, "campaign " + best.type() + "@" + Math.round(best.at().x()) + ","
                    + Math.round(best.at().y()) + " score=" + String.format("%.2f", bestScore)
                    + " guard=" + Math.round(threatAt(view, best.at(), Tune.GUARD_RADIUS))
                    + " power=" + Math.round(power));
        }
        return campaignPoint;
    }

    Point target(RsiView view) {
        retireDestroyed(view);
        Contact commandCenter = pick(view, true);
        if (commandCenter != null) {
            enemyBase = commandCenter.at();
            return enemyBase;
        }
        // 团战里打掉一家之后，剩下那家的基地可能还没见过：退而求其次去打它任何一栋建筑，
        // 至少把部队往那边带，而不是在原地站到游戏结束。
        Contact building = pick(view, false);
        if (building != null) {
            enemyBase = building.at();
            return enemyBase;
        }
        if (enemyBase != null && !near(view, enemyBase, lostBases, 400)) return enemyBase;
        return mirror(view);
    }

    /**
     * A command center that stopped being visible while our army sits on top of it is gone, but the
     * contact memory keeps it for six more minutes. Without this a team game stalls on the first
     * dead base while the other enemy snowballs.
     */
    /** True when a remembered building is already known to be destroyed. */
    boolean lost(long id) {
        return lostBases.contains(id);
    }

    /**
     * A destroyed command center keeps its contact memory for six minutes, and in a team game the
     * dead player's factories and turrets stay right next to it. Retiring on "no enemy building
     * near" therefore never fires there, and the army parks on the corpse while the other enemy
     * bases rebuild. Only another live command center is a reason to keep standing on the spot.
     */
    private void retireDestroyed(RsiView view) {
        for (Contact contact : view.lastSeen.values()) {
            if (!Knowledge.isCommandCenter(contact.type())) continue;
            if (view.visible.containsKey(contact.id()) || lostBases.contains(contact.id())) continue;
            if (!watched(view, contact.at())) continue;
            if (anyEnemyCommandCenterNear(view, contact.at(), 500)) continue;
            lostBases.add(contact.id());
            log(view, "retire cc #" + contact.id() + " at " + Math.round(contact.at().x()) + ","
                    + Math.round(contact.at().y()));
        }
    }

    private boolean anyEnemyCommandCenterNear(RsiView view, Point at, double radius) {
        double limit = radius * radius;
        for (Contact contact : view.visible.values()) {
            if (!Knowledge.isCommandCenter(contact.type())) continue;
            if (contact.at().distanceSquared(at) < limit) return true;
        }
        return false;
    }

    private boolean watched(RsiView view, Point at) {
        int count = 0;
        for (Unit unit : view.own.values()) {
            if (!Knowledge.isCombatUnit(unit) || unit.carrier() >= 0) continue;
            if (unit.at().distanceSquared(at) > 700 * 700) continue;
            if (++count >= 3) return true;
        }
        return false;
    }

    private boolean anyEnemyBuildingNear(RsiView view, Point at, double radius) {
        double limit = radius * radius;
        for (Contact contact : view.visible.values()) {
            if (contact.building() && contact.at().distanceSquared(at) < limit) return true;
        }
        return false;
    }

    private static boolean near(RsiView view, Point at, Set<Long> skipped, double radius) {
        if (skipped.isEmpty()) return false;
        double limit = radius * radius;
        for (Long id : skipped) {
            Contact contact = view.lastSeen.get(id);
            if (contact != null && contact.at().distanceSquared(at) < limit) return true;
        }
        return false;
    }

    private Contact pick(RsiView view, boolean onlyCommandCenter) {
        Contact best = null;
        double bestScore = Double.MAX_VALUE;
        for (Contact contact : view.lastSeen.values()) {
            if (lostBases.contains(contact.id())) continue;
            if (onlyCommandCenter) {
                if (!Knowledge.isCommandCenter(contact.type())) continue;
            } else if (!contact.building()) {
                continue;
            }
            double score = view.visible.containsKey(contact.id()) ? 0 : 1;
            score = score * 1e7 + (base == null ? 0 : base.distanceSquared(contact.at()));
            if (score < bestScore) {
                bestScore = score;
                best = contact;
            }
        }
        return best;
    }

    /** Symmetric maps put the opponent across the map center from us. */
    Point mirror(RsiView view) {
        Point center = new Point(view.width / 2, view.height / 2);
        if (base == null) return center;
        Point guess = new Point(center.x() * 2 - base.x(), center.y() * 2 - base.y());
        return view.contains(guess) ? guess : center;
    }

    /** Nearest visible enemy, optionally limited to units that can hurt a given target class. */
    Contact nearestEnemy(RsiView view, Point from, float radius) {
        Contact best = null;
        double bestDistance = (double) radius * radius;
        for (Contact contact : view.visible.values()) {
            double distance = from.distanceSquared(contact.at());
            if (distance <= bestDistance) {
                bestDistance = distance;
                best = contact;
            }
        }
        return best;
    }

    /** Enemies close enough to threaten the base. */
    List<Contact> raiders(RsiView view, float radius) {
        List<Contact> result = new ArrayList<>();
        if (base == null) return result;
        for (Contact contact : view.visible.values()) {
            if (contact.at().distanceSquared(base) <= (double) radius * radius) result.add(contact);
        }
        return result;
    }

    boolean hasContact(RsiView view) {
        return !view.visible.isEmpty() || !view.lastSeen.isEmpty();
    }

    // ---------------------------------------------------------------- placement

    boolean clear(RsiView view, Point at, double spacing) {
        double limit = spacing * spacing;
        for (Unit unit : view.own.values()) {
            if (unit.building() && unit.at().distanceSquared(at) < limit) return false;
        }
        for (Contact contact : view.visible.values()) {
            if (contact.building() && contact.at().distanceSquared(at) < limit) return false;
        }
        // 团战：盟友的抽取器占着同一个矿点，别抢（两队分别下单只会白跑一趟）。
        for (RsiView.Ally ally : view.allies.values()) {
            if (ally.building() && ally.at().distanceSquared(at) < limit) return false;
        }
        return true;
    }

    /**
     * Unoccupied resource pools the builder can walk next to, nearest first. The pool tile itself
     * is usually not walkable — an extractor is placed on it — so reachability is tested against
     * the ring around it, the same way the engine checks building placement.
     */
    List<Point> freePools(RsiView view, Unit builder) {
        List<Point> result = new ArrayList<>();
        for (Point pool : view.resourcePools) {
            if (!view.canApproach(builder, pool, 45)) continue;
            if (!clear(view, pool, 30)) continue;
            result.add(pool);
        }
        result.sort((a, b) -> Double.compare(builder.at().distanceSquared(a),
                builder.at().distanceSquared(b)));
        return result;
    }

    void log(RsiView view, String message) {
        if (Tune.DEBUG) {
            System.out.println("RWX_AIRSI tick=" + view.tick + " t=" + (view.tick / 60)
                    + "s " + message);
        }
    }
}
