package com.corrodinggames.rts.game.ai.custom.rl;

import com.corrodinggames.rts.gameFramework.GameEngine;
import io.github.rwx.app.MicroJson;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;

/**
 * 播放回放时补回自定义 AI 的定义级收入倍率。
 *
 * <p>回放本体会记录 AI 的稳定 id（{@code rwx.ai-rl-hard}），但不会记录 AI 定义上的
 * {@code incomeMultiplier}：收入是“房间倍率 × AI 定义倍率”，播放端只能按默认定义去补。
 * 补错就会让录制下来的建造命令因为差钱而失败，逐帧校验和随之漂移（实测用 1.4 播 1.8
 * 的录像，660 处不一致）。</p>
 *
 * <p>录制端因此在回放旁边写一份 {@code <replay>.ai.json}（与 {@code -Drwx.rl.aiConfig}
 * 是同一份文档）。播放时只取其中 {@code definition.incomeMultiplier} 参与结算，其余参数
 * （权重、节拍、开关）都不影响回放：回放阶段 AI 不跑，命令来自录制。没有这份文件、
 * 或者不在回放中时，行为与原来完全一致。</p>
 */
public final class AiRlReplayConfig {
    public static final String PRESET_ID = AiRlHardStrategy.ID;
    private static final String SIDECAR_SUFFIX = ".ai.json";

    private static volatile String cachedPath;
    private static volatile float cachedIncome;
    private static volatile boolean cachedPresent;
    private static volatile String loggedPath;

    private AiRlReplayConfig() {
    }

    /** 只有可配置的 RL 预设才有定义级收入差异；原版档位一律不动。 */
    public static boolean isPreset(String id) {
        return PRESET_ID.equals(id);
    }

    /** 正在播放回放且旁边有 sidecar 时返回录制时的收入倍率，否则原样返回 fallback。 */
    public static float playbackIncome(float fallback) {
        try {
            GameEngine engine = GameEngine.getInstance();
            if (engine == null || engine.replayEngine == null || !engine.replayEngine.j()) {
                return fallback;
            }
            String path = engine.replayEngine.getReplayFilePath();
            if (path == null || path.isBlank()) {
                return fallback;
            }
            if (path.equals(cachedPath)) {
                return cachedPresent ? cachedIncome : fallback;
            }
            float value = readIncome(path);
            cachedIncome = value;
            cachedPresent = value > 0f;
            cachedPath = path;
            if (cachedPresent && !path.equals(loggedPath)) {
                loggedPath = path;
                GameEngine.log("RWX replay ai income -> " + value + " (" + path + SIDECAR_SUFFIX + ")");
            }
            return cachedPresent ? value : fallback;
        } catch (RuntimeException ignored) {
            return fallback;
        }
    }

    private static float readIncome(String replayPath) {
        Path sidecar = rwxSidecarPath(replayPath);
        if (sidecar == null || !Files.isRegularFile(sidecar)) {
            return -1f;
        }
        try {
            Map<String, Object> root = MicroJson.read(sidecar);
            Object definition = root.get("definition");
            if (!(definition instanceof Map<?, ?> def)) {
                return -1f;
            }
            Object node = def.get("incomeMultiplier");
            Object value = node instanceof Map<?, ?> wrapper && wrapper.containsKey("value")
                    ? wrapper.get("value")
                    : node;
            if (value instanceof Number number) {
                float income = number.floatValue();
                return income > 0f && Float.isFinite(income) ? income : -1f;
            }
        } catch (Exception error) {
            GameEngine.log("RWX replay ai config unreadable: " + sidecar + " " + error);
        }
        return -1f;
    }

    private static Path rwxSidecarPath(String replayPath) {
        try {
            Path direct = Path.of(replayPath);
            if (!direct.isAbsolute()) {
                Path underReplays = Path.of(System.getProperty("user.dir", ".")).resolve("replays").resolve(direct);
                if (Files.isRegularFile(underReplays)) {
                    direct = underReplays;
                }
            }
            return Path.of(direct.toAbsolutePath().normalize().toString() + SIDECAR_SUFFIX);
        } catch (RuntimeException error) {
            return null;
        }
    }
}
