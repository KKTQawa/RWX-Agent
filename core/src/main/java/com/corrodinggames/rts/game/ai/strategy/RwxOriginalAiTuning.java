package com.corrodinggames.rts.game.ai.strategy;

import java.util.Map;

/** Numeric overrides for existing base and group branches in Hard-up v3. */
public record RwxOriginalAiTuning(float buildingInterval, float upgradeInterval,
                                  Production production, Groups groups) {
    public static final RwxOriginalAiTuning ORIGINAL = fromDocument(Map.of(), 0, 0);

    public record Production(int attempts, float scoreCap, int reserveCredits,
                             int highCredits, float highScore, int lowCredits, float lowScore) {
        public boolean permits(double credits, float score) {
            return (credits >= highCredits && score >= highScore) || (credits >= lowCredits && score >= lowScore);
        }
    }

    public record Groups(int builderNormal, int builderAggressive, int builderEstablished, int builderLarge,
                         int landFirst, int landSecond, int attackDelay, int recruitBase,
                         int patrol, int order, double retreatRatio, double resumeRatio,
                         int stagingDistance, int minUnits, int weakAttackLifetime, int attackLifetime,
                         int attackMoveThreshold) { }

    public static RwxOriginalAiTuning fromDocument(Map<String, Object> doc, float building, float upgrade) {
        Map<?, ?> reference = section(doc, "reference");
        Map<?, ?> tactics = section(doc, "tactics");
        Map<?, ?> units = section(doc, "units");
        Map<?, ?> credits = section(reference, "attackCreditThresholds");
        Map<?, ?> builders = section(reference, "builderGroupSize");
        Map<?, ?> capacity = section(reference, "groupCapacity");
        Map<?, ?> lifetime = section(reference, "groupCombatLifetime");
        Production production = new Production(
                count(reference, "productionAttemptsPerCycle", 12), (float) number(reference, "reclaimScoreCap", 3.5),
                count(units, "reserveCredits", 0), count(credits, "highCredits", 1300),
                (float) number(credits, "highScore", 1), count(credits, "lowCredits", 300),
                (float) number(credits, "lowScore", 3));
        Groups groups = new Groups(
                count(builders, "normal", 1), count(builders, "aggressive", 2),
                count(builders, "established", 2), count(builders, "large", 3),
                count(capacity, "landFirst", 3), count(capacity, "landSecond", 5),
                count(reference, "groupAttackDelayFrames", 1000), count(reference, "groupRecruitFrames", 200),
                count(reference, "groupPatrolFrames", 4000),
                count(tactics, "intervalFrames", count(reference, "groupOrderFrames", 800)),
                number(tactics, "retreatHpPercent", 50) / 100.0, number(tactics, "resumeHpPercent", 60) / 100.0,
                count(tactics, "stagingDistance", 720), count(lifetime, "minUnits", 3),
                count(lifetime, "attackFrames", 1000), count(lifetime, "totalAttackFrames", 11000),
                count(reference, "attackMoveChance", 80));
        if (production.highCredits <= production.lowCredits || production.highScore >= production.lowScore
                || production.lowScore > production.scoreCap || production.attempts < 1) {
            throw new IllegalArgumentException("Hard-up v3 production thresholds overlap or are unreachable");
        }
        if (groups.retreatRatio >= groups.resumeRatio || groups.stagingDistance < 450
                || groups.weakAttackLifetime >= groups.attackLifetime || groups.attackMoveThreshold > 101
                || groups.patrol == 0 || groups.order == 0) {
            throw new IllegalArgumentException("Hard-up v3 group thresholds or timers are invalid");
        }
        return new RwxOriginalAiTuning(building, upgrade, production, groups);
    }

    private static Map<?, ?> section(Map<?, ?> doc, String key) {
        return doc.get(key) instanceof Map<?, ?> map ? map : Map.of();
    }

    private static double number(Map<?, ?> doc, String key, double fallback) {
        Object raw = doc.get(key);
        if (raw instanceof Map<?, ?> wrapper) raw = wrapper.get("value");
        if (raw == null) return fallback;
        if (!(raw instanceof Number number) || !Double.isFinite(number.doubleValue()) || number.doubleValue() < 0) {
            throw new IllegalArgumentException("Invalid Hard-up v3 number: " + key);
        }
        return number.doubleValue();
    }

    private static int count(Map<?, ?> doc, String key, int fallback) {
        double number = number(doc, key, fallback);
        if (number != (int) number) throw new IllegalArgumentException("Expected integer: " + key);
        return (int) number;
    }
}
