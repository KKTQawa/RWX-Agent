package io.github.rwx.headless.rollout

import com.corrodinggames.rts.game.PlayerTeam
import com.corrodinggames.rts.game.ai.AIController
import com.corrodinggames.rts.game.units.BaseUnit
import com.corrodinggames.rts.gameFramework.GameEngine
import com.corrodinggames.rts.gameFramework.ReplayEngine
import com.corrodinggames.rts.gameFramework.mission.RwxWinCondition
import com.corrodinggames.rts.gameFramework.network.GameRoomSettings
import io.github.rwx.CrashReporter
import io.github.rwx.DesktopFontMetrics
import io.github.rwx.FileCrashReporter
import io.github.rwx.PlatformStorage
import io.github.rwx.app.AppOptions
import io.github.rwx.app.MicroJson
import io.github.rwx.di.coreModule
import io.github.rwx.di.desktopModule
import io.github.rwx.headless.HeadlessGameSession
import io.github.rwx.i18n.LocaleSettings
import io.github.rwx.logger
import io.github.rwx.render.canvas.GameFontMetrics
import io.github.rwx.render.frame.GameViewport
import io.github.rwx.session.BattleRoomCoreConfig
import io.github.rwx.session.BattleRoomLaunchConfig
import org.koin.core.context.GlobalContext
import org.koin.dsl.module
import java.io.BufferedWriter
import java.nio.file.Files
import java.nio.file.Path
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

/**
 * Runs one fully AI-vs-AI skirmish as fast as the CPU allows and writes its materials.
 *
 * This is the training-step entry point, not an evaluation entry point:
 *
 *  - the match is configured from a JSON spec ([RolloutSpec]), normally every side driven by a
 *    registered AI definition (slot 0 is the measured side);
 *  - ticks advance by calling the engine's own frame entry (`gameLoop(1f, 16)`) without any pacing,
 *    so the simulation is exactly the same one a realtime match runs at 1x;
 *  - the replay is armed before the first tick and closed through the engine's normal shutdown path,
 *    which keeps it playable and checksum-consistent;
 *  - per-team state is sampled by game tick (not wall clock) into `samples.jsonl`, and the outcome and
 *    final state land in `result.json`.
 *
 * The process exits after one match because the legacy engine allows one game session per OS process.
 */
internal object HeadlessRollout {
    private const val MIN_LOAD_WAIT_MILLIS = 180_000L
    private const val MAX_REPLAY_WALL_SECONDS = 900L
    private val timestamp = DateTimeFormatter.ofPattern("yyyyMMdd-HHmmss").withZone(ZoneId.systemDefault())

