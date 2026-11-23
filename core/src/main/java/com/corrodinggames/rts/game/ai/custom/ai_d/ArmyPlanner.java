package com.corrodinggames.rts.game.ai.custom.ai_d;

import com.corrodinggames.rts.game.ai.custom.rsi_sdk.RsiStrategy;
import com.corrodinggames.rts.game.ai.custom.rsi_sdk.RsiView;
import com.corrodinggames.rts.game.ai.custom.rsi_sdk.RsiView.Contact;
import com.corrodinggames.rts.game.ai.custom.rsi_sdk.RsiView.Point;
import com.corrodinggames.rts.game.ai.custom.rsi_sdk.RsiView.Squad;
import com.corrodinggames.rts.game.ai.custom.rsi_sdk.RsiView.Unit;

import java.util.ArrayList;
import java.util.List;

/**
 * Army organisation, re-planned on the slow strategy cadence.
 *
 * <p>Everything that can walk to the enemy command center joins the push group — killing it is the
 * win condition. Units that cannot reach it (a land army on a lake map) hold the base instead of
 * walking into the water, and a small home group peels off when raiders show up.
 */
final class ArmyPlanner extends RsiStrategy.Operations {
    private final Blackboard board;

    ArmyPlanner(Blackboard board) {
        this.board = board;
    }

