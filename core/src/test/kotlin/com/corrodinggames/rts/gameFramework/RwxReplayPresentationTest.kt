package com.corrodinggames.rts.gameFramework

import kotlin.test.Test
import kotlin.test.assertEquals

/**
 * 回放终局块的线格式：录制端写 rollout 的 `Outcome.wire`（victory/defeat/max-ticks/wall-limit），
 * 播放端由 `Outcome.fromWire` 还原。两边是同一份协议，改一边必须改另一边。
 */
class RwxReplayPresentationTest {
    @Test
    fun outcomeWireRoundTrip() {
        assertEquals(RwxReplayPresentation.Outcome.VICTORY, RwxReplayPresentation.Outcome.fromWire("victory"))
        assertEquals(RwxReplayPresentation.Outcome.DEFEAT, RwxReplayPresentation.Outcome.fromWire("defeat"))
        // 未决出的对局（打满 tick / 墙钟上限）录制时就写这两个值，播放显示平局。
        assertEquals(RwxReplayPresentation.Outcome.STALEMATE, RwxReplayPresentation.Outcome.fromWire("max-ticks"))
        assertEquals(RwxReplayPresentation.Outcome.STALEMATE, RwxReplayPresentation.Outcome.fromWire("wall-limit"))
        // 仍在进行、或旧版本写坏的值都不参与判定。
        assertEquals(RwxReplayPresentation.Outcome.NONE, RwxReplayPresentation.Outcome.fromWire("active"))
        assertEquals(RwxReplayPresentation.Outcome.NONE, RwxReplayPresentation.Outcome.fromWire("nonsense"))
    }
}