    @JvmStatic
    fun run(options: AppOptions) {
        val startedAt = Instant.now()
        val replayCheck = options.replayCheck?.let { Path.of(it).toAbsolutePath().normalize() }
        val spec = if (replayCheck == null) {
            val specFile = requireNotNull(options.rolloutConfig) { "--rollout-config requires a file path" }
            try {
                val raw = MicroJson.read(Path.of(specFile))
                // The AI config path must be in place before the AI registry is initialized: parsing
                // the teams resolves AI ids through AiRegistry, and that builds every definition.
                (raw["aiConfig"] as? String)?.trim()?.takeIf { it.isNotEmpty() }?.let { path ->
                    val resolved = Path.of(path).let {
                        if (it.isAbsolute) it else Path.of("").toAbsolutePath().resolve(it)
                    }
                    System.setProperty(
                        com.corrodinggames.rts.game.ai.custom.rl.AiRlConfig.PROPERTY,
                        resolved.normalize().toString(),
                    )
                }
                RolloutSpec.parse(raw)
            } catch (error: Throwable) {
                // A bad spec is a launcher mistake: report it on stdout and fail before touching the engine.
                println("RWX_ROLLOUT_ERROR config=${error.message}")
                kotlin.system.exitProcess(1)
            }
        } else null


        System.setProperty("java.awt.headless", "true")
        System.setProperty("launch.dir", (spec?.outputDirectory ?: replayCheck?.parent)?.toString())
        GameEngine.isHeadlessMode = true
        GameEngine.isMenuBackgroundDisabled = true
        GameEngine.isNonAndroidVersion = true
        GameEngine.isDesktopInitialized = true
        GameEngine.isJavaDesktopVersion = true
        GameEngine.isPCOrIOSVersion = true
        spec?.let { RwxWinCondition.install(it.winCondition); Files.createDirectories(it.outputDirectory) }

        val app = GlobalContext.startKoin { modules(coreModule, desktopModule, module { single { options } }) }
        var exitCode = 1
        try {
            val storage = app.koin.get<PlatformStorage>()
            storage.createDirectories()
            (app.koin.get<CrashReporter>() as? FileCrashReporter)?.installAsDefaultUncaughtExceptionHandler()
            GameFontMetrics.install(DesktopFontMetrics(storage))
            LocaleSettings.initialize()
            exitCode = if (spec != null) {
                runMatch(app.koin.get(), spec, startedAt)
            } else {
                verifyReplay(app.koin.get(), requireNotNull(replayCheck))
            }
        } catch (error: Throwable) {
            logger.error(error) { "Rollout failed" }
            println("RWX_ROLLOUT_ERROR ${error.message ?: error.javaClass.simpleName}")
        } finally {
            runCatching { GlobalContext.stopKoin() }
        }
        kotlin.system.exitProcess(exitCode)
    }

    /**
     * Plays a recorded rollout back at maximum speed and reports whether the engine's own per-tick
     * checksums still match. This is the gate a training loop needs before trusting a fast recording:
     * the replay is only evidence when playback agrees with the live simulation.
     */
    private fun verifyReplay(session: HeadlessGameSession, replay: Path): Int {
        check(Files.isRegularFile(replay)) { "Replay not found: $replay" }
        // The engine resolves a replay name as "replays/<name>" against the process working
        // directory, so an absolute path is not accepted. Run from the rollout directory when
        // possible; otherwise stage a copy under the working directory and never touch the original.
        val cwd = Path.of("").toAbsolutePath().normalize()
        val name = replay.fileName.toString()
        val staged = if (replay.parent?.fileName?.toString() == "replays" && replay.parent?.parent == cwd) {
            replay
        } else {
            val target = cwd.resolve("replays").resolve(name)
            Files.createDirectories(target.parent)
            if (target.toAbsolutePath().normalize() != replay) {
                Files.copy(replay, target, java.nio.file.StandardCopyOption.REPLACE_EXISTING)
            }
            target
        }
        val viewport = GameViewport(640, 480)
        session.use { active ->
            active.preload(viewport)
            active.prepareReplayAsync(staged.fileName.toString(), viewport)
            val loadDeadline = System.nanoTime() + 120_000_000_000L
            while (!active.isEngineGameLoaded()) {
                check(System.nanoTime() < loadDeadline) { "Replay did not load: $replay" }
                active.mapLoadError()?.let { throw IllegalStateException("Unable to load replay", it) }
                Thread.sleep(2)
            }
            val engine = GameEngine.getInstance()
            val replayEngine = engine.replayEngine
            val playbackDeadline = System.nanoTime() + MAX_REPLAY_WALL_SECONDS * 1_000_000_000L
            val playbackStart = System.nanoTime()
            var ticks = 0
            // The engine keeps the world running after the recording's end block, so stop on the
            // explicit flag (or on the tick ceiling) rather than on isReplaying().
            while (replayEngine.isReplaying() && !replayEngine.playbackFinished) {
                check(System.nanoTime() < playbackDeadline) { "Replay playback did not finish" }
                active.step()
                ticks++
            }
            val desyncs = replayEngine.desyncCount
            val finished = replayEngine.playbackFinished
            val report = linkedMapOf<String, Any?>(
                "schema" to "rwx-replay-check/1",
                "replay" to replay.toString(),
                "ticks" to ticks,
                "desyncs" to desyncs,
                "finished" to finished,
                "consistent" to (desyncs == 0 && ticks > 0 && finished),
                "frames" to engine.currentTick,
                "gameMs" to engine.gameTimeMillis,
                "wallMs" to (System.nanoTime() - playbackStart) / 1_000_000,
            )
            Files.writeString(
                replay.resolveSibling(replay.fileName.toString() + ".check.json"),
                MicroJson.encode(report),
            )
            println(
                "RWX_REPLAY_CHECK replay=${replay.fileName} consistent=${report["consistent"]} " +
                    "desyncs=$desyncs ticks=$ticks finished=$finished frames=${engine.currentTick}",
            )
            return if (report["consistent"] == true) 0 else 4
        }
    }