    @Override
    protected List<Squad> plan(RsiView view) {
        board.observe(view);
        board.updateOffence(view.tick);
        status(view);
        dumpBuildings(view);

        List<Unit> army = new ArrayList<>();
        for (Unit unit : view.own.values()) {
            if (Knowledge.isCombatUnit(unit) && unit.carrier() < 0) army.add(unit);
        }
        if (army.isEmpty()) return List.of();

        // 因敌制胜：对面上限很高时打"消耗/瓦解"（拆产能、绕开主力、按需回防），
        // 我方不吃亏时打"歼灭/收尾"（集中兵力压上去，直接结束）。比例错了两种打法都会输：
        // 打得过还绕圈子等于把时间送给对方的产能；打不过还硬冲等于送兵。
        double armyPower = board.armyPower(view, null, 0);
        boolean attrition = Tune.DOCTRINE == 1
                && board.enemyArmyPower(view) > armyPower * Tune.PRESSURED_RATIO;
        board.attrition = attrition;

        // 主动权：只有打消耗战时才分兵。兵力不吃亏时，分出去的两个单位不如并进主力。
        List<Unit> raid = attrition ? raidSquad(army) : List.of();
        army.removeAll(raid);

        Point target = attrition
                ? board.campaign(view, board.staging != null ? board.staging : board.base, armyPower)
                : board.target(view);
        board.goal = target;
        board.siegeMode = board.enemyBase != null && army.size() >= Tune.SIEGE_MIN_ARMY;

        List<Unit> pushing = new ArrayList<>();
        List<Unit> stuck = new ArrayList<>();
        split(view, army, target, pushing, stuck);
        // Less than half the army can bring its weapons to bear on the main objective: production
        // switches to hover/air, which is the only way those maps are ever crossed. Measured before
        // the retarget below, otherwise the fallback hides the very separation that matters.
        boolean separated = pushing.size() * 2 < army.size();
        board.waterSeparated = separated;
        if (separated) {
            // Most of the army cannot even walk to that objective (an island base, a cliff shelf, a
            // lake between the two spawns). Keeping the order means the whole army stands at home
            // while the enemy expands — picking something they *can* reach at least keeps the war
            // moving, and the campaign re-ranks every few seconds anyway.
            Point reachable = reachableTarget(view, army, target);
            if (reachable != null) {
                target = reachable;
                board.goal = reachable;
                split(view, army, target, pushing, stuck);
                board.log(view, "retarget reachable " + Math.round(reachable.x()) + ","
                        + Math.round(reachable.y()) + " push=" + pushing.size() + "/" + army.size());
            }
        }
        if (pushing.isEmpty() && !raid.isEmpty() && view.canApproach(raid.get(0), target, 90)) {
            // The raid group was the only thing that could cross (a hover group on a water map).
            // Keep the army whole instead of stranding the main body at home.
            army.addAll(raid);
            raid.clear();
            split(view, army, target, pushing, stuck);
        }
        // Less than half the army can bring its weapons to bear: production switches to hover/air,
        // which is the only way those maps are ever crossed.
        board.waterSeparated = pushing.size() * 2 < army.size();

        // 影响力地图的简版：家附近的敌方战斗力 vs 我家附近现有的战斗力。
        //
        // 旧做法是"能守住就全军回防"——一有骚扰就放弃整条战线，主动权全交给对面。
        // 现在按威胁派兵：小股骚扰交给炮塔和就近的兵，主力继续压他们的经济；
        // 只有家里现有的兵真的挡不住时，才把全军拉回来（这时回防才是唯一正确的事）。
        double homeThreat = board.base == null ? 0 : board.threatAt(view, board.base, Tune.HOME_RADIUS);
        double homePower = board.base == null ? 0
                : board.armyPower(view, board.base, Tune.HOME_RADIUS * 1.4);
        boolean race = Tune.RACE_ON > 0 && homeThreat > armyPower * Tune.RACE_ON;

        List<Contact> raiders = board.raiders(view, 1100);
        List<Squad> squads = new ArrayList<>(3);
        if (!raid.isEmpty()) {
            Point sweep = sweep(view, raid.get(0));
            List<Long> ids = new ArrayList<>(raid.size());
            for (Unit unit : raid) ids.add(unit.id());
            squads.add(new Squad("raid", ids, sweep));
            board.log(view, "raid units=" + ids.size() + " to=" + Math.round(sweep.x()) + ","
                    + Math.round(sweep.y()));
        }

        board.defending = false;
        List<Unit> guard = new ArrayList<>(stuck);
        if (homeThreat > 0 && board.base != null) {
            Contact threat = board.threatCentre(view, board.base, Tune.HOME_RADIUS);
            Point point = threat == null ? board.base : threat.at();
            boolean canHold = homePower >= homeThreat * Tune.DEFEND_ADVANTAGE;
            if (!attrition) {
                // 兵力不吃亏时的老判据（实测更好）：守得住就全军回防——家里有炮塔和维修，
                // 在他们够得到的地方换血是赚的；守不住就把全军压出去，用进攻换时间。
                if (canHold) {
                    guard.addAll(pushing);
                    pushing.clear();
                    board.defending = true;
                    board.goal = point;
                    board.log(view, "defend threat=" + Math.round(homeThreat)
                            + " mine=" + Math.round(homePower) + " units=" + guard.size());
                    if (!guard.isEmpty()) squads.add(new Squad("home", ids(guard), point));
                    return squads;
                }
                race = true;
            } else if (homeThreat >= Tune.DEFEND_MIN_THREAT) {
                double guardPower = powerOf(guard);
                // 打消耗战时按需派兵：挡得住就继续压他们的经济，挡不住才全员回防。
                boolean whole = !Tune.DEFEND_SPLIT || army.size() <= Tune.DEFEND_MIN_UNITS
                        || homeThreat >= armyPower * Tune.DEFEND_ON;
                if (whole) {
                    guard.addAll(pushing);
                    pushing.clear();
                    board.defending = true;
                    board.goal = point;
                    board.log(view, "defend threat=" + Math.round(homeThreat)
                            + " mine=" + Math.round(homePower) + " units=" + guard.size());
                    if (!guard.isEmpty()) squads.add(new Squad("home", ids(guard), point));
                    return squads;
                }
                double need = homeThreat * Tune.DEFEND_MARGIN;
                if (guardPower < need) {
                    List<Unit> near = new ArrayList<>(pushing);
                    near.sort((a, b) -> Double.compare(a.at().distanceSquared(board.base),
                            b.at().distanceSquared(board.base)));
                    for (Unit unit : near) {
                        if (guardPower >= need) break;
                        guard.add(unit);
                        pushing.remove(unit);
                        guardPower += Knowledge.power(unit.type());
                    }
                }
                board.log(view, "guard units=" + guard.size() + " power=" + Math.round(guardPower)
                        + " threat=" + Math.round(homeThreat) + " push=" + pushing.size());
                if (!guard.isEmpty()) squads.add(new Squad("home", ids(guard), point));
            } else if (!guard.isEmpty()) {
                squads.add(new Squad("home", ids(guard), point));
            }
        } else if (!guard.isEmpty()) {
            Contact threat = board.nearestEnemy(view, board.base, 1400);
            squads.add(new Squad("home", ids(guard), threat == null ? board.base : threat.at()));
        }

        if (race) {
            for (Unit unit : stuck) pushing.add(unit);
            List<Long> ids = new ArrayList<>(pushing.size());
            for (Unit unit : pushing) ids.add(unit.id());
            board.goal = target;
            board.log(view, "race home=" + Math.round(homeThreat) + " mine=" + Math.round(homePower)
                    + " units=" + ids.size());
            if (!ids.isEmpty()) squads.add(new Squad("race", ids, target));
            return squads;
        }

        // 波次状态机：集结 → 全波压上 → 打残后重新集结。
        // 直线 attack-move 会让新兵一个接一个送进对方防线；这里只有"这一波"的成员才继续进攻，
        // 之后生产的部队去前哨集结，等下一波。
        Point stage = rally(view, target);
        board.staging = stage;
        // 起推线跟着对方规模走，但必须有上限：对面 3.7 倍收入时兵力永远"更多"，
        // 不设上限就等于一直不进攻，最后被耗死。
        int threshold = Math.min(Tune.ATTACK_MAX_UNITS,
                Math.max(Tune.ATTACK_UNITS, recentEnemyArmy(view) + Tune.ATTACK_MARGIN));

        board.waveUnits.removeIf(id -> {
            Unit unit = view.own.get(id);
            return unit == null || !Knowledge.isCombatUnit(unit);
        });
        if (board.waveActive && board.waveUnits.size() * 3 < Math.max(1, board.waveSize)) {
            board.waveActive = false;
            board.waveUnits.clear();
            board.log(view, "wave spent left=" + board.waveUnits.size());
        }

        List<Unit> attack = new ArrayList<>();
        List<Unit> waiting = new ArrayList<>();
        for (Unit unit : pushing) {
            if (board.waveActive && board.waveUnits.contains(unit.id())) attack.add(unit);
            else waiting.add(unit);
        }
        if (!Tune.WAVE_ATTACK) {
            // 关掉波次时退化为"够数就走"，新生产的部队不断补充过去。
            boolean enough = pushing.size() >= threshold || !raiders.isEmpty();
            List<Long> ids = new ArrayList<>(pushing.size());
            for (Unit unit : pushing) ids.add(unit.id());
            if (!ids.isEmpty()) {
                squads.add(new Squad("main", ids, enough ? target : stage));
            }
            board.log(view, "plan main=" + ids.size() + " guard=" + guard.size()
                    + " push=" + enough + " need=" + threshold + " stuck=" + stuck.size());
            return squads;
        }
        // 只有攒够这一波才出发：来几个送几个是之前输掉中期的主因。
        // 第二个条件是"打得过目标守军"：数量够了但对面驻军明显更强时，冲进去就是白送。
        boolean launch = !board.waveActive && waiting.size() >= threshold
                && (!attrition || strongEnough(view, waiting, target));
        if (launch) {
            board.waveActive = true;
            board.waveSize = waiting.size();
            for (Unit unit : waiting) {
                board.waveUnits.add(unit.id());
                attack.add(unit);
            }
            waiting.clear();
        }

        if (!waiting.isEmpty()) {
            List<Long> ids = new ArrayList<>(waiting.size());
            for (Unit unit : waiting) ids.add(unit.id());
            squads.add(new Squad("gather", ids, stage));
        }
        if (!attack.isEmpty()) {
            List<Long> ids = new ArrayList<>(attack.size());
            for (Unit unit : attack) ids.add(unit.id());
            squads.add(new Squad("main", ids, target));
        }
        board.log(view, "plan attack=" + attack.size() + " wait=" + waiting.size()
                + " guard=" + guard.size() + " wave=" + board.waveActive
                + " need=" + threshold + " stage=" + Math.round(stage.x()) + ","
                + Math.round(stage.y()) + " stuck=" + stuck.size());
        return squads;
    }

