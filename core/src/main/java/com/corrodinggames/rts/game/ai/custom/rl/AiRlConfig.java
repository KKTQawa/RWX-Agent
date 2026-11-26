package com.corrodinggames.rts.game.ai.custom.rl;

import com.corrodinggames.rts.game.ai.strategy.AiCadence;
import com.corrodinggames.rts.game.ai.strategy.AiDefinition;
import com.corrodinggames.rts.game.ai.strategy.AiRegistry;
import com.corrodinggames.rts.game.ai.strategy.AiPhase;
import com.corrodinggames.rts.game.ai.strategy.RwxOriginalAiTuning;
import io.github.rwx.app.MicroJson;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

/**
 * Config-driven AI definition and runtime knobs, read from a JSON file.
 *
 * <p>Everything the engine lets a custom strategy change without touching engine sources lives here:
 * the definition-level values (income, callback cadence, which original phases keep running) and the
 * gates/parameters of the optional takeovers (building production, unit production, upgrades, economy
 * maintenance, tactics). With every gate off this AI is the original difficulty it extends, so a
 * config that changes one number changes exactly one thing.</p>
 *
 * <p>The file also carries a {@code reference} table of values that are hardcoded in the original
 * controllers. They are documentation only: applying them needs an engine hook, and the runner reports
 * them as {@code applied:false} so nobody mistakes a documented range for a live knob.</p>
 */
public final class AiRlConfig {
    public static final String PROPERTY = "rwx.rl.aiConfig";
    /**
     * 第二个可配置 AI 实例的文档路径（注册 id {@code rwx.ai-rl-hard-2}）。
     * 存在的意义：同一局里让两份不同权重互相对打（例如新模型 vs Hard-up v1），
     * 否则一份 spec 只有一个 {@code aiConfig}，两队只能吃同一套参数。
     */
    public static final String PROPERTY2 = "rwx.rl.aiConfig2";
    private static volatile AiRlConfig cached;
    private static volatile AiRlConfig cachedSecond;

    private static final class DeliveredV1 {
        private static final AiRlConfig CONFIG = fromBundledResource("hardupv1-gen200.json");
    }

    public final String name;
    public final String description;
    /** Registry id, numeric code or short name of the AI whose behaviour this preset extends. */
    public final String base;
    public final int baseDifficulty;
    public final String strategyVersion;
    public final float incomeMultiplier;
    public final AiCadence cadence;
    public final Set<AiPhase> originalPhases;
    public final boolean extendsOriginal;

    public final boolean overrideBuildingProduction;
    public final boolean overrideUnitProduction;
    /** 只接管战斗单位，建造者/运输/采集仍由原版生产。 */
    public final boolean overrideCombatUnitProduction;
    public final boolean overrideUpgrades;
    public final boolean overrideTransportWaiting;
    public final boolean economyMaintenance;
    public final boolean tacticsEnabled;
    public final RwxOriginalAiTuning originalTuning;

    public final float buildingAttemptFrames;
    public final float originalBuildingIntervalFrames;
    public final float buildingBankCredits;
    public final List<String> buildingPriority;
    public final Map<String, Integer> buildingMaxCount;
    public final Set<String> buildingDisabled;

    public final float buildingReserveCredits;
    public final float unitReserveCredits;
    public final int unitMaxPerCycle;
    public final Map<String, Float> unitWeights;
    public final boolean unitReinforcement;

    public final float upgradeBankCredits;
    public final float upgradeIntervalFrames;
    public final int upgradeMaxPerCycle;

    public final float tacticsIntervalFrames;
    public final float retreatHpPercent;
    public final float resumeHpPercent;
    public final float stagingDistance;
    public final boolean tacticsFocusFire;
    public final boolean tacticsAttackMove;

    public final boolean economyHarvesters;
    public final boolean economyReclaim;
    public final boolean economyRetarget;
    public final boolean economyRepair;

    private final Map<Integer, Map<String, Object>> slotOverrides;
    private final Map<String, Object> raw;

