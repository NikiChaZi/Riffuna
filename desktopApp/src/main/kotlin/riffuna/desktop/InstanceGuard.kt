package riffuna.desktop

import java.nio.ByteBuffer
import java.nio.channels.FileChannel
import java.nio.channels.FileLock
import java.nio.channels.OverlappingFileLockException
import java.nio.file.*

/** The operating-system lock, rather than a reusable process ID, determines ownership. */
class InstanceGuard
private constructor(private val channel: FileChannel, private val lock: FileLock) : AutoCloseable {
    override fun close() {
        try {
            lock.release()
        } finally {
            channel.close()
        }
        // Keep the inode: unlinking after unlock can let two processes lock different files.
    }

    companion object {
        fun acquire(directory: Path): InstanceGuard? {
            Files.createDirectories(directory)
            val channel =
                FileChannel.open(
                    directory.resolve("instance.lock"),
                    StandardOpenOption.CREATE,
                    StandardOpenOption.READ,
                    StandardOpenOption.WRITE,
                )
            try {
                val lock =
                    try {
                        channel.tryLock()
                    } catch (_: OverlappingFileLockException) {
                        null
                    }
                if (lock == null) {
                    channel.close()
                    return null
                }
                val contents =
                    "${ProcessHandle.current().pid()}\nRiffuna\n${System.getenv("COMPUTERNAME") ?: "localhost"}\n"
                channel.truncate(0)
                channel.write(ByteBuffer.wrap(contents.toByteArray(Charsets.UTF_8)))
                channel.force(true)
                return InstanceGuard(channel, lock)
            } catch (e: Exception) {
                channel.close()
                throw e
            }
        }
    }
}