    /**
     * A wave is only worth sending if it can beat the troops parked on the objective. Their
     * garrison is read from what is visible; an objective that is remembered but not currently
     * observed counts as empty, which is exactly when it is worth taking.
     */
    private static boolean strongEnough(RsiView view, List<Unit> wave, Point target) {
        if (target == null) return true;
        double power = 0;
        for (Unit unit : wave) power += Knowledge.power(unit.type());
        double guard = 0;
        double limit = 900 * 900;
        for (Contact contact : view.visible.values()) {
            if (contact.building()) continue;
            if (contact.at().distanceSquared(target) > limit) continue;
            guard += Knowledge.power(contact.type());
        }
        return guard <= 0 || power >= guard * Tune.LAUNCH_EDGE;
    }

    private static List<Long> ids(List<Unit> units) {
        List<Long> ids = new ArrayList<>(units.size());
        for (Unit unit : units) ids.add(unit.id());
        return ids;
    }

    private static double powerOf(List<Unit> units) {
        double power = 0;
        for (Unit unit : units) power += Knowledge.power(unit.type());
        return power;
    }

    /** Split the army by whether it can actually walk to the objective at all. */
    private static void split(RsiView view, List<Unit> army, Point target,
                              List<Unit> pushing, List<Unit> stuck) {
        pushing.clear();
        stuck.clear();
        for (Unit unit : army) {
            // Buildings sit on their own tile, so a target that is a building has to be approached
            // rather than walked onto.
            if (view.canApproach(unit, target, 90)) pushing.add(unit);
            else stuck.add(unit);
        }
    }

