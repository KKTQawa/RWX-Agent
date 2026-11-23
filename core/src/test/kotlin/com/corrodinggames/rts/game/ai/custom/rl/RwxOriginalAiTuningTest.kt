package com.corrodinggames.rts.game.ai.custom.rl

import com.corrodinggames.rts.game.ai.strategy.RwxOriginalAiTuning
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertSame
import kotlin.test.assertTrue

class RwxOriginalAiTuningTest {
    @Test
    fun `tagged v2 uses native interval and historical v2 retains its effective alias`() {
        val building = mapOf("attemptIntervalFrames" to mapOf("value" to 430))
        // 任何布局（含 v1）写了这个 key 都只替换原版建造节拍的基准值。
        val v1 = AiRlConfig.fromDocument(mapOf("building" to building))
        assertEquals(430f, v1.originalBuildingIntervalFrames)

        val impossible = mapOf("takeover" to true, "defensiveScoreBase" to 190)
        val historical = AiRlConfig.fromDocument(mapOf("schema" to "rwx-rl-ai-v1",
            "building" to building, "impossible" to impossible))
        // 两个字段同时出现时 attemptIntervalFrames 优先，旧别名原样保留但不再是生效值。
        assertEquals(430f, historical.originalBuildingIntervalFrames)
        assertEquals(190f, historical.impossibleBranches().defensiveScoreBase())
        assertSame(RwxOriginalAiTuning.ORIGINAL, historical.originalTuning)

        val tagged = AiRlConfig.fromDocument(mapOf("schema" to "rwx-rl-ai-v2",
            "building" to building, "impossible" to impossible))
        assertEquals(430f, tagged.originalBuildingIntervalFrames)

        val aliasOnly = AiRlConfig.fromDocument(mapOf("schema" to "rwx-rl-ai-v2", "impossible" to impossible))
        assertEquals(0f, aliasOnly.originalBuildingIntervalFrames)
        assertEquals(190f, aliasOnly.impossibleBranches().defensiveScoreBase())
    }

    @Test
    fun `sparse v3 uses original defaults and legacy documents keep the original tuning sentinel`() {
        val legacy = AiRlConfig.fromDocument(emptyMap())
        assertSame(RwxOriginalAiTuning.ORIGINAL, legacy.originalTuning)

        val v3 = AiRlConfig.fromDocument(mapOf(
            "schema" to "rwx-rl-ai-v3",
            "overrides" to mapOf("upgrades" to true),
        ))
        val tuning = v3.originalTuning
        assertEquals(270f, tuning.buildingInterval())
        assertEquals(250f, tuning.upgradeInterval())
        assertEquals(12, v3.unitMaxPerCycle)
        assertEquals(RwxOriginalAiTuning.ORIGINAL.production(), tuning.production())
        assertEquals(RwxOriginalAiTuning.ORIGINAL.groups(), tuning.groups())
        assertTrue(tuning.production().permits(1300.0, 1f))
        assertTrue(tuning.production().permits(300.0, 3f))
        assertFalse(tuning.production().permits(400.0, 2.99f))
    }

    @Test
    fun `v3 applies numeric wrappers and accepts the group order alias`() {
        val v3 = AiRlConfig.fromDocument(mapOf(
            "schema" to "rwx-rl-ai-v3",
            "overrides" to mapOf("upgrades" to true),
            "definition" to mapOf("cadence" to mapOf("strategy" to 300)),
            "upgrades" to mapOf("intervalFrames" to mapOf("value" to 100)),
            "building" to mapOf("attemptIntervalFrames" to 410),
            "reference" to mapOf(
                "groupOrderFrames" to 600,
                "productionAttemptsPerCycle" to mapOf("value" to 6),
                "attackCreditThresholds" to mapOf("lowScore" to 2.5),
            ),
        ))
        assertEquals(100f, v3.originalTuning.upgradeInterval())
        assertEquals(410f, v3.originalTuning.buildingInterval())
        assertEquals(600, v3.originalTuning.groups().order())
        assertEquals(6, v3.originalTuning.production().attempts())
        assertTrue(v3.originalTuning.production().permits(300.0, 2.5f))
    }

    @Test
    fun `v3 rejects unreachable production and unsafe staging thresholds`() {
        assertFailsWith<IllegalArgumentException> {
            AiRlConfig.fromDocument(mapOf("schema" to "rwx-rl-ai-v3",
                "reference" to mapOf("reclaimScoreCap" to 2.5)))
        }
        assertFailsWith<IllegalArgumentException> {
            AiRlConfig.fromDocument(mapOf("schema" to "rwx-rl-ai-v3",
                "tactics" to mapOf("stagingDistance" to 449)))
        }
    }
}
