package io.github.rwx.headless.rollout

import com.corrodinggames.rts.game.PlayerTeam
import com.corrodinggames.rts.game.ai.custom.rwx_cli_tool.RwxIncomeRate
import com.corrodinggames.rts.game.units.BaseUnit
import com.corrodinggames.rts.game.units.OrderableUnit
import com.corrodinggames.rts.game.units.buildings.CommandCenter
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
 * 一局的结果视角：从哪个队看、我方（同色）是谁、敌方是谁。
 *
 * `PlayerTeam.c(t)` = t 与我为敌（颜色不同）；`PlayerTeam.d(t)` = t 与我同色（含自己）。
 * 引擎自己只对 player team（第一个队伍）维护 `hasWonGame` / `hasLostGame`，所以换视角后
 * 那两个 flag 只能用于原始玩家视角。
 */
internal class MatchPerspective private constructor(
    val mode: String,
    val slot: Int,
    val selfTeam: PlayerTeam?,
    val playerTeam: PlayerTeam?,
    val allies: List<PlayerTeam>,
    val enemies: List<PlayerTeam>,
) {
    val teamMode: Boolean get() = mode == RolloutPerspective.MODE_TEAM
    val isPlayerTeam: Boolean get() = selfTeam != null && selfTeam === playerTeam

    companion object {
        fun of(engine: GameEngine, perspective: RolloutPerspective?): MatchPerspective {
            val teams = PlayerTeam.getTeams().filterNotNull()
                .filter { it.teamId >= 0 && it.teamId < PlayerTeam.TEAM_NEUTRAL }
            val player = engine.playerTeam
            val slot = perspective?.slot ?: -1
            val self = if (slot < 0) player else teams.firstOrNull { it.teamId == slot } ?: player
            val allies = if (self == null) emptyList() else teams.filter { self.d(it) }
            val enemies = if (self == null) emptyList() else teams.filter { self.c(it) }
            return MatchPerspective(
                perspective?.mode ?: RolloutPerspective.MODE_INDIVIDUAL,
                slot, self, player, allies, enemies,
            )
        }
    }
}

/**
 * Decides whether the match is over, in the perspective the spec asked for.
 *
 * `MissionEngine` ends a skirmish through `GameUI.startGameEndSequence()` / `endGameSequence()`, which
 * latch `hasWonGame` / `hasLostGame` for the player team only. Those flags are used when the
 * perspective is that same team and the mode is `individual`; otherwise the team flags below decide.
 */
internal object EngineOutcome {
    fun evaluate(engine: GameEngine, perspective: RolloutPerspective?): Outcome {
        val view = MatchPerspective.of(engine, perspective)
        val self = view.selfTeam ?: return Outcome.ACTIVE
        if (!view.teamMode) {
            if (view.isPlayerTeam && !engine.isContinuingAfterGameEnd) {
                if (engine.hasWonGame) return Outcome.VICTORY
                if (engine.hasLostGame) return Outcome.DEFEAT
            }
            if (isOut(self)) return Outcome.DEFEAT
        } else if (view.allies.isNotEmpty() && view.allies.all { isOut(it) }) {
            return Outcome.DEFEAT
        }
        if (view.enemies.isEmpty()) return Outcome.ACTIVE
        return if (view.enemies.all { isOut(it) }) Outcome.VICTORY else Outcome.ACTIVE
    }

    private fun isOut(team: PlayerTeam): Boolean =
        team.isTeamVictory || team.isTeamDefeated || team.isTeamDefeatedTech || team.isTeamWipedOut ||
            team.getUnitCount(true, false) <= 0
}

internal fun BaseUnit.isLiveCommandCenterObjective(): Boolean =
    this is OrderableUnit && !isDead && !isExcludedFromDefeatCheck() && (this is CommandCenter || isTargetable)

