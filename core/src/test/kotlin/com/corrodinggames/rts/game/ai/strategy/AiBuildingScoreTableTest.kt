package com.corrodinggames.rts.game.ai.strategy

import com.corrodinggames.rts.game.units.UnitType
import com.corrodinggames.rts.game.units.UnitTypeEnum
import kotlin.test.*

/**
 * 锁定 [AiBuildingScoreTable] 的默认值 = 原版 `BaseZone.getBestBuildingToBuild` 的字面量。
 * 期望值按原版源码手算，不复制实现，改表时这里会先炸。
 */
class AiBuildingScoreTableTest {

    private fun env(
        credits: Double = 0.0,
        wideAntiAir: Boolean = false,
        hard: Boolean = false,
        pathing: Boolean = false,
        nukes: Boolean = true,
        resource: Boolean = false,
    ): AiBuildingScoreTable.Env {
        val env = AiBuildingScoreTable.Env()
        env.credits = credits
        env.wideAntiAir = wideAntiAir
        env.hardOrAbove = hard
        env.pathfindingOverloaded = pathing
        env.nukesAllowed = nukes
        env.resourceProbe = AiBuildingScoreTable.ResourceProbe { resource }
        return env
    }

    private fun score(env: AiBuildingScoreTable.Env, type: UnitType, count: Int, assign: Int, air: Int = 5) =
        AiBuildingScoreTable().score(env, type, false, count, assign, air)

    @Test
    fun `table is opt in and defaults to the original numbers`() {
        val table = AiBuildingScoreTable()
        assertFalse(table.isEnabled())
        assertTrue(AiBuildingScoreTable.TurretHeavy().isEnabled())
    }

    @Test
    fun landFactory() {
        assertEquals(0.80f, score(env(), UnitTypeEnum.landFactory, 0, 0), 1e-6f)
        assertEquals(0.46f / (2 + 1 * 2), score(env(), UnitTypeEnum.landFactory, 1, 2), 1e-6f)
        // assign>=5 且已有空军时不再加陆工厂
        assertEquals(-2.0f, score(env(), UnitTypeEnum.landFactory, 1, 5), 1e-6f)
        // ...但没有空军产出能力时守卫放行
        assertEquals(0.46f / (5 + 1 * 2), score(env(), UnitTypeEnum.landFactory, 1, 5, air = 0), 1e-6f)
    }

    @Test
    fun airFactory() {
        assertEquals(0.48f, score(env(), UnitTypeEnum.airFactory, 0, 0), 1e-6f)
        assertEquals(0.29f / (1 + 1), score(env(), UnitTypeEnum.airFactory, 1, 1), 1e-6f)
        assertEquals(-2.0f, score(env(), UnitTypeEnum.airFactory, 2, 1), 1e-6f)
    }

    @Test
    fun seaFactoryNeedsPathfindingOverload() {
        assertEquals(-2.0f, score(env(), UnitTypeEnum.seaFactory, 0, 0), 1e-6f)
        assertEquals(0.30f, score(env(pathing = true), UnitTypeEnum.seaFactory, 0, 0), 1e-6f)
    }

    @Test
    fun turretTiers() {
        assertEquals(0.47f, score(env(), UnitTypeEnum.turret, 0, 0), 1e-6f)
        assertEquals(0.35f, score(env(), UnitTypeEnum.turret, 1, 0), 1e-6f)
        assertEquals(0.025f / 3, score(env(), UnitTypeEnum.turret, 3, 0), 1e-6f)
        assertEquals(-2.0f, score(env(), UnitTypeEnum.turret, 4, 0), 1e-6f)
    }

    @Test
    fun oneOffBuildings() {
        assertEquals(0.018f, score(env(), UnitTypeEnum.laserDefence, 0, 0), 1e-6f)
        assertEquals(-2.0f, score(env(), UnitTypeEnum.laserDefence, 1, 0), 1e-6f)
        assertEquals(0.02f, score(env(), UnitTypeEnum.repairbay, 0, 0), 1e-6f)
    }