    // ---- 建筑打分表 / Impossible 分支（两个可选接管，配置缺省时完全不生效）----
    /** {@code buildingScore.enabled}：打开后 20 个 float 接管建筑选型打分。 */
    public final boolean buildingScoresEnabled;
    public final Map<String, Float> buildingScoreValues;
    /** {@code impossible.enabled}：打开后 8 个值接管原版 Impossible 的 7 个分支。 */
    public final boolean impossibleEnabled;
    public final Map<String, Float> impossibleValues;
    private volatile com.corrodinggames.rts.game.ai.strategy.AiBuildingScoreTable buildingScoreTable;
    private volatile com.corrodinggames.rts.game.ai.strategy.AiImpossibleBranches impossibleBranches;

    private AiRlConfig(Map<String, Object> root) {
        boolean originalTuningSchema = "rwx-rl-ai-v3".equals(root.get("schema"))
                || "rwx-rl-ai-v4".equals(root.get("schema"));
        this.raw = root;
        Map<String, Object> meta = map(root.get("meta"));
        name = string(meta.get("name"), "RL Hard-up");
        description = string(meta.get("description"), "");
        // The base is resolved once here: its difficulty, income and phase set are copied, then the
        // document may override each of them. Nothing about a difficulty is hardcoded in the strategy.
        BaseResolution resolved = resolveBase(meta.get("base"), meta.get("baseDifficulty"));
        base = resolved.id;
        baseDifficulty = resolved.difficulty;
        strategyVersion = string(meta.get("strategyVersion"), "rwx.ai-rl-hard.v1");

        Map<String, Object> definition = map(root.get("definition"));
        Object incomeNode = definition.get("incomeMultiplier");
        incomeMultiplier = incomeNode == null || (incomeNode instanceof Map<?, ?> wrapper && !wrapper.containsKey("value"))
                ? resolved.income
                : (float) number(value(incomeNode), resolved.income);
        Map<String, Object> cadenceNode = map(definition.get("cadence"));
        // Absent cadence inherits the base preset's periods; a present entry overrides just that phase.
        cadence = new AiCadence(
                (float) number(value(cadenceNode.get("economy")), resolved.cadence.economy()),
                (float) number(value(cadenceNode.get("tactics")), resolved.cadence.tactics()),
                (float) number(value(cadenceNode.get("strategy")), resolved.cadence.strategy()));
        extendsOriginal = bool(definition.get("extendsOriginal"), true);
        Map<String, Object> phases = map(definition.get("originalPhases"));
        Set<AiPhase> enabled = new LinkedHashSet<>();
        for (AiPhase phase : AiPhase.values()) {
            if (bool(phases.get(phase.name().toLowerCase(Locale.ROOT)), resolved.phases.contains(phase))) {
                enabled.add(phase);
            }
        }
        originalPhases = Set.copyOf(enabled);

        Map<String, Object> overrides = map(root.get("overrides"));
        overrideBuildingProduction = bool(value(overrides.get("buildingProduction")), false);
        overrideUnitProduction = bool(value(overrides.get("unitProduction")), false);
        overrideCombatUnitProduction = bool(value(overrides.get("combatUnitProduction")), false);
        overrideUpgrades = bool(value(overrides.get("upgrades")), false);
        overrideTransportWaiting = bool(value(overrides.get("transportWaiting")), false);
        economyMaintenance = bool(value(overrides.get("economyMaintenance")), false);
        tacticsEnabled = bool(value(overrides.get("tactics")), false);

        Map<String, Object> building = map(root.get("building"));
        buildingAttemptFrames = (float) number(value(building.get("attemptIntervalFrames")), originalTuningSchema ? 270.0 : 180.0);
        // 写了这个 key 且没接管建造 = 只替换原版建造节拍的基准值（270 + strategyId % 15），
        // 选什么、放哪里仍归原版。不按 schema 版本限制：v1 的文档同样可能只想改这个数。
        originalBuildingIntervalFrames = !overrideBuildingProduction
                && value(building.get("attemptIntervalFrames")) != null
                ? buildingAttemptFrames : 0f;
        buildingBankCredits = (float) number(value(building.get("bankCredits")), 0.0);
        buildingPriority = strings(building.get("priority"));
        Map<String, Object> maxCount = map(building.get("maxPerType"));
        Map<String, Integer> counts = new LinkedHashMap<>();
        for (Map.Entry<String, Object> entry : maxCount.entrySet()) {
            counts.put(entry.getKey().trim().toLowerCase(Locale.ROOT), (int) number(value(entry.getValue()), -1));
        }
        buildingMaxCount = Map.copyOf(counts);
        buildingDisabled = Set.copyOf(strings(building.get("disabled")));

        Map<String, Object> units = map(root.get("units"));
        buildingReserveCredits = (float) number(value(definition.get("buildingReserve")), 3000.0);
        unitReserveCredits = (float) number(value(units.get("reserveCredits")), 0.0);
        unitMaxPerCycle = (int) number(value(units.get("maxPerCycle")), originalTuningSchema ? 12 : 2);
        unitReinforcement = bool(value(units.get("reinforcement")), false);
        Map<String, Object> weights = map(units.get("weights"));
        Map<String, Float> parsedWeights = new LinkedHashMap<>();
        for (Map.Entry<String, Object> entry : weights.entrySet()) {
            float weight = (float) number(value(entry.getValue()), 0.0);
            if (weight > 0) parsedWeights.put(entry.getKey().trim().toLowerCase(Locale.ROOT), weight);
        }
        unitWeights = Map.copyOf(parsedWeights);

        Map<String, Object> upgrades = map(root.get("upgrades"));
        upgradeBankCredits = (float) number(value(upgrades.get("bankCredits")), 1200.0);
        upgradeIntervalFrames = (float) number(value(upgrades.get("intervalFrames")), originalTuningSchema ? 250.0 : 180.0);
        upgradeMaxPerCycle = (int) number(value(upgrades.get("maxPerCycle")), 1);

        Map<String, Object> tactics = map(root.get("tactics"));
        tacticsIntervalFrames = (float) number(value(tactics.get("intervalFrames")), 60.0);
        retreatHpPercent = (float) number(value(tactics.get("retreatHpPercent")), 30.0);
        resumeHpPercent = (float) number(value(tactics.get("resumeHpPercent")), 60.0);
        stagingDistance = (float) number(value(tactics.get("stagingDistance")), 600.0);
        tacticsFocusFire = bool(value(tactics.get("focusFire")), false);
        tacticsAttackMove = bool(value(tactics.get("attackMove")), true);
        originalTuning = originalTuningSchema
                ? RwxOriginalAiTuning.fromDocument(root, buildingAttemptFrames,
                        overrideUpgrades ? upgradeIntervalFrames : 0f)
                : RwxOriginalAiTuning.ORIGINAL;

        Map<String, Object> economy = map(root.get("economy"));
        economyHarvesters = bool(value(economy.get("harvesters")), false);
        economyReclaim = bool(value(economy.get("reclaim")), false);
        economyRetarget = bool(value(economy.get("retargetHarvesters")), false);
        economyRepair = bool(value(economy.get("repairBuildings")), false);

        // 两个可选接管：段缺失 = 关闭，行为与原版完全一致。
        // 开关键叫 takeover（不是 enabled）：它接管的是「我们自己的分支表」，与「是不是原版 Impossible 难度」无关。
        // 段存在但没写这个键时按“开启”处理（满血默认），旧文档里的 enabled 仍然兼容。
        Map<String, Object> buildingScore = map(root.get("buildingScore"));
        buildingScoreValues = readNumbers(buildingScore);
        buildingScoresEnabled = takeoverFlag(buildingScore) && !buildingScoreValues.isEmpty();
        Map<String, Object> impossible = map(root.get("impossible"));
        impossibleValues = readNumbers(impossible);
        impossibleEnabled = takeoverFlag(impossible) && !impossibleValues.isEmpty();

        Map<String, Object> slots = map(root.get("slots"));
        Map<Integer, Map<String, Object>> parsedSlots = new LinkedHashMap<>();
        for (Map.Entry<String, Object> entry : slots.entrySet()) {
            try {
                parsedSlots.put(Integer.parseInt(entry.getKey().trim()), map(entry.getValue()));
            } catch (NumberFormatException ignored) {
                // A malformed slot key is not worth failing the whole match for.
            }
        }
        slotOverrides = Map.copyOf(parsedSlots);

        validate();
    }

