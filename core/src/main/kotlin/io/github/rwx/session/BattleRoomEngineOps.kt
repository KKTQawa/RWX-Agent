package io.github.rwx.session

import com.corrodinggames.rts.game.GameTeam
import com.corrodinggames.rts.game.PlayerTeam
import com.corrodinggames.rts.game.PlayerTeam.resetTeamRegistry
import com.corrodinggames.rts.game.ai.AIController
import com.corrodinggames.rts.gameFramework.GameEngine
import com.corrodinggames.rts.gameFramework.network.NetworkEngine
import com.corrodinggames.rts.gameFramework.network.TeamLayoutType
import com.corrodinggames.rts.gameFramework.network.GameInputStream

/** Restores the world and the detached room rules captured with it on either renderer. */
fun GameEngine.restoreMapSnapshot(snapshot: MapSnapshot) {
    check(!isNetworkGameActive()) { "Cannot restore a local map snapshot during multiplayer" }
    check(gameSaver.readLocalMapSnapshot(GameInputStream(snapshot.saveBytes))) {
        "Unable to restore in-memory save: ${snapshot.mapPath}"
    }
    networkEngine?.let { network ->
        snapshot.battleRoomConfig?.let { config ->
            network.roomSettings = config.room.options.clone()
            network.isSandboxMode = config.sandbox
        }
        network.selectedMapPath = snapshot.mapPath
    }
    applyLoadedSinglePlayerFogRules()
}


/**
 * Applies the room fog rules restored by a standalone skirmish/sandbox save to the loaded map.
 *
 * A sandbox save restores its room rules but deliberately leaves the map's initial fog untouched.
 * Android initializes a skirmish map without explicit fog metadata as no-fog, while the desktop
 * engine initializes it as LOS. Apply the restored room rules here so that backend default does
 * not change the saved game mode.
 */
fun GameEngine.applyLoadedSinglePlayerFogRules() {
    val network = networkEngine ?: return
    if (!network.singleplayerServer || network.networkGameActive) return
    val map = tileMap ?: return
    when (network.roomSettings.fogMode) {
        0 -> {
            map.fogEnabled = false
            map.fogPeriodicMaintenanceEnabled = false
        }

        1 -> {
            map.fogEnabled = true
            map.fogPeriodicMaintenanceEnabled = false
        }

        2 -> {
            map.fogEnabled = true
            map.fogPeriodicMaintenanceEnabled = true
        }
    }
    map.fogRenderActive = network.roomSettings.revealedMap
}

/** The engine layout constant for [this], or null when the layout has no direct engine equivalent. */
fun BattleRoomTeamLayout.toEngineTeamLayoutType(): TeamLayoutType? =
    when (this) {
        BattleRoomTeamLayout.TwoSides -> TeamLayoutType.layout_2sides
        BattleRoomTeamLayout.ThreeSides -> TeamLayoutType.layout_3sides
        BattleRoomTeamLayout.Ffa -> TeamLayoutType.layout_ffa
        BattleRoomTeamLayout.Spectators -> TeamLayoutType.layout_spectators
        BattleRoomTeamLayout.Random,
        BattleRoomTeamLayout.AllVsAi,
        BattleRoomTeamLayout.AllVs2 -> null
    }

/** Applies [layout], falling back to a manual team-colour assignment for RWX-only layouts. */
fun NetworkEngine.applyBattleRoomTeamLayout(layout: BattleRoomTeamLayout) {
    val engineLayout = layout.toEngineTeamLayoutType()
    if (engineLayout != null) {
        a(engineLayout)
    } else {
        applyCustomTeamMode(layout)
    }
}