    private fun runMatch(
        session: HeadlessGameSession,
        spec: RolloutSpec,
        startedAt: Instant,
    ): Int {
        val viewport = GameViewport(640, 480)
        val roomSettings = GameRoomSettings().also { settings ->
            settings.mapPath = spec.mapPath
            settings.incomeMultiplier = spec.room.incomeMultiplier
            settings.startingCredits = spec.room.startingCredits
            settings.fogMode = spec.room.fogMode
            settings.revealedMap = spec.room.revealedMap
            settings.startingUnits = spec.room.startingUnits
            settings.noNukes = spec.room.noNukes
            settings.aiDifficulty = spec.room.aiDifficulty
            if (spec.room.seed != 0) settings.randomSeed = spec.room.seed
        }
        val launch = BattleRoomLaunchConfig(
            sandbox = false,
            aiPlayerCount = spec.aiPlayerCount,
            teamLayout = null,
            room = BattleRoomCoreConfig(spec.mapPath, roomSettings),
            aiCodesBySlot = spec.aiCodesBySlot,
        )

        session.use { active ->
            active.preload(viewport)
            // A local battle room is staged, not loaded on an IO thread: only the synchronous
            // pending-map path applies the room (configureLocalBattleRoom + startBattleRoomGame), so
            // the AI codes, income and credits below are the ones the match actually runs with.
            check(active.prepareLocalBattleRoom(launch)) { "Unable to stage the rollout battle room" }
            val engine = awaitLoaded(active, spec)
            val network = engine.networkEngine
            println(
                "RWX_ROLLOUT_READY map=${engine.getCurrentMapName()} " +
                    "tick=${engine.currentTick} teams=${describeTeams()} " +
                    "roomServer=${network.singleplayerServer} roomActive=${network.networkGameActive} " +
                    "income=${network.roomSettings.incomeMultiplier} " +
                    "mapMatch=${network.selectedMapPath == spec.mapPath}",
            )

            val samples = SampleWriter(spec)
            val replay = if (spec.recordReplay) startReplay(engine, spec) else null
            val loopStartNanos = System.nanoTime()
            var ticks = 0
            var outcome = Outcome.ACTIVE
            while (true) {
                if (ticks % spec.sampling.everyTicks == 0) samples.write(engine, ticks)
                outcome = EngineOutcome.evaluate(engine)
                if (outcome != Outcome.ACTIVE) break
                if (ticks >= spec.limits.maxTicks) break
                val wallSeconds = (System.nanoTime() - loopStartNanos) / 1_000_000_000.0
                if (wallSeconds >= spec.limits.maxWallSeconds) {
                    outcome = Outcome.WALL_LIMIT
                    break
                }
                active.step()
                ticks++
            }
            samples.write(engine, ticks)
            val wallMs = (System.nanoTime() - loopStartNanos) / 1_000_000
            if (outcome == Outcome.ACTIVE) outcome = Outcome.MAX_TICKS
            val replayPath = finishReplay(engine, replay)
            samples.close()
            val result = ResultWriter.write(
                spec, engine, startedAt, outcome, ticks, wallMs, samples, replayPath,
            )
            println(
                "RWX_ROLLOUT_DONE outcome=${result["outcome"]} ticks=$ticks " +
                    "gameMs=${engine.gameTimeMillis} wallMs=$wallMs samples=${samples.count} " +
                    "replay=${replayPath ?: "-"}",
            )
            return if (outcome == Outcome.MAX_TICKS || outcome == Outcome.WALL_LIMIT) 3 else 0
        }
    }

