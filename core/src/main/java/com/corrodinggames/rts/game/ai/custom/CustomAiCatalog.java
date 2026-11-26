package com.corrodinggames.rts.game.ai.custom;

import com.corrodinggames.rts.game.ai.custom.rl.AiRlHardStrategy;
import com.corrodinggames.rts.game.ai.custom.ai_autopilot.CustomAiAuto_PilotStrategy;
import com.corrodinggames.rts.game.ai.custom.ai_s.CustomAiSStrategy;
import com.corrodinggames.rts.game.ai.custom.easy_1income.CustomEasy1IncomeStrategy;
import com.corrodinggames.rts.game.ai.custom.hard_1income.CustomHard1IncomeStrategy;
import com.corrodinggames.rts.game.ai.custom.high.CustomHighAiStrategy;
import com.corrodinggames.rts.game.ai.custom.impossible_1income.CustomImpossible1IncomeStrategy;
import com.corrodinggames.rts.game.ai.custom.medium_1income.CustomMedium1IncomeStrategy;
import com.corrodinggames.rts.game.ai.custom.very_easy_1income.CustomVeryEasy1IncomeStrategy;
import com.corrodinggames.rts.game.ai.custom.very_hard_1income.CustomVeryHard1IncomeStrategy;
import com.corrodinggames.rts.game.ai.strategy.AiDefinition;

import java.util.List;

/** Add each new AI here. Its metadata and implementation stay together under this directory. */
public final class CustomAiCatalog {
    private CustomAiCatalog() { }

    public static List<AiDefinition> definitions() {
        return List.of(
                CustomHighAiStrategy.definition(),
                CustomAiAuto_PilotStrategy.definition(),
                CustomAiSStrategy.definition(),
                com.corrodinggames.rts.game.ai.custom.rsi_sdk.RsiHost.definition(),
                // RSI-1：同一宿主，策略来自 ai_d/ 实验目录（经济倍率 1.0，与 *_1income 系列同档）。
                com.corrodinggames.rts.game.ai.custom.rsi_sdk.RsiHost.definition(22, "rwx.ai-rsi-1",
                        "RSI-test1", "RSI-test1", com.corrodinggames.rts.game.ai.custom.ai_d.AiRsiOne::new),
                // 原版六档的“行为全继承 + 收入统一 ×1”版本，按难度从低到高排列（编号 8..13）。
                CustomVeryEasy1IncomeStrategy.definition(),
                CustomEasy1IncomeStrategy.definition(),
                CustomMedium1IncomeStrategy.definition(),
                CustomHard1IncomeStrategy.definition(),
                CustomVeryHard1IncomeStrategy.definition(),
                CustomImpossible1IncomeStrategy.definition(),
                com.corrodinggames.rts.game.ai.custom.micro.case1.Case1EnemyStrategy.definition(),
                // 两个可配置预设默认使用同一份 v1 交付模型。
                AiRlHardStrategy.definition(),
                AiRlHardStrategy.definitionSecond(),
                AiRlHardStrategy.definitionV2(),
                AiRlHardStrategy.definitionV3()
        );
    }
}