/** Keep one live objective per side. Rescan only when that objective is gone or changes sides. */
internal class TeamCommandCenterOutcome(private val view: MatchPerspective) {
    private var alliedCenter: BaseUnit? = null
    private var enemyCenter: BaseUnit? = null

    fun evaluate(): Outcome {
        if (view.allies.isEmpty() || view.enemies.isEmpty()) return Outcome.ACTIVE
        if (!isHeldBy(alliedCenter, view.allies)) {
            alliedCenter = findCenter(view.allies) ?: return Outcome.DEFEAT
        }
        if (!isHeldBy(enemyCenter, view.enemies)) {
            enemyCenter = findCenter(view.enemies) ?: return Outcome.VICTORY
        }
        return Outcome.ACTIVE
    }

    private fun isHeldBy(unit: BaseUnit?, teams: List<PlayerTeam>): Boolean =
        unit != null && unit.team in teams && unit.isLiveCommandCenterObjective()

    private fun findCenter(teams: List<PlayerTeam>): BaseUnit? {
        val live = BaseUnit.bE.a()
        for (index in 0 until BaseUnit.bE.size) {
            val unit = live[index]
            if (isHeldBy(unit, teams)) return unit
        }
        return null
    }
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
            if (spec.sampling?.includeUnitTypes == true) {
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
                // 收入也放进采样：奖励里的“经济差距”要双方各自的收入
                "income" to team.getScaledIncomeRate(),
                "incomePerSecond" to com.corrodinggames.rts.game.ai.custom.rwx_cli_tool.RwxIncomeRate
                    .perSecond(team, engine),
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
        sampleCount: Int,
        replay: String?,
    ): Map<String, Any?> {
        val buildingCosts = HashMap<Int, Long>()
        val commandCenters = HashMap<Int, Int>()
        val liveUnits = BaseUnit.bE.a()
        for (index in 0 until BaseUnit.bE.size) {
            val unit = liveUnits[index]
            val team = unit.team ?: continue
            if (unit.isLiveCommandCenterObjective()) commandCenters.merge(team.teamId, 1, Int::plus)
            if (!unit.isAlive() || !unit.bI() || !unit.isIncludedInUnitValue()) continue
            val cost = unit.buildPrice.b().toLong() + (unit.r().B()?.b() ?: 0)
            buildingCosts.merge(team.teamId, cost, Long::plus)
        }
        PlayerTeam.refreshTeamInstances()
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
                    "commandCenters" to (commandCenters[team.teamId] ?: 0),
                    "credits" to round(team.credits),
                    "incomePerSecond" to RwxIncomeRate.perSecond(team, engine),
                    "buildingCost" to (buildingCosts[team.teamId] ?: 0L),
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
        val view = MatchPerspective.of(engine, spec.perspective)
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
            // 结果视角：mode/slot 是请求值，teamId/allies/enemies 是引擎里实际解析出来的队伍，
            // 胜负一律按这个视角读，避免再在 harness 里二次推断。
            "perspective" to linkedMapOf<String, Any?>(
                "mode" to view.mode,
                "slot" to view.slot,
                "teamId" to view.selfTeam?.teamId,
                "allies" to view.allies.map { it.teamId },
                "enemies" to view.enemies.map { it.teamId },
            ),
            "outcome" to outcome.wire,
            "decisive" to (outcome == Outcome.VICTORY || outcome == Outcome.DEFEAT),
            "winnerTeam" to if (outcome == Outcome.VICTORY) view.selfTeam?.teamId else null,
            "ticks" to ticks,
            "gameMs" to engine.gameTimeMillis,
            "wallMs" to wallMs,
            "ticksPerSecond" to if (wallMs > 0) round(ticks * 1000.0 / wallMs) else null,
            "replay" to replay,
            "samples" to spec.sampling?.let { sampling ->
                linkedMapOf("file" to "samples.jsonl", "count" to sampleCount, "everyTicks" to sampling.everyTicks)
            },
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
