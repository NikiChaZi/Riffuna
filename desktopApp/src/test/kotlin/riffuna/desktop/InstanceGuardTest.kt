package riffuna.desktop

import java.nio.file.*
import kotlin.test.*

class InstanceGuardTest {
    @Test
    fun duplicateInstanceIsRefusedAndLockIsReleased() {
        val data = Files.createTempDirectory("riffuna-instance-test")
        val first = assertNotNull(InstanceGuard.acquire(data))
        try {
            assertNull(InstanceGuard.acquire(data))
        } finally {
            first.close()
        }
        // Reuse the same file to avoid unlink races between exiting and starting instances.
        assertTrue(Files.exists(data.resolve("instance.lock")))
        assertNotNull(InstanceGuard.acquire(data)).close()
    }

    @Test
    fun staleLockWithReusedLivePidDoesNotBlockStartup() {
        val data = Files.createTempDirectory("riffuna-reused-pid-test")
        Files.writeString(
            data.resolve("instance.lock"),
            "${ProcessHandle.current().pid()}\nRiffuna\nold-host\n",
        )
        assertNotNull(InstanceGuard.acquire(data)).use { assertNull(InstanceGuard.acquire(data)) }
    }

    @Test
    fun emptyOrMalformedStaleLockDoesNotBlockStartup() {
        for (contents in listOf("", "not-a-pid\nRiffuna\n")) {
            val data = Files.createTempDirectory("riffuna-stale-lock-test")
            Files.writeString(data.resolve("instance.lock"), contents)
            assertNotNull(InstanceGuard.acquire(data)).close()
            assertEquals(
                ProcessHandle.current().pid().toString(),
                Files.readAllLines(data.resolve("instance.lock")).first(),
            )
        }
    }
}