    /**
     * 直接从已解析的文档构造（不读进程级缓存、不看系统属性）。
     *
     * <p>给测试与离线工具用：同一份 JSON 既能验证解析结果，也能验证接管对象拿到的数值。</p>
     */
    public static AiRlConfig fromDocument(Map<String, Object> root) {
        return new AiRlConfig(root);
    }

    static AiRlConfig fromBundledResource(String filename) {
        String resource = "/io/github/rwx/ai/" + filename;
        try (var input = AiRlConfig.class.getResourceAsStream(resource)) {
            if (input == null) throw new IllegalStateException("Missing bundled AI model " + resource);
            return fromDocument(MicroJson.decode(new String(input.readAllBytes(), StandardCharsets.UTF_8)));
        } catch (IOException error) {
            throw new UncheckedIOException("Unable to read bundled AI model " + resource, error);
        }
    }

    static String configurableLabel(AiRlConfig config) {
        return config == DeliveredV1.CONFIG ? "Hard-up v1" : "RL Hard-up";
    }

    /**
     * Process-wide config. Registration happens for every game, so a missing or malformed file must
     * never break an unrelated match: unreadable overrides fall back to the original Hard settings.
     * With no requested override, the preset uses the bundled v1 delivery.
     */
    public static AiRlConfig current() {
        AiRlConfig local = cached;
        if (local == null) {
            synchronized (AiRlConfig.class) {
                local = cached;
                if (local == null) {
                    cached = local = load(PROPERTY);
                }
            }
        }
        return local;
    }

