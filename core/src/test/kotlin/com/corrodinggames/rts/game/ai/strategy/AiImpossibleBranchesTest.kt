package com.corrodinggames.rts.game.ai.strategy

import kotlin.test.*

/**
 * 锁定 [AiImpossibleBranches] 的默认值 = 原版 Impossible 的字面量（手抄自
 * `AIController` / `BaseZone` 的 isInsaneDifficulty 分支）。
 */
class AiImpossibleBranchesTest {

    @Test
    fun `defaults are the original impossible numbers`() {
        val branches = AiImpossibleBranches()
        assertFalse(branches.isEnabled())
        assertEquals(4f, branches.globalTimerExtraDecay(), 1e-6f)
        assertEquals(10, branches.builderGroupMaxUnits())
        assertEquals(14, branches.attackGroupMaxUnits(9))
        assertEquals(18, branches.attackGroupMaxUnits(30))
        assertEquals(10, branches.seaGroupMaxUnits())
        assertEquals(190f, branches.defensiveScoreBase(), 1e-6f)
        assertEquals(16, branches.productionWaterUnitsLimit())
        assertEquals(65, branches.productionIdleUnitsLimit())
    }

    @Test
    fun `the shared original preset stays disabled`() {
        assertFalse(AiImpossibleBranches.ORIGINAL.isEnabled())
        assertEquals(10, AiImpossibleBranches.ORIGINAL.builderGroupMaxUnits())
    }

    @Test
    fun `enable is the only switch`() {
        val branches = AiImpossibleBranches()
        assertFalse(branches.isEnabled())
        assertSame(branches, branches.enable())
        assertTrue(branches.isEnabled())
        branches.setEnabled(false)
        assertFalse(branches.isEnabled())
    }

    @Test
    fun `a subclass only replaces the numbers it touches`() {
        val veterans = AiImpossibleBranches.Veterans()
        assertTrue(veterans.isEnabled())
        assertEquals(150f, veterans.defensiveScoreBase(), 1e-6f)
        assertEquals(12, veterans.builderGroupMaxUnits())
        // 没覆写的仍沿用原版 Impossible
        assertEquals(18, veterans.attackGroupMaxUnits(30))
        assertEquals(65, veterans.productionIdleUnitsLimit())
    }
}

