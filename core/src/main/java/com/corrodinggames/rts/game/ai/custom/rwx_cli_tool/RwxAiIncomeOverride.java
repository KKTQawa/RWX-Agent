package com.corrodinggames.rts.game.ai.custom.rwx_cli_tool;

import java.util.Locale;

/**
 * 评测用的“经济倍率覆盖”开关：默认不启用，内置 AI 的难度加成（Hard=1.4、Very Hard=1.8 …）照常生效。
 *
 * <p>完整对局评测里，被测一方可能是脚本 AI；它的定义里带着难度经济加成，而人类/agent 的对照局只有
 * 房间倍率。要让基线局和 54 局对照可比，可以显式覆盖成 1.0：
 * <pre>java … -Drwx.ai.incomeMultiplier=1.0 …</pre>
 * 只作用于<b>本地玩家那一队</b>（{@code engine.playerTeam}），对手的内置加成保持原样。
 * 取值必须是有限正数；非法值只警告一次并按“不覆盖”处理，绝不让一场对局因为评测开关崩掉。</p>
 */
public final class RwxAiIncomeOverride {
    public static final String PROPERTY = "rwx.ai.incomeMultiplier";

    private static boolean warned;

    private RwxAiIncomeOverride() { }

    /** 返回最终倍率：属性未设置/非法时原样返回 {@code definitionMultiplier}。 */
    public static float apply(float definitionMultiplier) {
        String text = System.getProperty(PROPERTY);
        if (text == null || text.isBlank()) return definitionMultiplier;
        try {
            float value = Float.parseFloat(text.trim());
            if (Float.isFinite(value) && value > 0.0f && value <= 100.0f) return value;
        } catch (NumberFormatException ignored) {
            // 落到下面的警告
        }
        if (!warned) {
            warned = true;
            System.out.println(String.format(Locale.ROOT,
                    "RWX_AI_INCOME_OVERRIDE_IGNORED value=%s（需要 0 < 倍率 <= 100 的数字，按不覆盖处理）", text));
        }
        return definitionMultiplier;
    }
}