    /** 第二份可配置 AI 的文档（`rwx.rl.aiConfig2`）；未设置时使用内嵌 v1 交付。 */
    public static AiRlConfig currentSecond() {
        AiRlConfig local = cachedSecond;
        if (local == null) {
            synchronized (AiRlConfig.class) {
                local = cachedSecond;
                if (local == null) {
                    cachedSecond = local = load(PROPERTY2);
                }
            }
        }
        return local;
    }

    private static AiRlConfig load(String property) {
        String configured = System.getProperty(property);
        if (configured == null || configured.isBlank()) {
            return DeliveredV1.CONFIG;
        }
        Path path = Path.of(configured).toAbsolutePath().normalize();
        Map<String, Object> root = null;
        if (Files.isRegularFile(path)) {
            try {
                root = MicroJson.read(path);
            } catch (Exception error) {
                System.out.println("RWX_RL_AI_CONFIG_ERROR " + path + " " + error);
            }
        } else {
            System.out.println("RWX_RL_AI_CONFIG_MISSING " + path);
        }
        if (root == null) root = defaults();
        AiRlConfig local = new AiRlConfig(root);
        System.out.println("RWX_RL_AI_CONFIG " + property + "=" + path + " name=" + local.name);
        return local;
    }

    /** Built-in equivalent of the shipped default document: exactly the original Hard AI. */
    private static Map<String, Object> defaults() {
        Map<String, Object> root = new LinkedHashMap<>();
        root.put("meta", Map.of("name", "RL Hard-up (built-in defaults)", "baseDifficulty", 1));
        root.put("definition", Map.of(
                "incomeMultiplier", 1.4,
                "extendsOriginal", true,
                "originalPhases", Map.of(
                        "initialization", true, "economy", true, "tactics", true, "strategy", true),
                "cadence", Map.of("economy", 25, "tactics", 80, "strategy", 250)));
        return root;
    }

    /** Per-slot variant: {@code slots.<teamId>} is merged over the top-level document. */
    public AiRlConfig forSlot(int teamId) {
        Map<String, Object> override = slotOverrides.get(teamId);
        if (override == null || override.isEmpty()) return this;
        return new AiRlConfig(merge(raw, override));
    }

    /** What a preset inherits before its own overrides are applied. */
    private record BaseResolution(String id, int difficulty, float income, Set<AiPhase> phases,
                                  AiCadence cadence) { }

