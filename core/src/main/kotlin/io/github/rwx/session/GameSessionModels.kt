package io.github.rwx.session

import com.corrodinggames.rts.gameFramework.network.GameModeType
import com.corrodinggames.rts.gameFramework.network.GameRoomSettings
import io.github.rwx.ui.model.BattleRoomPlayer

data class GameLoadingStatus(
    val text: String = "Loading...",
    val progress: Float? = null,
    val recentSteps: List<String> = emptyList(),
) {
    init {
        require(progress == null || progress in 0.0f..1.0f) { "progress must be null or in 0..1" }
    }
}

data class GameSessionRendererProfile(
    /** True for GameFrame command presentation; false when the platform owns a native surface. */
    val usesFrameCommandRendering: Boolean = true,
    val canStartNewSessionInPlace: Boolean = false,
    val usesNativeSurfaceForResumeBackground: Boolean = false,
)

data class MapSnapshot(
    val mapPath: String,
    val saveBytes: ByteArray,
    val battleRoomConfig: BattleRoomLaunchConfig? = null,
) {
    override fun equals(other: Any?): Boolean {
        if (this === other) return true
        if (other !is MapSnapshot) return false
        return mapPath == other.mapPath &&
                saveBytes.contentEquals(other.saveBytes) &&
                battleRoomConfig == other.battleRoomConfig
    }

    override fun hashCode(): Int =
        31 * (31 * mapPath.hashCode() + saveBytes.contentHashCode()) +
                battleRoomConfig.hashCode()
}

data class BattleRoomCoreConfig(
    val mapPath: String,
    val options: GameRoomSettings,
) {
    val isSavedGame: Boolean get() = options.gameModeType == GameModeType.savedGame
}

data class BattleRoomLaunchConfig(
    val sandbox: Boolean = false,
    val aiPlayerCount: Int = 0,
    val teamLayout: BattleRoomTeamLayout? = null,
    val room: BattleRoomCoreConfig,
    /**
     * Optional AI takeover for a local room keyed by team slot: `{0: hard_1income.code, 1: hard.code}`.
     * Slot 0 is the local player, so a code for it turns the whole room into an AI-vs-AI match: the
     * runner drives neither side and both play through the registered AI definitions. Absent or empty
     * keeps the normal human-plus-AI room.
     */
    val aiCodesBySlot: Map<Int, Int> = emptyMap(),
    /** Logical side -> physical team slot (0-based): `{0: 6, 1: 7}` plays spawn 7 against spawn 8. */
    val spawnBySlot: Map<Int, Int> = emptyMap(),
    /**
     * Team slot -> side colour: slots sharing a value are allies (`PlayerTeam.c` compares
     * `teamColorId`). `{0: 0, 1: 1, 2: 0, 3: 1}` makes slots 0+2 fight slots 1+3, i.e. a 2v2.
     * Applied after [spawnBySlot], because moving a team rewrites its colour.
     */
    val sideBySlot: Map<Int, Int> = emptyMap(),
)


data class BattleRoomSnapshot(
    val room: BattleRoomCoreConfig,
    val mapDisplayName: String,
    val mapTypeLabel: String,
    val players: List<BattleRoomPlayer>,
    val isHost: Boolean,
    val isNetworkMultiplayer: Boolean = false,

    val rwxP2PSession: Boolean = false,
    /** Short summary of the host's active mods when the room requires them, as in the original game. */
    val requiredModsSummary: String? = null,
    /** Original battleroom status text, including network and server visibility details. */
    val networkStatusText: String? = null,
    /** Max player slots in the room (engine-global team count; not a GameRoomSettings field). */
    val maxPlayers: Int = 10,
)

data class MultiplayerChatSnapshot(
    val text: String,
    val teamColorIndex: Int = -1,
)

enum class BattleRoomTeamLayout {
    TwoSides,
    ThreeSides,
    Ffa,
    Spectators,
    Random,
    AllVsAi,
    AllVs2,
}