    @Test
    fun antiAirSkipsWithoutTheWideGateAndAllowsFourWithIt() {
        assertEquals(0.42f, score(env(), UnitTypeEnum.antiAirTurret, 0, 0), 1e-6f)
        assertEquals(0.30f / 2, score(env(), UnitTypeEnum.antiAirTurret, 2, 0), 1e-6f)
        assertEquals(0.02f / 3, score(env(), UnitTypeEnum.antiAirTurret, 3, 0), 1e-6f)
        assertEquals(-2.0f, score(env(), UnitTypeEnum.antiAirTurret, 4, 0), 1e-6f)
        assertEquals(0.30f / 3, score(env(wideAntiAir = true), UnitTypeEnum.antiAirTurret, 3, 0), 1e-6f)
        assertEquals(-2.0f, score(env(wideAntiAir = true), UnitTypeEnum.antiAirTurret, 4, 0), 1e-6f)
    }

    @Test
    fun fabricator() {
        assertEquals(-2.0f, score(env(credits = 1000.0), UnitTypeEnum.fabricator, 0, 0), 1e-6f)
        assertEquals(0.11f, score(env(credits = 3000.0), UnitTypeEnum.fabricator, 0, 0), 1e-6f)
        assertEquals(0.07f / (0.2f * 3 + 2), score(env(credits = 3000.0), UnitTypeEnum.fabricator, 2, 3), 1e-6f)
        assertEquals(-2.0f, score(env(credits = 3000.0), UnitTypeEnum.fabricator, 5, 0), 1e-6f)
    }

    @Test
    fun antiNuke() {
        assertEquals(0.06f, score(env(credits = 5000.0), UnitTypeEnum.AntiNukeLaucher, 0, 0), 1e-6f)
        assertEquals(0.05f / (2 + 0 * 2), score(env(credits = 5000.0), UnitTypeEnum.AntiNukeLaucher, 0, 2), 1e-6f)
        assertEquals(-2.0f, score(env(credits = 5000.0, nukes = false), UnitTypeEnum.AntiNukeLaucher, 0, 0), 1e-6f)
        assertEquals(-2.0f, score(env(credits = 5000.0), UnitTypeEnum.AntiNukeLaucher, 0, 4), 1e-6f)
    }

    @Test
    fun experimentalLandFactoryNeedsHardAndCredits() {
        assertEquals(-2.0f, score(env(credits = 20000.0), UnitTypeEnum.experimentalLandFactory, 0, 0), 1e-6f)
        assertEquals(0.04f, score(env(credits = 20000.0, hard = true), UnitTypeEnum.experimentalLandFactory, 0, 0), 1e-6f)
        assertEquals(0.03f, score(env(credits = 60000.0, hard = true), UnitTypeEnum.experimentalLandFactory, 0, 1), 1e-6f)
    }

    @Test
    fun resourcePoolBuildingIsExcludedWithoutAResourceTile() {
        // 采掘器依赖 findClosestResource()，这里只验证“没有资源点 → 排除”，不去碰那个随机数。
        assertEquals(-2.0f, score(env(resource = false), UnitTypeEnum.extractor, 0, 0), 1e-6f)
    }

    @Test
    fun subclassOnlyReplacesNumbers() {
        val heavy = AiBuildingScoreTable.TurretHeavy()
        assertEquals(0.60f, scoreOf(heavy, UnitTypeEnum.turret, 0, 0), 1e-6f)
        assertEquals(0.50f, scoreOf(heavy, UnitTypeEnum.antiAirTurret, 0, 0), 1e-6f)
        // 其它分支的数字没动
        assertEquals(0.80f, scoreOf(heavy, UnitTypeEnum.landFactory, 0, 0), 1e-6f)
    }

    private fun scoreOf(table: AiBuildingScoreTable, type: UnitType, count: Int, assign: Int) =
        table.score(env(), type, false, count, assign, 5)
}
