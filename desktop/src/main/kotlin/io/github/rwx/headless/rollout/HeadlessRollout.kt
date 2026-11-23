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
        kotlin.system.exitProcess(runOnce(options))
    }

    /** 跑一局并返回退出码，不结束进程；供 --rollout-loop 复用同一个 JVM。 */
    @JvmStatic
    fun runOnce(options: AppOptions): Int {
        val startedAt = Instant.now()
        val replayCheck = options.replayCheck?.let { Path.of(it).toAbsolutePath().normalize() }
        if (replayCheck != null) {
            // 与录制时同源的 AI 配置（<replay>.ai.json）存在就先装上，保证定义参数一致。
            // -Drwx.replay.skipAiConfigPreload=true 跳过这一步，用来验证“播放端自己发现 sidecar”的路径
            // （GUI 走的就是这条：没有人在启动前装配置）。
            val sidecar = Path.of(replayCheck.toString() + ".ai.json")
            if (Files.isRegularFile(sidecar) && !java.lang.Boolean.getBoolean("rwx.replay.skipAiConfigPreload")) {
                System.setProperty(
                    com.corrodinggames.rts.game.ai.custom.rl.AiRlConfig.PROPERTY,
                    sidecar.toAbsolutePath().normalize().toString(),
                )
                println("RWX_REPLAY_AI_CONFIG ${sidecar.fileName}")
            }
        }
        val spec = if (replayCheck == null) {
            val specFile = requireNotNull(options.rolloutConfig) { "--rollout-config requires a file path" }
            try {
                val raw = MicroJson.read(Path.of(specFile))
                // The AI config path must be in place before the AI registry is initialized: parsing
                // the teams resolves AI ids through AiRegistry, and that builds every definition.
                for ((key, property) in listOf(
                    "aiConfig" to com.corrodinggames.rts.game.ai.custom.rl.AiRlConfig.PROPERTY,
                    "aiConfig2" to com.corrodinggames.rts.game.ai.custom.rl.AiRlConfig.PROPERTY2,
                )) {
                    (raw[key] as? String)?.trim()?.takeIf { it.isNotEmpty() }?.let { path ->
                        val resolved = Path.of(path).let {
                            if (it.isAbsolute) it else Path.of("").toAbsolutePath().resolve(it)
                        }
                        System.setProperty(property, resolved.normalize().toString())
                    }
                }
                RolloutSpec.parse(raw)
            } catch (error: Throwable) {
                // A bad spec is a launcher mistake: report it on stdout and fail before touching the engine.
                println("RWX_ROLLOUT_ERROR config=${error.message}")
                kotlin.system.exitProcess(1)
            }
        } else null


        System.setProperty("java.awt.headless", "true")
        // 回放校验不要拿 replayCheck.parent 当 launch.dir：平台会把 preferences/saves/mods 写进这个目录，
        // 回放放在 replays/ 时就会在 replays/ 里长出一套用户目录。用当前工作目录，与手动跑回放一致。
        System.setProperty(
            "launch.dir",
            (spec?.outputDirectory ?: Path.of("").toAbsolutePath().normalize()).toString(),
        )
        GameEngine.isHeadlessMode = true
        GameEngine.isMenuBackgroundDisabled = true
        GameEngine.isNonAndroidVersion = true
        GameEngine.isDesktopInitialized = true
        GameEngine.isJavaDesktopVersion = true
        GameEngine.isPCOrIOSVersion = true
        spec?.let { RwxWinCondition.install(it.winCondition); Files.createDirectories(it.outputDirectory) }
        CURRENT_AI_CONFIG = spec?.aiConfig

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
        return exitCode
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
            settings.mapPath = portableMapPath(spec.mapPath)
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
            spawnBySlot = spec.spawnBySlot,
            sideBySlot = spec.sideBySlot,
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

            if (spec.telemetry) {
                // EngineEvidence is already called by GameLogic every tick; it only needs the property.
                System.setProperty("rwx.evaluate.dir", spec.outputDirectory.resolve("events-live").toString())
                println("RWX_ROLLOUT_TELEMETRY dir=" + spec.outputDirectory.resolve("events-live"))
            }
            val samples = spec.sampling?.let { SampleWriter(spec) }
            val replay = if (spec.recordReplay) startReplay(engine, spec) else null
            val loopStartNanos = System.nanoTime()
            var ticks = 0
            var outcome = Outcome.ACTIVE
            while (true) {
                val sampler = spec.sampling
                if (sampler != null && samples != null && ticks % sampler.everyTicks == 0) samples.write(engine, ticks)
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
            samples?.write(engine, ticks)
            val wallMs = (System.nanoTime() - loopStartNanos) / 1_000_000
            if (outcome == Outcome.ACTIVE) outcome = Outcome.MAX_TICKS
            val replayPath = finishReplay(engine, replay)
            samples?.close()
            val result = ResultWriter.write(
                spec, engine, startedAt, outcome, ticks, wallMs, samples?.count ?: 0, replayPath,
            )
            println(
                "RWX_ROLLOUT_DONE outcome=${result["outcome"]} ticks=$ticks " +
                    "gameMs=${engine.gameTimeMillis} wallMs=$wallMs samples=${samples?.count ?: 0} " +
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
            // With an explicit spawn the team lives at that spawn slot, not at its logical side index.
            val physicalSlot = team.spawn?.minus(1) ?: team.slot
            val actual = PlayerTeam.k(physicalSlot)
            check(actual != null && actual.teamAIDifficultyOverride == team.aiCode) {
                "Slot ${team.slot} (spawn $physicalSlot) is not running AI ${team.aiCode}: " +
                    "found ${actual?.teamAIDifficultyOverride}"
            }
        }
        return engine
    }

    /**
     * 回放里存的是房间设置里的地图路径；如果写成绝对路径（/data/aqf/... 或 X:\...），
     * 换一台机器就再也打不开。仓库内的地图一律用相对仓库根的路径（和原版资产的写法一致，
     * 例如 assets/maps/skirmish/xxx.tmx），回放才能跨机器复现。
     */
    private fun portableMapPath(absolute: String): String {
        return runCatching {
            val repo = Path.of(System.getProperty("rwx.repoDir", ".")).toAbsolutePath().normalize()
            val map = Path.of(absolute).toAbsolutePath().normalize()
            if (map.startsWith(repo)) repo.relativize(map).toString().replace('\\', '/') else absolute
        }.getOrDefault(absolute)
    }

    private fun describeTeams(): String {
        PlayerTeam.refreshTeamInstances()
        return PlayerTeam.getTeamInstances()
            .filter { it.teamId in 0 until PlayerTeam.TEAM_NEUTRAL }
            .joinToString(",") { "${it.teamId}:${it.teamName}" }
    }

    /** 本次 rollout 的 AI 配置路径；录回放时用它写 `<replay>.ai.json`。 */
    private var CURRENT_AI_CONFIG: String? = null

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
        // 引擎把回放写在进程工作目录的 replays/ 下（launch.dir 不参与这条路径），
        // 所以列表里必须带上 user.dir/replays；否则回放会留在仓库根、result.json 里显示 replay=-。
        val cwd = Path.of(System.getProperty("user.dir", ".")).toAbsolutePath().normalize()
        val source = listOf(
            replay,
            Path.of(reported ?: name).let { if (it.isAbsolute) it else launch.resolve(it) },
            cwd.resolve("replays").resolve(name),
            cwd.resolve(name),
            launch.resolve(name),
            launch.resolve("replays").resolve(name),
        ).map { it.toAbsolutePath().normalize() }.firstOrNull { Files.isRegularFile(it) }
            ?: return null
        Files.createDirectories(replay.parent)
        if (source != replay.toAbsolutePath().normalize()) {
            Files.move(source, replay, java.nio.file.StandardCopyOption.REPLACE_EXISTING)
        }
        // 自定义 AI（rwx.ai-rl-hard）的收入倍率等定义参数不写进回放本体；把同一份配置存在
        // <replay>.ai.json，回放校验/播放时据此重建定义，否则收入差会让逐帧校验和一直漂移。
        CURRENT_AI_CONFIG?.let { cfg ->
            runCatching {
                val from = Path.of(cfg)
                if (Files.isRegularFile(from)) {
                    Files.copy(from, Path.of(replay.toString() + ".ai.json"),
                        java.nio.file.StandardCopyOption.REPLACE_EXISTING)
                }
            }.onFailure { println("RWX_ROLLOUT_RECORD_AI_CONFIG failed=" + it.message) }
        }
        return replay.toAbsolutePath().normalize().toString()
    }
}