    /**
     * Resolves {@code meta.base} against the AI registry (so any registered preset can be extended),
     * then against the original difficulty table, then falls back to Hard. {@code baseDifficulty}
     * stays supported as a shorthand for {@code meta.base: <code>}.
     */
    private static BaseResolution resolveBase(Object baseNode, Object difficultyNode) {
        Object raw = value(baseNode);
        if (raw == null) raw = value(difficultyNode);
        String text = raw == null ? null : String.valueOf(raw).trim();
        if (text == null || text.isEmpty()) text = "rwx.original.hard";

        AiDefinition definition = null;
        try {
            definition = AiRegistry.find(text);
            if (definition == null) {
                try {
                    definition = AiRegistry.find((int) Double.parseDouble(text));
                } catch (NumberFormatException ignored) {
                    // fall through to the built-in table
                }
            }
        } catch (Throwable ignored) {
            // Registry static init may be in progress; the table below still knows the originals.
        }
        if (definition != null) {
            Set<AiPhase> phases = new LinkedHashSet<>();
            for (AiPhase phase : AiPhase.values()) {
                if (definition.runsOriginal(phase)) phases.add(phase);
            }
            return new BaseResolution(definition.id(), definition.originalDifficulty(),
                    definition.incomeMultiplier(), Set.copyOf(phases), definition.cadence());
        }

        int code = switch (text.toLowerCase(Locale.ROOT).replace("rwx.original.", "")) {
            case "very-easy", "veryeasy" -> -2;
            case "easy" -> -1;
            case "medium", "normal" -> 0;
            case "hard" -> 1;
            case "very-hard", "veryhard" -> 2;
            case "impossible" -> 3;
            default -> {
                try {
                    yield (int) Double.parseDouble(text);
                } catch (NumberFormatException error) {
                    throw new IllegalArgumentException(
                            "Unknown meta.base '" + text + "'. Use a registry id (e.g. rwx.original.very-hard), "
                                    + "a difficulty code -2..3, or one of very-easy/easy/medium/hard/very-hard/impossible",
                            error);
                }
            }
        };
        if (code < -2 || code > 3) {
            throw new IllegalArgumentException("meta.base code must be -2..3, got " + code);
        }
        float income = code > 0 ? 1.0f + code * 0.4f : 1.0f + code * 0.3f;
        if (code == 3) income += 1.5f;
        return new BaseResolution("rwx.original." + code, code, Math.max(0.1f, income),
                Set.of(AiPhase.values()), AiCadence.STANDARD);
    }

    private void validate() {
        if (incomeMultiplier <= 0f || !Float.isFinite(incomeMultiplier)) {
            throw new IllegalArgumentException("incomeMultiplier must be positive");
        }
        if (buildingAttemptFrames <= 0f) throw new IllegalArgumentException("building.attemptIntervalFrames must be positive");
        if (tacticsIntervalFrames <= 0f) throw new IllegalArgumentException("tactics.intervalFrames must be positive");
        if (retreatHpPercent <= 0f || retreatHpPercent >= resumeHpPercent) {
            throw new IllegalArgumentException("tactics retreatHpPercent must be below resumeHpPercent");
        }
    }

    // --- small JSON helpers: values may be plain numbers/bools or {"value": x, ...} objects ---

    @SuppressWarnings("unchecked")
    private static Map<String, Object> map(Object node) {
        return node instanceof Map ? (Map<String, Object>) node : Map.of();
    }

    private static Object value(Object node) {
        if (node instanceof Map<?, ?> wrapper && wrapper.containsKey("value")) {
            return wrapper.get("value");
        }
        return node;
    }

    private static double number(Object node, double fallback) {
        Object raw = value(node);
        if (raw instanceof Number number) return number.doubleValue();
        if (raw instanceof String text) {
            try {
                return Double.parseDouble(text.trim());
            } catch (NumberFormatException ignored) {
                return fallback;
            }
        }
        return fallback;
    }

    private static int integer(Object node, int fallback) {
        return (int) Math.round(number(node, fallback));
    }

    /**
     * 段的接管开关：{@code takeover} 优先，旧文档的 {@code enabled} 兼容；段存在但没写开关时默认开启。
     * 段本身缺失时返回 false（= 完全走原版逻辑）。
     */
    private static boolean takeoverFlag(Map<String, Object> section) {
        if (section.isEmpty()) {
            return false;
        }
        Object flag = section.containsKey("takeover") ? section.get("takeover") : section.get("enabled");
        return flag == null || bool(value(flag), true);
    }

