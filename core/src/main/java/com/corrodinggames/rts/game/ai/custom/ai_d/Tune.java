package com.corrodinggames.rts.game.ai.custom.ai_d;

/**
 * Tunables, read once from {@code -Drwx.airsi.*} system properties.
 *
 * <p>Every knob is a process-level property so a parameter sweep is a new JVM with different
 * {@code -D} flags instead of a rebuild. The defaults are the shipped strategy; a rollout log
 * prints the whole table once at start so a run can be reproduced from its log alone.
 */
final class Tune {
    private Tune() { }

    static final boolean DEBUG = bool("debug", false);

    /**
     * How the army spends its strength. 0 = decapitation: walk everything at the enemy command
     * center. 1 = adaptive: annihilation whenever their army outclasses ours, decapitation when it
     * does not. Kept as a switch so both can be measured from one build.
     */
    static final int DOCTRINE = integer("doctrine", 1);
    /** Their army power has to be this many times ours before the war of attrition switches on. */
    static final double PRESSURED_RATIO = num("pressuredRatio", 1.4);
    /** How long a campaign target is kept before the map is re-ranked. */
    static final int CAMPAIGN_TICKS = integer("campaignTicks", 900);
    /** Radius around an enemy building in which their units count as its garrison. */
    static final float GUARD_RADIUS = (float) num("guardRadius", 700);
    /** Units split off to sweep the enemy half; 0 disables the raid group. */
    static final int RAID_UNITS = integer("raidUnits", 2);
    /** The raid group only splits off when the army is at least this big. */
    static final int RAID_MIN_ARMY = integer("raidMinArmy", 10);
    /** How far from the enemy base the raid group sweeps. */
    static final float RAID_RADIUS = (float) num("raidRadius", 1400);
    /** Ticks between sweep legs. */
    static final int RAID_CYCLE = integer("raidCycle", 1200);
    /** Break contact instead of trading into a stronger hostile group. */
    static final boolean KITE = bool("kite", true);
    /** Kite when their local power is at least this multiple of ours. */
    static final double KITE_RATIO = num("kiteRatio", 2.0);
    /** Stop backing off once their local power drops below this multiple of ours. */
    static final double KITE_RELEASE = num("kiteRelease", 1.0);
    /** How long one retreat episode lasts before the ratio is re-tested. */
    static final int KITE_TICKS = integer("kiteTicks", 180);
    /** Groups below this absolute strength do not bother retreating. */
    static final double KITE_MIN_POWER = num("kiteMinPower", 2000);
    /**
     * Send the nearest units home for a raid instead of turning the whole army around. The main
     * push keeps its tempo; only a threat the base cannot handle pulls everyone back.
     */
    static final boolean DEFEND_SPLIT = bool("defendSplit", true);
    /** Power margin the home detachment wants over the incoming force. */
    static final double DEFEND_MARGIN = num("defendMargin", 1.3);
    /** Hostile power below this is left to the turrets; it does not interrupt the push. */
    static final double DEFEND_MIN_THREAT = num("defendMinThreat", 1500);
    /** Launch a wave when its power is at least this share of the target's garrison. */
    static final double LAUNCH_EDGE = num("launchEdge", 0.75);
    /** How strongly a hostile garrison makes a building unattractive as a campaign target. */
    static final double GUARD_WEIGHT = num("guardWeight", 2.0);
    /** Focus the whole squad on one target instead of each unit picking its own. */
    static final boolean FOCUS_FIRE = bool("focusFire", true);
    /** Only walk into the command center when their garrison there is thinner than this share. */
    static final double CC_GARRISON = num("ccGarrison", 1.2);
    /** Weight of "their units are clustered here" when a unit picks what to shoot. */
    static final double ISOLATION = num("isolation", 1.0);

    /** Builders to keep alive; below this the command center keeps producing them. */
    static final int BUILDERS = integer("builders", 5);
    /** Credits the economy refuses to spend, leaving them for unit production. */
    static final double UNIT_RESERVE = num("unitReserve", 600);

    /** Hard cap on extractors (0 = no cap). */
    static final int EXTRACTOR_MAX = integer("extractorMax", 40);
    /** Minimum credits before a 700-credit extractor is started. */
    static final double EXTRACTOR_MIN_CREDITS = num("extractorMinCredits", 700);

