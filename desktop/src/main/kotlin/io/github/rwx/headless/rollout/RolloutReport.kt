package io.github.rwx.headless.rollout

import com.corrodinggames.rts.game.PlayerTeam
import com.corrodinggames.rts.game.units.BaseUnit
import com.corrodinggames.rts.gameFramework.GameEngine
import io.github.rwx.app.MicroJson
import java.io.BufferedWriter
import java.nio.file.Files
import java.nio.file.Path
import java.time.Instant
import java.util.TreeMap

/** Why the rollout stopped. Only the first two are decisive match results. */
internal enum class Outcome(val wire: String) {
    VICTORY("victory"),
    DEFEAT("defeat"),
    MAX_TICKS("max-ticks"),
    WALL_LIMIT("wall-limit"),
    ACTIVE("active"),
}

/**
 * Decides whether the match is over, using the engine's own flags first.
 *
 * `MissionEngine` ends a skirmish through `GameUI.startGameEndSequence()` / `endGameSequence()`, which
 * latch `hasWonGame` / `hasLostGame` for the player team (slot 0 here). The team flags below only flip
 * when a side is wiped out, which can be minutes after its last command center dies, so they are the
 * fallback rather than the primary signal.
 */
internal object EngineOutcome {
    fun evaluate(engine: GameEngine): Outcome {
        if (!engine.isContinuingAfterGameEnd) {
            if (engine.hasWonGame) return Outcome.VICTORY
            if (engine.hasLostGame) return Outcome.DEFEAT
        }
        val self = engine.playerTeam ?: return Outcome.ACTIVE
        if (isDefeated(self)) return Outcome.DEFEAT
        var enemies = 0
        for (team in PlayerTeam.getTeams()) {
            if (team == null || team.teamId < 0 || team.teamId >= PlayerTeam.TEAM_NEUTRAL) continue
            if (!self.c(team)) continue
            enemies++
            if (!isDefeated(team) && team.getUnitCount(true, false) > 0) return Outcome.ACTIVE
        }
        return if (enemies > 0) Outcome.VICTORY else Outcome.ACTIVE
    }

    private fun isDefeated(team: PlayerTeam): Boolean =
        team.isTeamVictory || team.isTeamDefeated || team.isTeamDefeatedTech || team.isTeamWipedOut
}

/** Writes one JSON line per sampled tick into `samples.jsonl`. */
internal class SampleWriter(private val spec: RolloutSpec) : AutoCloseable {
    private val file: Path = spec.outputDirectory.resolve("samples.jsonl")
    private val writer: BufferedWriter = Files.newBufferedWriter(file)
    var count: Int = 0
        private set

    fun write(engine: GameEngine, tick: Int) {
        val teams = linkedMapOf<String, Any?>()
        val roster = trackedTeams()
        val live = HashMap<Int, TeamSample>()
        for (team in roster) live[team.teamId] = TeamSample()
        val units = BaseUnit.bE.a()
        val size = BaseUnit.bE.size
        for (index in 0 until size) {
            val unit = units[index]
            val team = unit.team ?: continue
            val sample = live[team.teamId] ?: continue
            if (!unit.isAlive()) continue
            sample.units++
            sample.hp += unit.currentHealth
            sample.shield += unit.shield
            if (unit.bI()) sample.buildings++
            if (spec.sampling.includeUnitTypes) {
                val type = unit.r().v()
                sample.types.merge(type, 1, Int::plus)
            }
        }
        for (team in roster) {
            val sample = live[team.teamId] ?: continue
            teams[team.teamId.toString()] = linkedMapOf(
                "name" to team.teamName,
                "side" to team.teamColorId,
                "credits" to round(team.credits),
                "units" to sample.units,
                "buildings" to sample.buildings,
                "hp" to round(sample.hp),
                "shield" to round(sample.shield),
                "types" to TreeMap(sample.types),
            )
        }
        val row = linkedMapOf<String, Any?>(
            "tick" to tick,
            "gameMs" to engine.gameTimeMillis,
            "teams" to teams,
        )
        writer.write(MicroJson.encode(row))
        writer.newLine()
        count++
        if (count % 64 == 0) writer.flush()
    }

    private fun trackedTeams(): List<PlayerTeam> {
        PlayerTeam.refreshTeamInstances()
        return PlayerTeam.getTeamInstances()
            .filter { it.teamId >= 0 && it.teamId < PlayerTeam.TEAM_NEUTRAL }
            .sortedBy { it.teamId }
    }

