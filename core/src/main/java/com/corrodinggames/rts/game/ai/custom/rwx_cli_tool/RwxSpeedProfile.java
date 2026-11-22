package com.corrodinggames.rts.game.ai.custom.rwx_cli_tool;

import java.util.Locale;

/**
 * Game-time calibration for <em>diagnostic</em> runs.
 *
 * <p>RWX measures agents on a realtime clock: wall-clock latency is part of what is being measured,
 * not noise to be compensated. The scored configuration is therefore exactly one — {@code
 * realtime}, 1x. Everything else here exists only so a run can be repeated with a slower clock
 * afterwards, to quantify how much of a score difference is latency rather than decisions. Such a
 * run is marked {@code diagnostic} and is not leaderboard eligible.</p>
 *
 * <p>{@code sync} ("pause while the agent thinks") is not offered at all: it would remove the thing
 * being measured. {@link #parse} rejects it permanently rather than "for now".</p>
 */
public final class RwxSpeedProfile {
    /**
     * {@code REALTIME} 是唯一可上榜的配置；{@code SLOW} 用于“慢放后重跑”的诊断；
     * {@code FAST} 只用于把整条采集/评分链路跑通的加速彩排——它同样是非诊断口径，
     * 证据里会写 {@code fast:8}、{@code diagnostic=true}、{@code leaderboardEligible=false}。
     */
    public enum Kind { REALTIME, SLOW, FAST }

    /** {@code -Drwx.speed.profile=slow:0.5}; the launch argument sets the same property. */
    public static final String PROPERTY = "rwx.speed.profile";

    private static final RwxSpeedProfile REALTIME = new RwxSpeedProfile(Kind.REALTIME, 1.0f);
    private static volatile RwxSpeedProfile active = REALTIME;

    public final Kind kind;
    /** Engine {@code gameSpeed} the profile pins while the match runs; 1 for realtime. */
    public final float speed;

    private RwxSpeedProfile(Kind kind, float speed) {
        this.kind = kind;
        this.speed = speed;
    }

    public static RwxSpeedProfile realtime() {
        return REALTIME;
    }

    public static RwxSpeedProfile slow(float multiplier) {
        if (!Float.isFinite(multiplier) || multiplier <= 0.0f || multiplier >= 1.0f) {
            throw new IllegalArgumentException("slow speed must be greater than 0 and less than 1");
        }
        return new RwxSpeedProfile(Kind.SLOW, multiplier);
    }

    /** 加速彩排：{@code fast} (=8) | {@code fast:8} | {@code 8x}。1 < 倍率 <= 64。 */
    public static RwxSpeedProfile fast(float multiplier) {
        if (!Float.isFinite(multiplier) || multiplier <= 1.0f || multiplier > 64.0f) {
            throw new IllegalArgumentException("fast speed must be greater than 1 and at most 64");
        }
        return new RwxSpeedProfile(Kind.FAST, multiplier);
    }

    /**
     * {@code realtime} | {@code 1} | {@code slow} (=0.5) | {@code slow:0.25} | {@code 0.25}
     * | {@code fast} (=8) | {@code fast:8} | {@code 8x}.
     *
     * <p>{@code sync} is refused with the reason, so nobody mistakes the refusal for "not yet":
     * a clock that only advances on commands would delete the latency this benchmark measures.</p>
     */
    public static RwxSpeedProfile parse(String text) {
        if (text == null || text.isBlank()) return REALTIME;
        String value = text.trim().toLowerCase(Locale.ROOT);
        if (value.equals("realtime") || value.equals("1x") || value.equals("1")) return REALTIME;
        if (value.equals("sync") || value.startsWith("sync:")) {
            throw new IllegalArgumentException("speed profile 'sync' is not supported: RWX is a "
                    + "realtime benchmark and provides no mechanism that compensates for agent "
                    + "latency; use realtime (scored) or slow[:multiplier] (diagnostic only)");
        }
        boolean isFast = value.startsWith("fast");
        String multiplier = isFast ? value.substring("fast".length())
                : value.startsWith("slow") ? value.substring("slow".length()) : value;
        if (multiplier.startsWith(":")) multiplier = multiplier.substring(1);
        if (multiplier.startsWith("x")) multiplier = multiplier.substring(1);
        if (multiplier.endsWith("x")) multiplier = multiplier.substring(0, multiplier.length() - 1);
        if (multiplier.isBlank()) return isFast ? fast(8.0f) : slow(0.5f);
        float parsed;
        try {
            parsed = Float.parseFloat(multiplier);
        } catch (NumberFormatException invalid) {
            throw new IllegalArgumentException("unknown speed profile '" + text.trim()
                    + "'; use realtime, slow[:multiplier] or fast[:multiplier]");
        }
        // 裸数字只认慢放（<1）：`--speed-profile=2` 仍然是非法的，加速必须显式写 fast[:x]。
        return isFast ? fast(parsed) : slow(parsed);
    }

    public static RwxSpeedProfile active() {
        return active;
    }

    /** Installs the profile for this process; null restores realtime. */
    public static void install(RwxSpeedProfile profile) {
        active = profile == null ? REALTIME : profile;
    }

    /** {@code realtime} / {@code slow:0.5} / {@code fast:8}, as written into the evaluation evidence. */
    public String id() {
        if (kind == Kind.REALTIME) return "realtime";
        return (kind == Kind.FAST ? "fast:" : "slow:") + multiplier(speed);
    }

    /** True when the profile must keep {@code gameSpeed} pinned while the match runs. */
    public boolean enforcesSpeed() {
        return kind != Kind.REALTIME;
    }

    /**
     * True for a run that exists to measure latency's effect, not to be scored. Diagnostic runs
     * must never be compared with realtime runs as if they were the same configuration.
     */
    public boolean diagnostic() {
        return kind != Kind.REALTIME;
    }

    /** Only the realtime 1x configuration may enter the leaderboard. */
    public boolean leaderboardEligible() {
        return kind == Kind.REALTIME;
    }

    /**
     * Up to three decimals with trailing zeros removed: a 0.25x profile must read as {@code 0.25},
     * not {@code 0.2}, because the id ends up in evidence files people compare across runs.
     */
    private static String multiplier(float speed) {
        String text = String.format(Locale.ROOT, "%.3f", speed);
        while (text.endsWith("0")) text = text.substring(0, text.length() - 1);
        if (text.endsWith(".")) text = text.substring(0, text.length() - 1);
        return text;
    }

    @Override public String toString() {
        return id();
    }
}
