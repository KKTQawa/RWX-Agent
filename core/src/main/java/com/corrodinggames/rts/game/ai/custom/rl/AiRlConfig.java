package com.corrodinggames.rts.game.ai.custom.rl;

import com.corrodinggames.rts.game.ai.strategy.AiCadence;
import com.corrodinggames.rts.game.ai.strategy.AiPhase;
import io.github.rwx.app.MicroJson;

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
    /** Default config of the shipped preset; relative to the checkout root. */
    public static final String DEFAULT_RELATIVE = "evaluate/RL/AI Hard-up/ai.json";

    private static volatile AiRlConfig cached;

    public final String name;
    public final String description;
    public final int baseDifficulty;
    public final String strategyVersion;
    public final float incomeMultiplier;
    public final AiCadence cadence;
    public final Set<AiPhase> originalPhases;
    public final boolean extendsOriginal;

    public final boolean overrideBuildingProduction;
    public final boolean overrideUnitProduction;
    public final boolean overrideUpgrades;
    public final boolean overrideTransportWaiting;
    public final boolean economyMaintenance;
    public final boolean tacticsEnabled;

    public final float buildingAttemptFrames;
    public final float buildingBankCredits;
    public final List<String> buildingPriority;
    public final Map<String, Integer> buildingMaxCount;
    public final Set<String> buildingDisabled;

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

    private AiRlConfig(Map<String, Object> root) {
        this.raw = root;
        Map<String, Object> meta = map(root.get("meta"));
        name = string(meta.get("name"), "RL Hard-up");
        description = string(meta.get("description"), "");
        baseDifficulty = integer(meta.get("baseDifficulty"), 1);
        strategyVersion = string(meta.get("strategyVersion"), "rwx.ai-rl-hard.v1");

        Map<String, Object> definition = map(root.get("definition"));
        incomeMultiplier = (float) number(value(definition.get("incomeMultiplier")), 1.0f);
        Map<String, Object> cadenceNode = map(definition.get("cadence"));
        cadence = new AiCadence(
                (float) number(value(cadenceNode.get("economy")), AiCadence.STANDARD.economy()),
                (float) number(value(cadenceNode.get("tactics")), AiCadence.STANDARD.tactics()),
                (float) number(value(cadenceNode.get("strategy")), AiCadence.STANDARD.strategy()));
        extendsOriginal = bool(definition.get("extendsOriginal"), true);
        Map<String, Object> phases = map(definition.get("originalPhases"));
        Set<AiPhase> enabled = new LinkedHashSet<>();
        if (bool(phases.get("initialization"), true)) enabled.add(AiPhase.INITIALIZATION);
        if (bool(phases.get("economy"), true)) enabled.add(AiPhase.ECONOMY);
        if (bool(phases.get("tactics"), true)) enabled.add(AiPhase.TACTICS);
        if (bool(phases.get("strategy"), true)) enabled.add(AiPhase.STRATEGY);
        originalPhases = Set.copyOf(enabled);

        Map<String, Object> overrides = map(root.get("overrides"));
        overrideBuildingProduction = bool(value(overrides.get("buildingProduction")), false);
        overrideUnitProduction = bool(value(overrides.get("unitProduction")), false);
        overrideUpgrades = bool(value(overrides.get("upgrades")), false);
        overrideTransportWaiting = bool(value(overrides.get("transportWaiting")), false);
        economyMaintenance = bool(value(overrides.get("economyMaintenance")), false);
        tacticsEnabled = bool(value(overrides.get("tactics")), false);

        Map<String, Object> building = map(root.get("building"));
        buildingAttemptFrames = (float) number(value(building.get("attemptIntervalFrames")), 180.0);
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
        unitReserveCredits = (float) number(value(units.get("reserveCredits")), 0.0);
        unitMaxPerCycle = (int) number(value(units.get("maxPerCycle")), 2);
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
        upgradeIntervalFrames = (float) number(value(upgrades.get("intervalFrames")), 180.0);
        upgradeMaxPerCycle = (int) number(value(upgrades.get("maxPerCycle")), 1);

        Map<String, Object> tactics = map(root.get("tactics"));
        tacticsIntervalFrames = (float) number(value(tactics.get("intervalFrames")), 60.0);
        retreatHpPercent = (float) number(value(tactics.get("retreatHpPercent")), 30.0);
        resumeHpPercent = (float) number(value(tactics.get("resumeHpPercent")), 60.0);
        stagingDistance = (float) number(value(tactics.get("stagingDistance")), 600.0);
        tacticsFocusFire = bool(value(tactics.get("focusFire")), false);
        tacticsAttackMove = bool(value(tactics.get("attackMove")), true);

        Map<String, Object> economy = map(root.get("economy"));
        economyHarvesters = bool(value(economy.get("harvesters")), false);
        economyReclaim = bool(value(economy.get("reclaim")), false);
        economyRetarget = bool(value(economy.get("retargetHarvesters")), false);
        economyRepair = bool(value(economy.get("repairBuildings")), false);

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
     * Process-wide config. Registration happens for every game, so a missing or malformed file must
     * never break an unrelated match: it falls back to the built-in defaults (Hard, every phase, no
     * takeovers, standard cadence) and reports the problem on stdout.
     */
    public static AiRlConfig current() {
        AiRlConfig local = cached;
        if (local == null) {
            synchronized (AiRlConfig.class) {
                local = cached;
                if (local == null) {
                    Path path = resolvePath();
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
                    local = new AiRlConfig(root);
                    cached = local;
                    System.out.println("RWX_RL_AI_CONFIG " + path + " name=" + local.name);
                }
            }
        }
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

    private static Path resolvePath() {
        String property = System.getProperty(PROPERTY);
        if (property != null && !property.isBlank()) return Path.of(property).toAbsolutePath().normalize();
        try {
            Path root = com.corrodinggames.rts.game.ai.custom.rwx_cli_tool.RwxCliTool.repoRoot();
            return root.resolve(DEFAULT_RELATIVE).toAbsolutePath().normalize();
        } catch (RuntimeException error) {
            return Path.of(DEFAULT_RELATIVE).toAbsolutePath().normalize();
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