    override fun close() {
        writer.flush()
        writer.close()
    }

    private class TeamSample {
        var units: Int = 0
        var buildings: Int = 0
        var hp: Double = 0.0
        var shield: Double = 0.0
        val types: MutableMap<String, Int> = HashMap()
    }
}

/** Builds `result.json`: the one file an RL harness needs after a match. */
internal object ResultWriter {
    fun write(
        spec: RolloutSpec,
        engine: GameEngine,
        startedAt: Instant,
        outcome: Outcome,
        ticks: Int,
        wallMs: Long,
        samples: SampleWriter,
        replay: String?,
    ): Map<String, Any?> {
        val teams = PlayerTeam.getTeamInstances()
            .filter { it.teamId >= 0 && it.teamId < PlayerTeam.TEAM_NEUTRAL }
            .sortedBy { it.teamId }
            .map { team ->
                linkedMapOf<String, Any?>(
                    "teamId" to team.teamId,
                    "name" to team.teamName,
                    "side" to team.teamColorId,
                    "aiDifficulty" to team.teamAIDifficultyOverride,
                    "defeated" to (team.isTeamDefeated || team.isTeamDefeatedTech || team.isTeamWipedOut ||
                        team.isTeamVictory),
                    "units" to team.getUnitCount(true, false),
                    "credits" to round(team.credits),
                )
            }
        val specTeams = spec.teams.sortedBy { it.slot }.map { team ->
            linkedMapOf<String, Any?>(
                "slot" to team.slot,
                "aiId" to team.aiId,
                "aiCode" to team.aiCode,
                "name" to team.name,
            )
        }
        val result = linkedMapOf<String, Any?>(
            "schema" to SCHEMA,
            "startedAt" to startedAt.toString(),
            "finishedAt" to Instant.now().toString(),
            "map" to spec.mapPath,
            "mapName" to engine.getCurrentMapName(),
            "winCondition" to spec.winCondition,
            "room" to linkedMapOf(
                "incomeMultiplier" to spec.room.incomeMultiplier,
                "startingCredits" to spec.room.startingCredits,
                "fogMode" to spec.room.fogMode,
                "revealedMap" to spec.room.revealedMap,
                "startingUnits" to spec.room.startingUnits,
                "noNukes" to spec.room.noNukes,
                "seed" to spec.room.seed,
                "aiDifficulty" to spec.room.aiDifficulty,
            ),
            // What the running match actually uses, read back from the engine: a room rule the engine
            // refused to take would otherwise hide behind the spec's requested value.
            "effective" to engine.networkEngine.roomSettings.let { live ->
                linkedMapOf<String, Any?>(
                    "incomeMultiplier" to live.incomeMultiplier,
                    "startingCredits" to live.startingCredits,
                    "fogMode" to live.fogMode,
                    "revealedMap" to live.revealedMap,
                    "startingUnits" to live.startingUnits,
                    "noNukes" to live.noNukes,
                    "seed" to live.randomSeed,
                )
            },
            "specTeams" to specTeams,
            "outcome" to outcome.wire,
            "decisive" to (outcome == Outcome.VICTORY || outcome == Outcome.DEFEAT),
            "winnerTeam" to if (outcome == Outcome.VICTORY) engine.playerTeam?.teamId else null,
            "ticks" to ticks,
            "gameMs" to engine.gameTimeMillis,
            "wallMs" to wallMs,
            "ticksPerSecond" to if (wallMs > 0) round(ticks * 1000.0 / wallMs) else null,
            "replay" to replay,
            "samples" to linkedMapOf("file" to "samples.jsonl", "count" to samples.count,
                "everyTicks" to spec.sampling.everyTicks),
            "teams" to teams,
            "engine" to linkedMapOf(
                "hasWonGame" to engine.hasWonGame,
                "hasLostGame" to engine.hasLostGame,
                "currentTick" to engine.currentTick,
            ),
        )
        val encoded = MicroJson.encode(result)
        Files.writeString(spec.outputDirectory.resolve("result.json"), encoded)
        return result
    }

    private const val SCHEMA = "rwx-rollout-result/1"
}

private fun round(value: Double): Double = Math.round(value * 1000.0) / 1000.0
