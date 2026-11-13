package com.corrodinggames.rts.game.ai.custom.micro

import com.corrodinggames.rts.game.ai.custom.rwx_cli_tool.RwxCliCommands.Command
import kotlin.test.*

class MicroLobbyTest {
    /** The lobby is process-wide by design; a unit test has to release it explicitly. */
    private fun clearLobby() {
        MicroRuntime::class.java.getDeclaredField("lobby").apply { isAccessible = true }.set(null, null)
    }

    @Test
    fun `a lobby defers the case and accepts only status enter and ping`() {
        clearLobby()
        try {
            val out = System.getProperty("java.io.tmpdir").replace('\\', '/')
            MicroRuntime.configureLobby("CASE1-duel", "task=1_1_3,seed=1,track=realtime,out=$out", null)
            assertTrue(MicroRuntime.lobbyActive())
            assertNull(MicroRuntime.current())
            assertEquals("ok: micro lobby case=CASE1-duel phase=lobby",
                MicroRuntime.execute(Command.MICRO_LOBBY_STATUS, emptyList()))
            for (command in listOf(Command.PING, Command.MICRO_LOBBY_STATUS, Command.MICRO_LOBBY_ENTER)) {
                assertTrue(MicroRuntime.allowed(command), "$command must be accepted in the lobby")
            }
            for (command in listOf(Command.MICRO_STATE, Command.MICRO_BEGIN, Command.MAP_SHOW)) {
                assertFalse(MicroRuntime.allowed(command), "$command must wait for the entered case")
            }
            assertTrue(MicroRuntime.execute(Command.MICRO_STATE, emptyList()).startsWith("error:"))
            // Without an app-installed transition hook the entry fails and the lobby stays usable.
            assertTrue(MicroRuntime.execute(Command.MICRO_LOBBY_ENTER, emptyList()).startsWith("error:"))
            assertTrue(MicroRuntime.lobbyActive())
            assertEquals("ok: micro lobby case=CASE1-duel phase=lobby",
                MicroRuntime.execute(Command.MICRO_LOBBY_STATUS, emptyList()))
        } finally {
            clearLobby()
        }
    }
}
