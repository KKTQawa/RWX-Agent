package io.github.rwx.headless.rollout

import com.corrodinggames.rts.game.ai.strategy.AiRegistry

/**
 * One rollout request, read from the JSON file passed to `--rollout-config`.
 *
 * Everything here is run-level input: the map, the two AI codes, the room rules and the limits. The
 * launcher (an RL harness, a batch script or a human) owns this file and reads [RolloutResult]; the
 * runner never guesses defaults from the user's settings, so two rollouts with the same spec are the
 * same match.
 */
internal data class RolloutSpec(
    val mapPath: String,
    val outputDirectory: java.nio.file.Path,
    val teams: List<RolloutTeam>,
    val room: RolloutRoom,
    val limits: RolloutLimits,
    val sampling: RolloutSampling,
    val recordReplay: Boolean,
    val winCondition: String,
    /** Config file of the configurable AI preset (`rwx.ai-rl-hard`); null keeps its default. */
    val aiConfig: String?,
) {
    init {
        require(mapPath.isNotBlank()) { "map must not be blank" }
        require(teams.size >= 2) { "teams must contain at least two entries" }
        require(teams.map { it.slot }.toSet().size == teams.size) { "team slots must be unique" }
        require(teams.any { it.slot == 0 }) { "teams must define slot 0 (the measured side)" }
        require(limits.maxTicks > 0) { "limits.maxTicks must be positive" }
        require(sampling.everyTicks > 0) { "sampling.everyTicks must be positive" }
    }

    /** Highest slot defines how many AI players the room has to create. */
    val aiPlayerCount: Int get() = teams.maxOf { it.slot }

    val aiCodesBySlot: Map<Int, Int> get() = teams.associate { it.slot to it.aiCode }

    companion object {
        fun parse(raw: Map<String, Any?>): RolloutSpec {
            val schema = raw["schema"] as? String
            require(schema == null || schema == SCHEMA) {
                "Unsupported rollout schema '$schema'; expected $SCHEMA"
            }
            val output = pathOf(requireString(raw, "out"))
            val map = resolveMap(requireString(raw, "map"), output)
            val teams = parseTeams(raw["teams"])
            val room = parseRoom(raw["room"] as? Map<*, *>)
            val limits = parseLimits(raw["limits"] as? Map<*, *>)
            val sampling = parseSampling(raw["sampling"] as? Map<*, *>)
            val record = (raw["record"] as? Boolean) ?: true
            val winCondition = com.corrodinggames.rts.gameFramework.mission.RwxWinCondition.parse(
                raw["winCondition"] as? String,
            )
            val aiConfig = (raw["aiConfig"] as? String)?.trim()?.takeIf { it.isNotEmpty() }
            return RolloutSpec(map, output, teams, room, limits, sampling, record, winCondition, aiConfig)
        }

        private const val SCHEMA = "rwx-rollout-v1"

        /** Same lookup order as the CLI: numeric code, then the stable registry id. */
        fun resolveAi(value: Any?): AiResolution {
            val text = when (value) {
                null -> throw IllegalArgumentException("teams[].ai is required")
                is Number -> value.toInt().toString()
                else -> value.toString().trim()
            }
            require(text.isNotEmpty()) { "teams[].ai must not be blank" }
            text.toIntOrNull()?.let { code ->
                val definition = AiRegistry.find(code)
                return if (definition == null) {
                    // Unknown numeric codes keep the engine's legacy difficulty behaviour, but say so.
                    AiResolution(code, null, "code:$code")
                } else {
                    AiResolution(code, definition.originalDifficulty(), definition.id())
                }
            }
            val byId = AiRegistry.find(text)
                ?: throw IllegalArgumentException(
                    "Unknown AI '$text'. Known ids: " +
                        AiRegistry.definitions().joinToString(", ") { it.id() },
                )
            return AiResolution(byId.code(), byId.originalDifficulty(), byId.id())
        }

        private fun parseTeams(value: Any?): List<RolloutTeam> {
            val rows = value as? List<*>
                ?: throw IllegalArgumentException("teams must be an array")
            return rows.mapIndexed { index, row ->
                val entry = row as? Map<*, *>
                    ?: throw IllegalArgumentException("teams[$index] must be an object")
                val slot = (entry["slot"] as? Number)?.toInt() ?: index
                require(slot in 0..9) { "teams[$index].slot must be 0..9" }
                val ai = resolveAi(entry["ai"])
                RolloutTeam(
                    slot = slot,
                    aiCode = ai.code,
                    aiId = ai.id,
                    name = (entry["name"] as? String)?.trim()?.takeIf { it.isNotEmpty() }
                        ?: "AI ${ai.label}",
                )
            }
        }

        private fun parseRoom(raw: Map<*, *>?): RolloutRoom {
            val room = RolloutRoom()
            if (raw == null) return room
            return RolloutRoom(
                incomeMultiplier = (raw["incomeMultiplier"] as? Number)?.toFloat() ?: room.incomeMultiplier,
                startingCredits = (raw["startingCredits"] as? Number)?.toInt() ?: room.startingCredits,
                fogMode = (raw["fogMode"] as? Number)?.toInt() ?: room.fogMode,
                revealedMap = (raw["revealedMap"] as? Boolean) ?: room.revealedMap,
                startingUnits = (raw["startingUnits"] as? Number)?.toInt() ?: room.startingUnits,
                noNukes = (raw["noNukes"] as? Boolean) ?: room.noNukes,
                seed = (raw["seed"] as? Number)?.toInt() ?: room.seed,
                aiDifficulty = (raw["aiDifficulty"] as? Number)?.toInt() ?: room.aiDifficulty,
            ).also {
                require(it.incomeMultiplier > 0f && it.incomeMultiplier.isFinite()) {
                    "room.incomeMultiplier must be positive"
                }
                require(it.fogMode in 0..2) { "room.fogMode must be 0..2" }
            }
        }

        private fun parseLimits(raw: Map<*, *>?): RolloutLimits {
            val limits = RolloutLimits()
            if (raw == null) return limits
            return RolloutLimits(
                maxTicks = (raw["maxTicks"] as? Number)?.toInt() ?: limits.maxTicks,
                maxWallSeconds = (raw["maxWallSeconds"] as? Number)?.toInt() ?: limits.maxWallSeconds,
            )
        }

        private fun parseSampling(raw: Map<*, *>?): RolloutSampling {
            val sampling = RolloutSampling()
            if (raw == null) return sampling
            return RolloutSampling(
                everyTicks = (raw["everyTicks"] as? Number)?.toInt() ?: sampling.everyTicks,
                includeUnitTypes = (raw["includeUnitTypes"] as? Boolean) ?: sampling.includeUnitTypes,
            )
        }

        private fun requireString(raw: Map<String, Any?>, key: String): String {
            val value = (raw[key] as? String)?.trim()
            require(!value.isNullOrEmpty()) { "$key is required" }
            return value
        }

        private fun pathOf(value: String): java.nio.file.Path =
            java.nio.file.Path.of(value).toAbsolutePath().normalize()

        /** A relative map is resolved against the working directory first, then the output directory. */
        private fun resolveMap(value: String, output: java.nio.file.Path): String {
            val direct = java.nio.file.Path.of(value)
            if (direct.isAbsolute) return direct.normalize().toString()
            val fromCwd = direct.toAbsolutePath().normalize()
            if (java.nio.file.Files.exists(fromCwd)) return fromCwd.toString()
            val fromOutput = output.resolve(direct).normalize()
            if (java.nio.file.Files.exists(fromOutput)) return fromOutput.toString()
            return fromCwd.toString()
        }
    }
}

/** One commanded side of the match; [aiCode] is what the engine resolves through [AiRegistry]. */
internal data class RolloutTeam(
    val slot: Int,
    val aiCode: Int,
    val aiId: String?,
    val name: String,
)

internal data class RolloutRoom(
    val incomeMultiplier: Float = 1f,
    val startingCredits: Int = 0,
    val fogMode: Int = 2,
    val revealedMap: Boolean = false,
    val startingUnits: Int = 1,
    val noNukes: Boolean = false,
    val seed: Int = 0,
    val aiDifficulty: Int = 1,
)

internal data class RolloutLimits(
    val maxTicks: Int = 36_000,
    val maxWallSeconds: Int = 180,
)

internal data class RolloutSampling(
    val everyTicks: Int = 60,
    val includeUnitTypes: Boolean = true,
)

internal data class AiResolution(val code: Int, val originalDifficulty: Int?, val id: String?) {
    val label: String get() = id ?: "#$code"
}