    /**
     * The nearest remembered enemy building that most of the army can actually walk to. Used when
     * the campaign target sits on another landmass: on those maps the alternative is not "attack
     * anyway", it is standing at home until the enemy arrives with the whole map.
     */
    private Point reachableTarget(RsiView view, List<Unit> army, Point exclude) {
        List<Contact> candidates = new ArrayList<>();
        for (Contact contact : view.lastSeen.values()) {
            if (!contact.building() || board.lost(contact.id())) continue;
            if (exclude != null && contact.at().distanceSquared(exclude) < 400) continue;
            candidates.add(contact);
        }
        candidates.sort((a, b) -> Double.compare(a.at().distanceSquared(board.base),
                b.at().distanceSquared(board.base)));
        Point best = null;
        int bestCount = 0;
        for (Contact contact : candidates.subList(0, Math.min(12, candidates.size()))) {
            int count = 0;
            for (Unit unit : army) {
                if (view.canApproach(unit, contact.at(), 90)) count++;
            }
            if (count > bestCount) {
                bestCount = count;
                best = contact.at();
            }
            if (bestCount == army.size()) break;
        }
        return bestCount * 2 > army.size() ? best : null;
    }

    /**
     * The units that go hunting on their own. Fast hulls first: a hover or air group can cross
     * terrain their army cannot follow and can leave a losing fight. Long-range pieces stay with the
     * main body — a siege unit alone behind their lines is a gift. The group is small on purpose;
     * it exists to make them split, not to win battles on its own.
     */
    private static List<Unit> raidSquad(List<Unit> army) {
        List<Unit> raid = new ArrayList<>();
        if (Tune.RAID_UNITS <= 0 || army.size() < Tune.RAID_MIN_ARMY) return raid;
        for (Unit unit : army) {
            if (raid.size() >= Tune.RAID_UNITS) break;
            if (unit.range() >= Tune.SIEGE_RANGE) continue;
            String movement = Knowledge.movementGuess(unit.type());
            if (!movement.equals("AIR") && !movement.equals("HOVER")) continue;
            raid.add(unit);
        }
        for (Unit unit : army) {
            if (raid.size() >= Tune.RAID_UNITS) break;
            if (raid.contains(unit)) continue;
            if (unit.range() >= Tune.SIEGE_RANGE) continue;
            if (Knowledge.combatValue(unit.type()) > 1.4) continue;
            raid.add(unit);
        }
        return raid;
    }

    /**
     * Where the raiders sweep: a ring around the enemy base, one leg per {@link Tune#RAID_CYCLE}.
     * The ring is outside their main base but inside their expansion space, so the group meets
     * extractors, fabricators and builders — the things that pay their bills — instead of their army.
     */
    private Point sweep(RsiView view, Unit lead) {
        Point enemy = board.enemyBase;
        if (enemy == null) enemy = board.mirror(view);
        if (board.base == null) return enemy;
        double facing = Math.atan2(enemy.y() - board.base.y(), enemy.x() - board.base.x());
        int phase = Math.max(0, view.tick / Math.max(300, Tune.RAID_CYCLE) % 4);
        double angle = facing + (phase - 1.5) * Math.PI / 3;
        for (float radius : new float[]{Tune.RAID_RADIUS, Tune.RAID_RADIUS * 0.65f, 600}) {
            Point point = new Point(enemy.x() + (float) (Math.cos(angle) * radius),
                    enemy.y() + (float) (Math.sin(angle) * radius));
            if (view.contains(point) && view.canReach(lead, point)) return point;
        }
        return enemy;
    }

