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

    /** 第 8 条：开关默认跟着 takeover 走，关掉接管就等于原版。 */
    @Test
    fun `experimental factory switch follows takeover by default`() {
        assertFalse(AiImpossibleBranches.ORIGINAL.experimentalLandFactoryUnlocked(), "原版实例永远不开")
        val on = AiImpossibleBranches().enable()
        assertTrue(on.experimentalLandFactory(), "默认值就是 true")
        assertTrue(on.experimentalLandFactoryUnlocked(), "takeover 打开 → 开关默认跟着打开")
        on.setExperimentalLandFactory(false)
        assertFalse(on.experimentalLandFactoryUnlocked(), "显式关掉后即使 takeover 打开也不生效")
    }

    /** 第 8 条：只补「难度门槛」这一个条件，分数/资金门槛/核弹全部保持原版。 */
    @Test
    fun `switch only opens the vanilla experimental factory branch`() {
        val table = AiBuildingScoreTable().enable()
        fun env(credits: Double) = AiBuildingScoreTable.Env().apply {
            this.credits = credits
            wideAntiAir = false
            hardOrAbove = false // 故意设成不满足难度（Hard 就是这种）
            pathfindingOverloaded = false
            nukesAllowed = true
            experimentalLandFactory = true
            resourceProbe = AiBuildingScoreTable.ResourceProbe { false }
        }
        // 难度不满足但开关打开 → 原版分数 0.04（= experimentalFirst 默认值）
        assertEquals(0.04f, table.score(env(20000.0), UnitTypeEnum.experimentalLandFactory, false, 0, 0, 0), 1e-6f)
        // 资金门槛仍是原版 15000
        assertTrue(table.score(env(10000.0), UnitTypeEnum.experimentalLandFactory, false, 0, 0, 0) < 0f)
        // 开关关掉 → 难度不满足就还是进不去
        assertTrue(table.score(env(20000.0).apply { experimentalLandFactory = false },
                UnitTypeEnum.experimentalLandFactory, false, 0, 0, 0) < 0f)
        // 核弹发射井没有任何分支：钱再多也不打分
        assertTrue(table.score(env(200000.0), UnitTypeEnum.NukeLaucher, false, 0, 0, 0) < 0f, "核弹不在本开关范围内")
    }
}
