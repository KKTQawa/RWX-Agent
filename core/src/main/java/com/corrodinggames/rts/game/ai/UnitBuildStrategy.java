package com.corrodinggames.rts.game.ai;

import com.corrodinggames.rts.game.units.UnitMovementType;
import com.corrodinggames.rts.game.units.UnitType;
import com.corrodinggames.rts.game.units.UnitTypeEnum;
import com.corrodinggames.rts.gameFramework.GameEngine;
import com.corrodinggames.rts.gameFramework.Utility;

import java.util.ArrayList;
import java.util.Collections;
import java.util.Iterator;

/* JADX INFO: renamed from: com.corrodinggames.rts.game.a.d */
/* JADX INFO: loaded from: game-lib.jar:com/corrodinggames/rts/game/a/d.class */
public abstract class UnitBuildStrategy {

    /* JADX INFO: renamed from: b */
    String strategyName;

    /* JADX INFO: renamed from: c */
    public ArrayList<UnitBuildPriority> unitPriorities = new ArrayList();

    /* JADX INFO: renamed from: a */
    private ArrayList shuffledUnits = new ArrayList();

    /* JADX INFO: renamed from: d */
    final /* synthetic */ AIController aiController;

    /* JADX INFO: renamed from: a */
    public abstract boolean canBuildUnit(UnitType unitType);

    public UnitBuildStrategy(AIController aIController, String str) {
        this.aiController = aIController;
        this.strategyName = str;
        aIController.debugMessages.add(this);
    }

    /* JADX INFO: renamed from: b */
    public boolean hasUnitPriority(UnitType unitType) {
        Iterator it = this.unitPriorities.iterator();
        while (it.hasNext()) {
            if (((UnitBuildPriority) it.next()).unitType == unitType) {
                return true;
            }
        }
        return false;
    }

    /**
     * RWX：配置权重覆盖（单位内部 id 小写 → 权重）。为空时与原版完全一致（全体 10.0）。
     *
     * <p>只影响“在候选里选哪一个”，过滤（移动类型配比）、资金门槛、空闲节流、寻路规避、
     * 候选采样仍然由原版 {@code BaseZone.tryBuildCombatUnits} 负责，所以这些数值是唯一变量。</p>
     */
    private java.util.Map<String, Float> rwxWeightOverride = java.util.Collections.emptyMap();

    public void rwxSetWeightOverride(java.util.Map<String, Float> weights) {
        this.rwxWeightOverride = weights == null ? java.util.Collections.emptyMap() : weights;
        rebuildUnitMix();
    }

    /* JADX INFO: renamed from: c */
    public float getUnitPriority(UnitType unitType) {
        if (!this.rwxWeightOverride.isEmpty() && unitType != null) {
            Float weight = this.rwxWeightOverride.get(unitType.v().toLowerCase(java.util.Locale.ROOT));
            if (weight != null) {
                // 权重是**相对原版 10.0 的倍率**，不是绝对值：1.0 = 与原版同权，
                // 未被配置覆盖的单位仍是 10.0。这样全 1.0 的策略表与原版逐位等价。
                return Math.max(0.0f, weight) * 10.0f;
            }
        }
        return 10.0f;
    }

    /* JADX INFO: renamed from: a */
    public ArrayList getShuffledUnits() {
        Collections.shuffle(this.shuffledUnits);
        return this.shuffledUnits;
    }

    /** Preserve the ordinary shuffle when the builder pool has equal priorities. */
    ArrayList<UnitBuildPriority> rwxWeightedBuildOrder() {
        if (this.unitPriorities.size() < 2) return getShuffledUnits();
        float first = this.unitPriorities.get(0).priority;
        if (this.unitPriorities.stream().allMatch(entry -> entry.priority == first)) return getShuffledUnits();

        ArrayList<UnitBuildPriority> remaining = new ArrayList<>(this.unitPriorities);
        ArrayList<UnitBuildPriority> ordered = new ArrayList<>(remaining.size());
        while (!remaining.isEmpty()) {
            float total = 0;
            for (UnitBuildPriority entry : remaining) total += entry.priority;
            float draw = Utility.randomFloatInRange(0f, total);
            int index = 0;
            while (index < remaining.size() - 1 && draw >= remaining.get(index).priority) {
                draw -= remaining.get(index).priority;
                index++;
            }
            ordered.add(remaining.remove(index));
        }
        return ordered;
    }

