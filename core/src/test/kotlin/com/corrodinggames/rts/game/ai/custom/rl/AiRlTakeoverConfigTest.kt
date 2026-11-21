package com.corrodinggames.rts.game.ai.custom.rl

import com.corrodinggames.rts.game.ai.strategy.AiBuildingScoreTable
import com.corrodinggames.rts.game.ai.strategy.AiImpossibleBranches
import com.corrodinggames.rts.game.units.UnitTypeEnum
import io.github.rwx.app.MicroJson
import java.nio.file.Files
import kotlin.test.*

/**
 * 锁定「配置 → 接管对象」这条链：`buildingScore` / `impossible` 段能落到
 * [AiBuildingScoreTable] 与 [AiImpossibleBranches] 的字段上，段缺失时保持原版行为。
 */
class AiRlTakeoverConfigTest {

    private fun configOf(json: String): AiRlConfig {
        val file = Files.createTempFile("rwx-ai-config", ".json")
        file.toFile().writeText(json.trimIndent(), Charsets.UTF_8)
        return AiRlConfig.fromDocument(MicroJson.read(file))
    }

    private val base = """
        {
          "meta": {"baseDifficulty": 1},
          "definition": {"cadence": {"economy": 25, "tactics": 80, "strategy": 250}},
          "units": {"weights": {"c_tank": 1.0}}
        }
    """

    @Test
    fun `missing sections keep the original behaviour`() {
        val cfg = configOf(base)
        assertFalse(cfg.buildingScoresEnabled)
        assertFalse(cfg.impossibleEnabled)
        assertNull(cfg.buildingScoreTable(), "段缺失时必须返回 null（原版 if 链）")
        assertSame(AiImpossibleBranches.ORIGINAL, cfg.impossibleBranches(), "段缺失时必须返回共享的原版实例")
    }

    @Test
    fun `building score values reach the table`() {
        val cfg = configOf(
            """
            {
              "meta": {"baseDifficulty": 1},
              "definition": {"cadence": {"economy": 25, "tactics": 80, "strategy": 250}},
              "buildingScore": {
                "enabled": true,
                "turretFirst": {"value": 0.71, "min": 0.2, "max": 0.9},
                "landFactoryFirst": {"value": 0.66, "min": 0.35, "max": 0.95},
                "experimentalFirst": {"value": 0.09, "min": 0.02, "max": 0.2}
              }
            }
            """
        )
        val table = assertNotNull(cfg.buildingScoreTable())
        assertTrue(table.isEnabled())
        val env = AiBuildingScoreTable.Env().apply {
            credits = 100.0
            wideAntiAir = false
            hardOrAbove = true
            pathfindingOverloaded = false
            nukesAllowed = true
            resourceProbe = AiBuildingScoreTable.ResourceProbe { false }
        }
        assertEquals(0.71f, table.score(env, UnitTypeEnum.turret, false, 0, 0, 5), 1e-6f)
    }

    @Test
    fun `impossible branches round ints and keep floats`() {
        val cfg = configOf(
            """
            {
              "meta": {"baseDifficulty": 1},
              "definition": {"cadence": {"economy": 25, "tactics": 80, "strategy": 250}},
              "impossible": {
                "enabled": true,
                "globalTimerExtraDecay": {"value": 2.5},
                "builderGroupMaxUnits": {"value": 7.4},
                "attackGroupMaxUnitsNarrow": {"value": 11.6},
                "attackGroupMaxUnitsWide": {"value": 20},
                "seaGroupMaxUnits": {"value": 8},
                "defensiveScoreBase": {"value": 240},
                "productionIdleUnitsLimit": {"value": 70},
                "productionWaterUnitsLimit": {"value": 18}
              }
            }
            """
        )
        val branches = cfg.impossibleBranches()
        assertTrue(branches.isEnabled())
        assertEquals(2.5f, branches.globalTimerExtraDecay(), 1e-6f)
        assertEquals(7, branches.builderGroupMaxUnits(), "int 旋钮应四舍五入")
        assertEquals(12, branches.attackGroupMaxUnits(20), "窄图用 narrow")
        assertEquals(20, branches.attackGroupMaxUnits(30), "宽图用 wide")
        assertEquals(8, branches.seaGroupMaxUnits())
        assertEquals(240f, branches.defensiveScoreBase(), 1e-6f)
        assertEquals(70, branches.productionIdleUnitsLimit())
        assertEquals(18, branches.productionWaterUnitsLimit())
    }

    @Test
    fun `unknown knobs are ignored instead of throwing`() {
        val cfg = configOf(
            """
            {
              "meta": {"baseDifficulty": 1},
              "definition": {"cadence": {"economy": 25, "tactics": 80, "strategy": 250}},
              "buildingScore": {"enabled": true, "notAKnob": {"value": 1.0}},
              "impossible": {"enabled": true, "alsoNotAKnob": {"value": 3}}
            }
            """
        )
        assertNotNull(cfg.buildingScoreTable())
        assertTrue(cfg.impossibleBranches().isEnabled())
        // 未知项被忽略 → 仍然全是原版字面量
        assertEquals(0.47f, cfg.buildingScoreTable()!!.let { t ->
            val env = AiBuildingScoreTable.Env().apply {
                credits = 0.0; wideAntiAir = false; hardOrAbove = false
                pathfindingOverloaded = false; nukesAllowed = true
                resourceProbe = AiBuildingScoreTable.ResourceProbe { false }
            }
            t.score(env, UnitTypeEnum.turret, false, 0, 0, 5)
        }, 1e-6f)
        assertEquals(190f, cfg.impossibleBranches().defensiveScoreBase(), 1e-6f)
    }
}
