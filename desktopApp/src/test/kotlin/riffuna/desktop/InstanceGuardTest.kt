package riffuna.desktop
import kotlin.test.*
import java.nio.file.*
class InstanceGuardTest {
    @Test fun duplicateInstanceIsRefusedAndLockIsReleased() {
        val data=Files.createTempDirectory("riffuna-instance-test")
        val first=InstanceGuard.acquire(data);assertNotNull(first)
        assertNull(InstanceGuard.acquire(data));first.close()
        assertFalse(Files.exists(data.resolve("instance.lock")))
        InstanceGuard.acquire(data)!!.close()
    }
}