    /** Enemy combat units seen in roughly the last 30 seconds; their army is a moving target. */
    private static int recentEnemyArmy(RsiView view) {
        int count = 0;
        for (Contact contact : view.lastSeen.values()) {
            if (contact.building()) continue;
            if (view.tick - contact.lastSeenTick() > 1800) continue;
            count++;
        }
        return count;
    }

    /** A point on the way to the target where the army can wait for reinforcements. */
    private Point rally(RsiView view, Point target) {
        if (board.base == null) return target;
        double dx = target.x() - board.base.x();
        double dy = target.y() - board.base.y();
        double length = Math.hypot(dx, dy);
        if (length < 1) return target;
        double distance = Math.min(Tune.RALLY_DISTANCE, length * 0.5);
        Point rally = new Point(board.base.x() + (float) (dx / length * distance),
                board.base.y() + (float) (dy / length * distance));
        return view.contains(rally) ? rally : target;
    }

    /** One line per strategy tick: the numbers used to tune the build ladder. */
    private void status(RsiView view) {
        if (!Tune.DEBUG || view.tick - board.lastLogTick < 900) return;
        board.lastLogTick = view.tick;
        int idle = 0;
        for (Unit unit : Knowledge.builders(view)) if (unit.idle()) idle++;
        System.out.println("RWX_AIRSI status tick=" + view.tick + " t=" + (view.tick / 60)
                + "s credits=" + Math.round(view.credits) + " income=" + view.income
                + " builders=" + Knowledge.builders(view).size() + "/" + idle + "idle"
                + " extractors=" + Knowledge.countAny(view, Knowledge::isExtractor)
                + " factories=" + Knowledge.countAny(view, Knowledge::isFactory)
                + " army=" + armySize(view) + " nearGoal=" + nearGoal(view)
                + " enemySeen=" + view.lastSeen.size()
                + " enemyUnits=" + view.visible.size()
                + " retreating=" + board.retreating.size()
                + " goal=" + (board.goal == null ? "-" : Math.round(board.goal.x()) + ","
                        + Math.round(board.goal.y()))
                + " ccVisible=" + commandCenterVisible(view)
                + " blocked=" + board.offensiveBlocked
                + nearContacts(view));
    }

    /** Every ~50 s dump the actions of our factories: what the engine actually offers to upgrade. */
    private void dumpBuildings(RsiView view) {
        if (!Tune.DEBUG) return;
        if (view.tick / 3000 == board.lastDumpTick / 3000) return;
        board.lastDumpTick = view.tick;
        for (Unit unit : view.own.values()) {
            if (!unit.building()) continue;
            StringBuilder text = new StringBuilder();
            for (var action : unit.actions()) {
                if (text.length() > 0) text.append(" | ");
                text.append(action.id()).append("->").append(action.product())
                        .append(" c=").append(action.credits())
                        .append(action.ready() ? " ready" : " -")
                        .append(action.queueable() ? " queue" : "")
                        .append(action.placement() ? " place" : "");
            }
            System.out.println("RWX_AIRSI building " + unit.type() + " queue=" + unit.queued()
                    + " [" + text + "]");
        }
    }

    private static boolean commandCenterVisible(RsiView view) {
        for (Contact contact : view.visible.values()) {
            if (Knowledge.isCommandCenter(contact.type())) return true;
        }
        return false;
    }

    /** Debug: the closest enemy contacts to the push goal, with type and distance. */
    private String nearContacts(RsiView view) {
        if (board.goal == null) return "";
        StringBuilder text = new StringBuilder();
        view.visible.values().stream()
                .sorted((x, y) -> Double.compare(x.at().distanceSquared(board.goal),
                        y.at().distanceSquared(board.goal)))
                .limit(4)
                .forEach(c -> text.append(' ').append(c.type()).append('@')
                        .append(Math.round(Math.sqrt(c.at().distanceSquared(board.goal))))
                        .append(c.building() ? "B" : ""));
        return text.toString();
    }

    /** How many of our units are within 600 world units of the push goal. */
    private int nearGoal(RsiView view) {
        if (board.goal == null) return 0;
        int count = 0;
        for (Unit unit : view.own.values()) {
            if (Knowledge.isCombatUnit(unit)
                    && unit.at().distanceSquared(board.goal) < 600 * 600) count++;
        }
        return count;
    }

    private static int armySize(RsiView view) {
        int count = 0;
        for (Unit unit : view.own.values()) if (Knowledge.isCombatUnit(unit)) count++;
        return count;
    }
}