    static final int LAND_FACTORY_MAX = integer("landFactoryMax", 10);
    /** Upper bound on production buildings; the ladder asks for income/30 of them. */
    static final int FACTORY_MAX = integer("factoryMax", 24);
    /** Credits per second one factory can turn into units (measured rough throughput). */
    static final double FACTORY_THROUGHPUT = num("factoryThroughput", 30);
    static final int MECH_FACTORY_MAX = integer("mechFactoryMax", 6);
    static final int AIR_FACTORY_MAX = integer("airFactoryMax", 2);
    static final int TURRET_MAX = integer("turretMax", 6);
    /** A placement the engine rejected stays blacklisted for this long. */
    static final int BAD_SPOT_TICKS = integer("badSpotTicks", 3000);
    /** Turrets built before any enemy shows up; the first wave often arrives unseen. */
    static final int EARLY_TURRETS = integer("earlyTurrets", 0);
    static final int ANTI_AIR_MAX = integer("antiAirMax", 2);
    static final int FABRICATOR_MAX = integer("fabricatorMax", 10);
    static final double FABRICATOR_MIN_CREDITS = num("fabricatorMinCredits", 2600);
    /** Idle builders reclaim visible wreckage (`view.salvage` + RECLAIM) instead of standing still. */
    static final boolean RECLAIM = bool("reclaim", true);
    /** Reclaim targets further away than this are not worth the walk. */
    static final float RECLAIM_RADIUS = (float) num("reclaimRadius", 2500);

    /** Bank needed before the first factory upgrade is considered. */
    static final double UPGRADE_MIN_CREDITS = num("upgradeMinCredits", 1600);
    /** Bank needed before a land factory is upgraded to level 2 (plasma, mammoth, laser tank). */
    static final double LAND_L2_MIN_CREDITS = num("landL2MinCredits", 2200);
    /** Bank needed before the mech factory T2 upgrade (the mechLaser unlock). */
    static final double MECH_T2_MIN_CREDITS = num("mechT2MinCredits", 4600);
    /** Credits kept back so an upgrade does not empty the bank. */
    static final double UPGRADE_RESERVE = num("upgradeReserve", 400);
    /** What production must leave untouched while the next extractor tier is being saved for. */
    static final double UPGRADE_SAVE_CREDITS = num("upgradeSaveCredits", 1500);
    /** Below this many extractors, rebuilding them outranks every upgrade. */
    static final int REBUILD_POOLS = integer("rebuildPools", 6);
    /** How many siege lasers the strike group wants (0 disables the doctrine). */
    static final int LASER_COUNT = integer("laserCount", 3);
    /** Price of one siege laser, used to size the reserve. */
    static final double LASER_PRICE = num("laserPrice", 7000);
    /** Upgrades at or below this price are worth pausing unit production for. */
    static final double CHEAP_UPGRADE_MAX = num("cheapUpgradeMax", 0);
    static final double SAVE_UPGRADE_MAX = num("saveUpgradeMax", 4600);
    /** Units to keep before the surplus starts going into upgrades. */
    static final int ARMY_FLOOR = integer("armyFloor", 20);
    /** Share of income banked for the next investment (upgrade or siege unit). */
    static final double INVEST_SHARE = num("investShare", 0.35);
    /** Production share while the economy is banking for the siege strike. */
    static final double SIEGE_SHARE = num("siegeShare", 0.25);

    /**
     * Fraction of health at which a unit breaks off and goes home. Off by default: these units do
     * not heal on their own, so a retreat is a permanent loss of a unit that still shoots at full
     * damage. Enable it only if repair support exists.
     */
    static final double RETREAT_HP = num("retreatHp", 0.0);
    /** Fraction of health at which a retreated unit rejoins. */
    static final double REGROUP_HP = num("regroupHp", 0.65);

    /** Squad reaction cadence in ticks (60 ticks = 1 s). */
    static final int TACTICS_TICKS = integer("tacticsTicks", 20);

    /** Extra reach beyond weapon range that still counts as "shoot it now". */
    static final double ENGAGE_MARGIN = num("engageMargin", 1.6);
    /** Never acquire targets closer than this, whatever the weapon range is. */
    static final float ENGAGE_RADIUS = (float) num("engageRadius", 450);

    /** Do not re-issue movement to a unit that is closer than this to its goal. */
    static final double ARRIVE_DISTANCE = num("arriveDistance", 260);

    /** Army size that triggers a push. Below it the army waits at a rally point instead of trickling in. */
    static final int ATTACK_UNITS = integer("attackUnits", 8);
    /** Inside this radius a visible enemy command center outranks every other target. */
    static final float COMMAND_CENTER_PRIORITY = (float) num("commandCenterPriority", 900);