private fun NetworkEngine.applyCustomTeamMode(layout: BattleRoomTeamLayout) {
    if (!isServer) return
    val teams = PlayerTeam.getTeams().filter { !it.isSpectatorTeamColor }
    when (layout) {
        BattleRoomTeamLayout.AllVsAi ->
            teams.forEach { it.teamColorId = if (it.isTeamControlledByAI) 1 else 0 }

        BattleRoomTeamLayout.AllVs2 ->
            teams.forEach { it.teamColorId = if (it.teamId == 0) 1 else 0 }

        BattleRoomTeamLayout.Random -> {
            val shuffled = teams.shuffled()
            val teamsPerSide = when (shuffled.size) {
                in 0..8 -> 2
                in 9..21 -> 3
                in 22..32 -> 4
                else -> 5
            }
            var remainingInSide = teamsPerSide
            var currentSide = 0
            shuffled.forEach { team ->
                team.teamColorId = currentSide
                remainingInSide--
                if (remainingInSide == 0) {
                    remainingInSide = teamsPerSide
                    currentSide++
                }
            }
        }

        else -> return
    }
}


fun GameEngine.configureLocalBattleRoom(
    config: BattleRoomLaunchConfig,
    logLabel: String,
): NetworkEngine? {
    val networkEngine = networkEngine ?: return null
    // Starting a local server resets its mutable settings. Snapshot the requested rules first,
    // including when a caller captured them directly from this engine's current room.
    val settings = config.room.options.clone()
    if (networkEngine.roomSettings === config.room.options) {
        networkEngine.roomSettings = networkEngine.roomSettings.clone()
    }
    networkEngine.selectedMapPath = config.room.mapPath
    val playerName = networkEngine.playerName
        ?: settingsEngine?.lastNetworkPlayerName
        ?: "Player"
    networkEngine.playerName = playerName
    networkEngine.requireActiveMods = true
    resetTeamRegistry()
    // A slot-0 AI code makes this an AI-vs-AI room: the local team must be an actual AIController,
    // because team behaviour follows the team object type, not the isTeamControlledByAI flag. It is
    // created before the level loads so starting units are owned by this instance from tick 0.
    val localPlayerAiCode = config.aiCodesBySlot[0]
    val localPlayerTeam: PlayerTeam = if (localPlayerAiCode != null) {
        AIController(0).also { ai ->
            ai.teamName = playerName.ifBlank { "Player" }
            ai.teamColorId = 0
            ai.teamPingTime = localPlayerAiCode
            ai.teamAIDifficultyOverride = localPlayerAiCode
            ai.isTeamControlledByAI = true
            ai.isTeamSpectator = false
            ai.isTeamObserver = false
            ai.isTeamReady = true
        }
    } else {
        GameTeam(0).also { team ->
            team.teamName = playerName.ifBlank { "Player" }
            team.isTeamSpectator = false
            team.isTeamControlledByAI = false
            team.isTeamObserver = false
            team.isTeamReady = true
            team.teamPingTime = 0
        }
    }
    playerTeam = localPlayerTeam
    this.networkEngine?.localPlayerTeam = localPlayerTeam

    val started = if (config.sandbox) {
        networkEngine.startSandboxServer()
    } else {
        networkEngine.startSingleplayerServer()
    }
    check(started) { "Unable to start $logLabel battle room" }
    check(networkEngine.localPlayerTeam === localPlayerTeam) {
        "Unable to start $logLabel battle room: local player team was not registered"
    }
    // startSingleplayerServer() may hand team 0 a different instance than the one staged above.
    // Re-assert the AI seat on whichever team actually holds team 0 so slot 0 keeps the same AI
    // difficulty (and therefore the same income multiplier) as slot 1.
    if (localPlayerAiCode != null) {
        PlayerTeam.k(0)?.let { live ->
            if (live.teamAIDifficultyOverride != localPlayerAiCode) {
                live.teamAIDifficultyOverride = localPlayerAiCode
                live.teamPingTime = localPlayerAiCode
                live.isTeamControlledByAI = true
            }
        }
    }

    if (!config.room.isSavedGame) {
        settings.gameModeType = getGameModeType()
        settings.mapPath = currentMapFilename
    }
    networkEngine.roomSettings = settings
    networkEngine.a(settings)

    repeat(config.aiPlayerCount.coerceAtLeast(0)) {
        networkEngine.addAIToGame()
    }
    config.teamLayout?.let(networkEngine::applyBattleRoomTeamLayout)
    applyAiCodes(config.aiCodesBySlot)
    applySpawnSlots(config.spawnBySlot)
    return networkEngine
}

