package com.corrodinggames.rts.gameFramework;

import com.corrodinggames.rts.game.PlayerTeam;
import com.corrodinggames.rts.gameFramework.network.GameOutputStream;

import java.io.IOException;

/** Playback-only perspective and result. Neither changes the saved simulation or its alliances. */
public final class RwxReplayPresentation {
    public static final String VIEW_BLOCK = "rwxPerspective";
    public static final String RESULT_BLOCK = "rwxOutcome";

    public enum Outcome {
        NONE, VICTORY, DEFEAT, STALEMATE;

        public static Outcome fromWire(String value) {
            return switch (value) {
                case "victory" -> VICTORY;
                case "defeat" -> DEFEAT;
                case "stalemate", "max-ticks", "wall-limit" -> STALEMATE;
                default -> NONE;
            };
        }
    }

    private int viewTeamId = -1;
    private Outcome recorded = Outcome.NONE;
    private Outcome playback = Outcome.NONE;

    void reset() {
        viewTeamId = -1;
        recorded = Outcome.NONE;
        playback = Outcome.NONE;
    }

    void setViewTeamId(int teamId) {
        viewTeamId = teamId;
    }

    void setRecordedOutcome(Outcome outcome) {
        recorded = outcome;
    }

    public PlayerTeam viewTeam() {
        return viewTeamId < 0 || viewTeamId >= PlayerTeam.TEAM_NEUTRAL ? null : PlayerTeam.k(viewTeamId);
    }

    public int colorIndex(PlayerTeam team) {
        PlayerTeam view = viewTeam();
        if (view == null || team.teamId < 0 || team.isSpectatorTeamColor()) return -1;
        if (team.d(view)) return 0;
        return team.c(view) ? 1 : -1;
    }

    public Outcome outcome() {
        return playback;
    }

    static Outcome nativeOutcome(GameEngine engine) {
        if (engine.hasLostGame) return Outcome.DEFEAT;
        if (engine.hasWonGame) return Outcome.VICTORY;
        return Outcome.NONE;
    }

    Outcome outcomeForRecording(GameEngine engine) {
        return recorded == Outcome.NONE ? nativeOutcome(engine) : recorded;
    }

    void finish(GameEngine engine) {
        PlayerTeam view = viewTeam();
        Outcome original = view == null || view == engine.playerTeam ? nativeOutcome(engine) : Outcome.NONE;
        if (recorded == Outcome.NONE && original == Outcome.NONE && view != null) {
            original = legacyOutcome(view);
        }
        playback = switch (recorded) {
            case VICTORY, DEFEAT -> recorded;
            default -> original == Outcome.NONE ? Outcome.STALEMATE : original;
        };
    }

    private static Outcome legacyOutcome(PlayerTeam view) {
        boolean alliesAlive = false;
        boolean enemiesAlive = false;
        boolean hasEnemies = false;
        for (PlayerTeam team : PlayerTeam.getTeams()) {
            if (team == null || team.teamId < 0 || team.isSpectatorTeamColor()) continue;
            boolean alive = !team.isTeamDefeated && !team.isTeamWipedOut && !team.isTeamDefeatedTech
                    && !team.isTeamVictory && team.getUnitCount(true, false) > 0;
            if (view.d(team)) alliesAlive |= alive;
            if (view.c(team)) {
                hasEnemies = true;
                enemiesAlive |= alive;
            }
        }
        if (!hasEnemies || alliesAlive == enemiesAlive) return Outcome.NONE;
        return alliesAlive ? Outcome.VICTORY : Outcome.DEFEAT;
    }

    static void writeOutcome(GameOutputStream stream, Outcome outcome) throws IOException {
        if (outcome == Outcome.NONE) return;
        stream.startBlock(RESULT_BLOCK);
        stream.writeStringUTF(outcome.name().toLowerCase(java.util.Locale.ROOT));
        stream.endBlock(RESULT_BLOCK);
    }
}