    private fun awaitLoaded(session: HeadlessGameSession, spec: RolloutSpec): GameEngine {
        val deadline = System.nanoTime() + MIN_LOAD_WAIT_MILLIS * 1_000_000
        while (true) {
            check(System.nanoTime() < deadline) { "Rollout battle room did not load a level" }
            session.mapLoadError()?.let { throw IllegalStateException("Unable to load rollout map", it) }
            if (session.isEngineGameLoaded()) break
            // Delta 0 loads the staged map without advancing the simulation.
            session.loadPendingMapNow()
            if (!session.isEngineGameLoaded()) Thread.sleep(2)
        }
        val engine = GameEngine.getInstance()
        val network = engine.networkEngine
        check(network.singleplayerServer && network.selectedMapPath == spec.mapPath) {
            "Battle room was not applied: server=${network.singleplayerServer} " +
                "map=${network.selectedMapPath}"
        }
        check(network.roomSettings.incomeMultiplier == spec.room.incomeMultiplier) {
            "Battle room income was not applied: ${network.roomSettings.incomeMultiplier}"
        }
        // The AI code is the whole point of the spec: fail loudly instead of silently running the
        // room's default difficulty for a slot the launcher asked to be a specific AI.
        for (team in spec.teams) {
            val actual = PlayerTeam.k(team.slot)
            check(actual != null && actual.teamAIDifficultyOverride == team.aiCode) {
                "Slot ${team.slot} is not running AI ${team.aiCode}: " +
                    "found ${actual?.teamAIDifficultyOverride}"
            }
        }
        return engine
    }

    private fun describeTeams(): String {
        PlayerTeam.refreshTeamInstances()
        return PlayerTeam.getTeamInstances()
            .filter { it.teamId in 0 until PlayerTeam.TEAM_NEUTRAL }
            .joinToString(",") { "${it.teamId}:${it.teamName}" }
    }

    private fun startReplay(engine: GameEngine, spec: RolloutSpec): Path {
        val name = "rollout-" + timestamp.format(Instant.now()) + ".replay"
        val replayEngine: ReplayEngine = engine.replayEngine
        replayEngine.d(name)
        check(replayEngine.isRecording()) { "Replay recording did not start" }
        println("RWX_ROLLOUT_RECORD replay=$name")
        return spec.outputDirectory.resolve("replays").resolve(name)
    }

    private fun finishReplay(engine: GameEngine, replay: Path?): String? {
        if (replay == null) return null
        val reported = engine.replayEngine.replayFilePath
        // The normal close path flushes every buffered frame, writes the end block and joins the
        // writer thread; killing the process instead would leave a truncated, unplayable file.
        engine.replayEngine.e()
        val name = replay.fileName.toString()
        val launch = Path.of(System.getProperty("launch.dir", ".")).toAbsolutePath().normalize()
        val source = listOf(
            replay,
            Path.of(reported ?: name).let { if (it.isAbsolute) it else launch.resolve(it) },
            launch.resolve(name),
            launch.resolve("replays").resolve(name),
        ).map { it.toAbsolutePath().normalize() }.firstOrNull { Files.isRegularFile(it) }
            ?: return null
        Files.createDirectories(replay.parent)
        if (source != replay.toAbsolutePath().normalize()) {
            Files.move(source, replay, java.nio.file.StandardCopyOption.REPLACE_EXISTING)
        }
        return replay.toAbsolutePath().normalize().toString()
    }
}