/**
 * Puts each side on the spawn point the launcher asked for: a two-side room on an 8-spawn map
 * otherwise always takes the first two spawns, which silently biases map comparisons.
 *
 * <p>`setTeamId` also rewrites `teamColorId`, and the engine's own swap overwrites it on both teams —
 * either way the two sides can end up reading as allies (`PlayerTeam.c` compares that colour), which
 * ends the match at tick 1. So movers are parked on a free scratch slot first, and each side's colour is
 * restored to its logical side index afterwards.</p>
 */
private fun GameEngine.applySpawnSlots(spawnBySlot: Map<Int, Int>) {
    if (spawnBySlot.isEmpty()) return
    val networkEngine = networkEngine ?: return
    val logicalByTarget = spawnBySlot.entries.associate { it.value to it.key }
    val targets = spawnBySlot.values.toSet()
    val scratch = (0..9).firstOrNull { PlayerTeam.k(it) == null && it !in targets && it !in spawnBySlot.keys } ?: -1
    val pending = LinkedHashMap<PlayerTeam, Int>()
    for ((from, to) in spawnBySlot.entries.sortedBy { it.value }) {
        val team = PlayerTeam.k(from) ?: continue
        if (team.teamId != to) {
            val occupant = PlayerTeam.k(to)
            if (occupant != null) {
                // Displace only the other side of this same match; anything else is left where it is.
                if (occupant.teamId !in spawnBySlot.keys || scratch < 0) continue
                networkEngine.a(team, scratch)
            }
        }
        pending[team] = to
    }
    // Free targets one round at a time: a team sitting on another side's target has to leave first, so
    // a single pass can leave somebody parked on the scratch slot.
    repeat(4) {
        var moved = false
        for ((team, to) in pending) {
            if (team.teamId == to || PlayerTeam.k(to) != null) continue
            networkEngine.a(team, to)
            moved = true
        }
        if (!moved) return@repeat
    }
    for ((team, to) in pending) logicalByTarget[to]?.let { team.teamColorId = it }
}

/**
 * Pins the registered AI definition of each slot before the level loads. A team's AI code travels in
 * [PlayerTeam.teamAIDifficultyOverride] (the engine resolves it through `getTeamColorId`), and it has
 * to be in place before the first tick so the custom runtime is created from the right definition.
 */
private fun GameEngine.applyAiCodes(codesBySlot: Map<Int, Int>) {
    if (codesBySlot.isEmpty()) return
    for (team in PlayerTeam.getTeams()) {
        if (team == null || team.teamId < 0) continue
        val code = codesBySlot[team.teamId] ?: continue
        team.teamPingTime = code
        team.teamAIDifficultyOverride = code
        // A team that still carries the spectator flag gets its AI income multiplier applied twice
        // (getEconomyMultiplier × getSpectatorEnergyFactor), which made the AI seat 1.4× richer than
        // the local seat in every headless match. AI teams are players here, never spectators.
        team.isTeamSpectator = false
        team.isTeamObserver = false
    }
}

/** Sanitises a user-supplied save name into something the engine's save directory accepts. */
fun String.toRwSaveName(): String =
    trim()
        .ifBlank { "rwx_save" }
        .replace(".", "_")
        .replace("/", "_")
        .replace("\\", "_")

/** Sanitises a user-supplied map name into a filesystem-safe `.tmx` basename. */
fun String.toRwExportMapName(): String =
    trim()
        .ifBlank { "rwx_map" }
        .replace(".", "_")
        .replace("/", "_")
        .replace("\\", "_")
        .replace("|", "_")
        .replace("?", "_")
        .replace(":", "_")
        .replace("*", "_")
        .replace("\"", "_")
        .replace("<", "_")
        .replace(">", "_")