    /**
     * 读一个“旋钮组”：跳过 {@code _note} / {@code enabled} / {@code preset}，其余按
     * {@code {"value":x}} 或裸数字解析成 name → float。缺 value 的项直接忽略。
     */
    private static Map<String, Float> readNumbers(Map<String, Object> group) {
        Map<String, Float> values = new LinkedHashMap<>();
        for (Map.Entry<String, Object> entry : group.entrySet()) {
            String key = entry.getKey();
            if (key.startsWith("_") || key.equals("takeover") || key.equals("enabled") || key.equals("preset")
                    || key.equals("experimentalLandFactory") || key.equals("experimentalAndNukes")) {
                continue;
            }
            Object raw = value(entry.getValue());
            if (raw instanceof Number number) {
                values.put(key, number.floatValue());
            }
        }
        return Map.copyOf(values);
    }

    /** 建筑选型打分表的配置实例；段缺失或 {@code enabled=false} 时返回 null（= 原版 if 链）。 */
    public com.corrodinggames.rts.game.ai.strategy.AiBuildingScoreTable buildingScoreTable() {
        if (!buildingScoresEnabled) {
            return null;
        }
        com.corrodinggames.rts.game.ai.strategy.AiBuildingScoreTable local = buildingScoreTable;
        if (local == null) {
            synchronized (this) {
                local = buildingScoreTable;
                if (local == null) {
                    local = new com.corrodinggames.rts.game.ai.strategy.AiBuildingScoreTable()
                            .applyValues(buildingScoreValues).enable();
                    buildingScoreTable = local;
                    System.out.println("RWX_RL_SCORES enabled=true knobs=" + buildingScoreValues.size()
                            + " " + local.describeForLog());
                }
            }
        }
        return local;
    }

    /** Impossible 分支的配置实例；段缺失或 {@code enabled=false} 时返回 {@code ORIGINAL}。 */
    public com.corrodinggames.rts.game.ai.strategy.AiImpossibleBranches impossibleBranches() {
        if (!impossibleEnabled) {
            return com.corrodinggames.rts.game.ai.strategy.AiImpossibleBranches.ORIGINAL;
        }
        com.corrodinggames.rts.game.ai.strategy.AiImpossibleBranches local = impossibleBranches;
        if (local == null) {
            synchronized (this) {
                local = impossibleBranches;
                if (local == null) {
                    local = new com.corrodinggames.rts.game.ai.strategy.AiImpossibleBranches()
                            .applyValues(impossibleValues).enable();
                    impossibleBranches = local;
                    System.out.println("RWX_RL_BRANCHES enabled=true knobs=" + impossibleValues.size()
                            + " defensiveScoreBase=" + local.defensiveScoreBase()
                            + " builderGroupMaxUnits=" + local.builderGroupMaxUnits()
                            + " idleLimit=" + local.productionIdleUnitsLimit());
                }
            }
        }
        return local;
    }

    private static boolean bool(Object node, boolean fallback) {
        Object raw = value(node);
        if (raw instanceof Boolean value) return value;
        if (raw instanceof String text) return Boolean.parseBoolean(text.trim());
        return fallback;
    }

    private static String string(Object node, String fallback) {
        Object raw = value(node);
        return raw instanceof String text && !text.isBlank() ? text : fallback;
    }

    private static List<String> strings(Object node) {
        List<String> result = new ArrayList<>();
        if (node instanceof List<?> list) {
            for (Object item : list) {
                Object raw = value(item);
                if (raw instanceof String text && !text.isBlank()) result.add(text.trim().toLowerCase(Locale.ROOT));
            }
        }
        return result;
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> merge(Map<String, Object> base, Map<String, Object> override) {
        Map<String, Object> merged = new LinkedHashMap<>(base);
        for (Map.Entry<String, Object> entry : override.entrySet()) {
            Object existing = merged.get(entry.getKey());
            if (existing instanceof Map && entry.getValue() instanceof Map) {
                merged.put(entry.getKey(), merge((Map<String, Object>) existing, (Map<String, Object>) entry.getValue()));
            } else {
                merged.put(entry.getKey(), entry.getValue());
            }
        }
        return merged;
    }
}
