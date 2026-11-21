package io.github.rwx.headless.rollout

import io.github.rwx.app.AppOptions
import java.nio.file.Files
import java.nio.file.Path

/**
 * 实验性常驻模式：同一个 JVM 里连续跑多局，省掉每局的 JVM 启动与引擎预热。
 *
 * 用法：`--rollout-loop=<目录>`，目录里放若干 `<name>.json` 规格文件；
 * 进程按文件名顺序逐局执行，发现 `stop` 文件后跑完剩余任务退出。
 * 每局仍会重新初始化引擎与 Koin —— 引擎是否允许同进程多局，由这一模式来验证。
 */
object RolloutLoop {
    @JvmStatic
    fun run(dirPath: String, base: AppOptions) {
        val dir = Path.of(dirPath).toAbsolutePath().normalize()
        Files.createDirectories(dir)
        val finished = mutableSetOf<String>()
        println("RWX_LOOP_START dir=$dir")
        while (true) {
            val stop = Files.exists(dir.resolve("stop"))
            val pending = Files.list(dir).use { stream ->
                stream.filter { it.fileName.toString().endsWith(".json") }
                    .sorted()
                    .toList()
            }.firstOrNull { it.fileName.toString() !in finished }
            if (pending == null) {
                if (stop) break
                Thread.sleep(500)
                continue
            }
            finished += pending.fileName.toString()
            println("RWX_LOOP_JOB ${pending.fileName}")
            val code = try {
                HeadlessRollout.runOnce(base.copy(rolloutConfig = pending.toString()))
            } catch (error: Throwable) {
                println("RWX_LOOP_ERROR ${pending.fileName} ${error.message}")
                1
            }
            println("RWX_LOOP_DONE ${pending.fileName} rc=$code")
        }
        println("RWX_LOOP_EXIT jobs=${finished.size}")
        kotlin.system.exitProcess(0)
    }
}