    /** Attack in regrouped waves instead of continuously feeding reinforcements. */
    static final boolean WAVE_ATTACK = bool("waveAttack", true);
    /** Hard cap on the push threshold; beyond this the army attacks even against a bigger enemy. */
    static final int ATTACK_MAX_UNITS = integer("attackMaxUnits", 20);
    /** Extra units wanted on top of the enemy's recently seen army before pushing. */
    static final int ATTACK_MARGIN = integer("attackMargin", 0);
    /** How far from the base the army waits for reinforcements. */
    static final double RALLY_DISTANCE = num("rallyDistance", 700);
    /** A unit that has not moved for this many ticks while moving gets its orders cleared. */
    static final int STUCK_TICKS = integer("stuckTicks", 900);

    /** Units kept home when the base is under attack. */
    static final int DEFENDERS = integer("defenders", 4);
    /** Influence radius around the base for the defence decision. */
    static final float HOME_RADIUS = (float) num("homeRadius", 1300);
    /** Defend only when our local power is at least this much larger than the incoming force. */
    static final double DEFEND_ADVANTAGE = num("defendAdvantage", 1.2);
    /** Range at which a unit can shoot a base from outside its turrets. */
    static final float SIEGE_RANGE = (float) num("siegeRange", 280);
    /** Preference multiplier for siege units once the enemy base is known. */
    static final double SIEGE_BIAS = num("siegeBias", 2.0);
    /** Army size from which the siege preference kicks in. */
    static final int SIEGE_MIN_ARMY = integer("siegeMinArmy", 10);
    /** Outgunned at home beyond this ratio: stop defending and race their base instead. */
    static final double RACE_ON = num("raceOn", 0.0);
    /** Enter defence when hostile power near home exceeds our local power times this. */
    static final double DEFEND_ON = num("defendOn", 1.5);
    /** Leave defence once it falls below this fraction. */
    static final double DEFEND_OFF = num("defendOff", 0.8);
    /** Below this army size the AI stays home no matter what. */
    static final int DEFEND_MIN_UNITS = integer("defendMinUnits", 4);

    /** Let a factory idle to save for a unit this much better than anything affordable. */
    static final double SAVE_FOR_UNIT_SCORE = num("saveForUnitScore", 3.5);

    /** Production buildings wanted for a given income: each one can spend about 30 credits/s. */
    static int factoryTarget(double income) {
        int target = (int) Math.round(2 + income / FACTORY_THROUGHPUT);
        return Math.max(2, Math.min(FACTORY_MAX, target));
    }

    /** Prefer hover units when the enemy base is in another land region. */
    static final boolean AUTO_HOVER = bool("autoHover", true);

    static void print() {
        System.out.println("RWX_AIRSI tune builders=" + BUILDERS + " reserve=" + UNIT_RESERVE
                + " landFactoryMax=" + LAND_FACTORY_MAX + " mechFactoryMax=" + MECH_FACTORY_MAX
                + " upgradeMin=" + UPGRADE_MIN_CREDITS + " attackUnits=" + ATTACK_UNITS
                + " retreat=" + RETREAT_HP + " tactics=" + TACTICS_TICKS + " hover=" + AUTO_HOVER
                + " doctrine=" + DOCTRINE + " raid=" + RAID_UNITS
                + " kite=" + KITE + "/" + KITE_RATIO + " focus=" + FOCUS_FIRE
                + " split=" + DEFEND_SPLIT + " launchEdge=" + LAUNCH_EDGE
                + " ccGarrison=" + CC_GARRISON + " isolation=" + ISOLATION);
    }

    static void log(String message) {
        if (DEBUG) System.out.println("RWX_AIRSI " + message);
    }

    private static double num(String key, double fallback) {
        try {
            String raw = System.getProperty("rwx.airsi." + key);
            return raw == null || raw.isBlank() ? fallback : Double.parseDouble(raw.trim());
        } catch (RuntimeException ignored) {
            return fallback;
        }
    }

    private static int integer(String key, int fallback) {
        return (int) num(key, fallback);
    }

    private static boolean bool(String key, boolean fallback) {
        String raw = System.getProperty("rwx.airsi." + key);
        return raw == null || raw.isBlank() ? fallback : Boolean.parseBoolean(raw.trim());
    }
}
