package com.corrodinggames.rts.game.ai.strategy;

import java.util.Map;

import static com.corrodinggames.rts.game.ai.strategy.RwxOriginalAiTuning.count;
import static com.corrodinggames.rts.game.ai.strategy.RwxOriginalAiTuning.number;
import static com.corrodinggames.rts.game.ai.strategy.RwxOriginalAiTuning.section;

/** Values used at the existing expansion, placement, transport and upgrade decision points. */
public record RwxAiV4Tuning(int pathfindingOverloadThreshold, int baseRadius, int resourceOutpostRadius,
                           int frontOutpostRadius, int maxResourceOutposts, int maxFrontOutposts,
                           int resourceScanCooldownFrames, int frontScanCooldownFrames,
                           int buildingFailureBackoffFrames, int placementAttempts, int fabricatorClusterAttempts,
                           int navalRadiusStart, int navalRadiusStep, int transporterGroupLimit,
                           int transporterGroupCapacity, int transporterTimeoutFrames, int transporterDropTolerance,
                           double upgradeActionProbabilityScale) {
    public static final RwxAiV4Tuning ORIGINAL = new RwxAiV4Tuning(3000, 420, 360, 310, 2, 3,
            2000, 5000, 120, 15, 6, 600, 100, 3, 1, 1700, 40, 1.0);

    static RwxAiV4Tuning fromReference(Map<?, ?> reference) {
        Map<?, ?> transporters = section(reference, "transporterGroups");
        RwxAiV4Tuning tuning = new RwxAiV4Tuning(
                count(reference, "pathfindingOverloadThreshold", ORIGINAL.pathfindingOverloadThreshold),
                count(reference, "baseRadius", ORIGINAL.baseRadius),
                count(reference, "resourceOutpostRadius", ORIGINAL.resourceOutpostRadius),
                count(reference, "frontOutpostRadius", ORIGINAL.frontOutpostRadius),
                count(reference, "maxResourceOutposts", ORIGINAL.maxResourceOutposts),
                count(reference, "maxFrontOutposts", ORIGINAL.maxFrontOutposts),
                count(reference, "resourceScanCooldownFrames", ORIGINAL.resourceScanCooldownFrames),
                count(reference, "frontScanCooldownFrames", ORIGINAL.frontScanCooldownFrames),
                count(reference, "buildingFailureBackoffFrames", ORIGINAL.buildingFailureBackoffFrames),
                count(reference, "placementAttempts", ORIGINAL.placementAttempts),
                count(reference, "fabricatorClusterAttempts", ORIGINAL.fabricatorClusterAttempts),
                count(reference, "navalRadiusStart", ORIGINAL.navalRadiusStart),
                count(reference, "navalRadiusStep", ORIGINAL.navalRadiusStep),
                count(transporters, "max", ORIGINAL.transporterGroupLimit),
                count(transporters, "capacity", ORIGINAL.transporterGroupCapacity),
                count(reference, "transporterTimeoutFrames", ORIGINAL.transporterTimeoutFrames),
                count(reference, "transporterDropTolerance", ORIGINAL.transporterDropTolerance),
                number(reference, "upgradeActionProbabilityScale", ORIGINAL.upgradeActionProbabilityScale));
        if (tuning.baseRadius == 0 || tuning.resourceOutpostRadius == 0 || tuning.frontOutpostRadius == 0
                || tuning.placementAttempts <= tuning.fabricatorClusterAttempts || tuning.navalRadiusStart == 0
                || tuning.transporterGroupCapacity == 0 || tuning.resourceScanCooldownFrames == 0
                || tuning.frontScanCooldownFrames == 0 || tuning.transporterTimeoutFrames == 0) {
            throw new IllegalArgumentException("Invalid Hard-up v4 radius, timer or attempt limit");
        }
        return tuning;
    }

    public float resourceScanTimer(float extraDecay) {
        // v4 measures the post-success cooldown in elapsed frames, independently of the legacy decay.
        return this == ORIGINAL ? resourceScanCooldownFrames : resourceScanCooldownFrames * (1f + extraDecay);
    }

    public float scaleUpgradeThreshold(float threshold) {
        if (upgradeActionProbabilityScale == 1.0) return threshold;
        // Original draw is an integer from 0 to 99 and passes only if strictly above the threshold.
        int winningRolls = Math.max(0, 99 - (int) Math.floor(threshold));
        if (winningRolls == 0) return threshold;
        long scaledRolls = Math.round(winningRolls * upgradeActionProbabilityScale);
        return 99 - Math.min(89L, scaledRolls);
    }
}
