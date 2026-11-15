package com.corrodinggames.rts.gameFramework.mission;

import com.corrodinggames.rts.gameFramework.GameEngine;

/**
 * Run-level override for a skirmish map's victory condition.
 *
 * <p>Evaluation matches are already scored as "my command center died" / "every enemy command center
 * died" (see {@code evaluate/preprocess.js}), but a stock skirmish map keeps playing until a team
 * has no builder or mobile unit left. {@code --win-condition=commandCenter} (or the system property
 * {@code -Drwx.winCondition}) makes the engine end the match at the same moment the scored window
 * is cut, so the end screen, the recorded outcome and the scoring window agree.</p>
 *
 * <p>The override is installed once per process from the launch arguments and applied when a map
 * has finished loading, so it never changes the global default and never touches campaign, survival
 * or challenge missions. Every client of a networked match must pass the same value: a mismatch
 * changes the tick at which the game ends and can desynchronise the room. Absent the flag the map's
 * own {@code winCondition} stays in force.</p>
 */
public final class RwxWinCondition {
    /** System property read when the launch argument is absent; same values as the argument. */
    public static final String PROPERTY = "rwx.winCondition";
    /** Keep whatever the map declares (the default, and the only value normal play needs). */
    public static final String MAP = "map";
    /** A team loses when every command center (or map objective) it owns is gone. */
    public static final String COMMAND_CENTER = "commandCenter";

    private static final String[] VALUES = {
        MAP, COMMAND_CENTER, "allUnitsAndBuildings", "allBuildings", "noConstructionOrTech",
    };

    private static volatile String requested = MAP;

    private RwxWinCondition() {
    }

    /** Canonical name for a launch value; throws instead of silently falling back to the map rule. */
    public static String parse(String value) {
        if (value == null || value.trim().isEmpty()) return MAP;
        String trimmed = value.trim();
        for (String candidate : VALUES) {
            if (candidate.equalsIgnoreCase(trimmed)) return candidate;
        }
        throw new IllegalArgumentException(
            "--win-condition must be one of " + String.join(", ", VALUES) + ": " + value);
    }

    public static void install(String value) {
        requested = parse(value);
    }

    /** Canonical name of the mode in force, for logs and evidence rows. */
    public static String active() {
        return requested;
    }

    /**
     * Applies the installed mode right after {@link MissionEngine} has read the map settings.
     * Only skirmish maps are overridden: a mission's own objective must never be replaced.
     */
    public static void apply(MissionEngine engine) {
        if (engine == null || MAP.equals(requested)) return;
        if (!engine.isSkirmish) {
            GameEngine.log("RWX win condition ignored on non-skirmish map: " + requested);
            return;
        }
        WaveSpawnMode mode = modeOf(requested);
        engine.waveSpawnMode = mode;
        // Every skirmish map uses one mode for both sides; keep them equal after the override.
        engine.f = mode;
        GameEngine.log("RWX win condition: " + requested);
    }

    private static WaveSpawnMode modeOf(String value) {
        if ("allUnitsAndBuildings".equals(value)) return WaveSpawnMode.allUnitsAndBuildings;
        if ("allBuildings".equals(value)) return WaveSpawnMode.allBuildings;
        if ("noConstructionOrTech".equals(value)) return WaveSpawnMode.noConstructionOrTech;
        return WaveSpawnMode.commandCenter;
    }
}