    /* JADX INFO: renamed from: b */
    public void rebuildUnitMix() {
        this.unitPriorities = new ArrayList();
        float f = 0.0f;
        for (UnitType unitType : UnitTypeEnum.ae) {
            if (canBuildUnit(unitType)) {
                float unitPriority = getUnitPriority(unitType);
                f += unitPriority;
                this.unitPriorities.add(new UnitBuildPriority(this, unitType, unitPriority));
            }
        }
        this.shuffledUnits = new ArrayList(this.unitPriorities);
        if (this.unitPriorities.size() == 0) {
            GameEngine.log("AI: rebuildUnitMix: no units in unitMix:" + this.strategyName);
        }
        rwxDumpUnitMix();
    }

    /**
     * RWX 诊断（默认关，`-Drwx.rl.dumpMix=true` 打开）：打印这个策略真正能选的兵种及权重。
     *
     * <p>用来核对配置里的 weight 键是否真的落到了某个可生产单位上：权重表不是白名单，
     * 没写进去的单位仍然是原版 10.0，照样会被生产。这里把每个 id 的实际取值一起打出来。</p>
     */
    private void rwxDumpUnitMix() {
        if (!Boolean.getBoolean("rwx.rl.dumpMix")) {
            return;
        }
        StringBuilder sb = new StringBuilder();
        for (Object item : this.unitPriorities) {
            UnitBuildPriority priority = (UnitBuildPriority) item;
            if (sb.length() > 0) {
                sb.append(", ");
            }
            sb.append(priority.unitType.v()).append('=').append(priority.priority);
        }
        System.out.println("RWX_RL_MIX " + this.strategyName
                + " n=" + this.unitPriorities.size()
                + " overridden=" + this.rwxWeightOverride.size()
                + " units=[" + sb + "]");
    }

    /* JADX INFO: renamed from: c */
    public UnitType getRandomUnitType() {
        return getRandomUnitTypeWithPrice((UnitMovementType) null, -1);
    }

    /* JADX INFO: renamed from: a */
    public UnitType getRandomUnitTypeByMovement(UnitMovementType unitMovementType) {
        return getRandomUnitTypeWithPrice(unitMovementType, -1);
    }

    /* JADX INFO: renamed from: a */
    public boolean matchesMovementType(UnitType unitType, UnitMovementType unitMovementType) {
        if (unitMovementType == null) {
            return true;
        }
        UnitMovementType unitMovementTypeO = unitType.o();
        if (unitMovementTypeO == UnitMovementType.OVER_CLIFF) {
            unitMovementTypeO = UnitMovementType.LAND;
        }
        if (unitMovementTypeO == UnitMovementType.OVER_CLIFF_WATER) {
            unitMovementTypeO = UnitMovementType.HOVER;
        }
        if (unitMovementTypeO == unitMovementType) {
            return true;
        }
        return false;
    }

    /* JADX INFO: renamed from: a */
    public UnitType getRandomUnitTypeWithPrice(UnitMovementType unitMovementType, int i) {
        if (this.unitPriorities.size() == 0) {
            GameEngine.log("AI: getRandomUnitType: no units in unitMix:" + this.strategyName);
            return null;
        }
        float f = 0.0f;
        int i2 = 0;
        for (UnitBuildPriority unitBuildPriority : this.unitPriorities) {
            if (matchesMovementType(unitBuildPriority.unitType, unitMovementType) && (i == -1 || unitBuildPriority.unitType.c() <= i)) {
                f += unitBuildPriority.priority;
                i2++;
            }
        }
        if (i2 == 0) {
            return null;
        }
        float fRandomFloatInRange = Utility.randomFloatInRange(0.0f, f);
        float f2 = 0.0f;
        for (UnitBuildPriority unitBuildPriority2 : this.unitPriorities) {
            if (matchesMovementType(unitBuildPriority2.unitType, unitMovementType) && (i == -1 || unitBuildPriority2.unitType.c() <= i)) {
                f2 += unitBuildPriority2.priority;
                if (f2 > fRandomFloatInRange) {
                    return unitBuildPriority2.unitType;
                }
            }
        }
        GameEngine.log("Did not find getRandomUnit, this should only happen very rarely, name:" + this.strategyName + " unitMix.size:" + this.unitPriorities.size() + " minPrice:" + i + " movementType:" + unitMovementType + " totalUnits:" + i2);
        return ((UnitBuildPriority) this.unitPriorities.get(this.unitPriorities.size() - 1)).unitType;
    }
}
