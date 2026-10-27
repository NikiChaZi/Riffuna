package riffuna.desktop

import java.nio.ByteBuffer
import java.nio.channels.FileChannel
import java.nio.channels.FileLock
import java.nio.file.*

/** Uses the legacy Qt lock path too, to prevent two writers of queue/settings. */
class InstanceGuard private constructor(private val path:Path,private val channel:FileChannel,private val lock:FileLock):AutoCloseable {
    override fun close(){lock.release();channel.close();Files.deleteIfExists(path)}
    companion object {
        fun acquire(directory:Path):InstanceGuard? {
            Files.createDirectories(directory)
            val path=directory.resolve("instance.lock")
            repeat(2){
                val channel=try{FileChannel.open(path,StandardOpenOption.CREATE_NEW,StandardOpenOption.READ,StandardOpenOption.WRITE)}catch(_:FileAlreadyExistsException){
                    val pid=runCatching{Files.readAllLines(path).firstOrNull()?.toLongOrNull()}.getOrNull()
                    if(pid!=null&&ProcessHandle.of(pid).map{it.isAlive}.orElse(false)==false){runCatching{Files.deleteIfExists(path)};return@repeat}
                    return null
                }
                try {
                    val contents="${ProcessHandle.current().pid()}\nRiffuna\n${System.getenv("COMPUTERNAME")?:"localhost"}\n"
                    channel.write(ByteBuffer.wrap(contents.toByteArray(Charsets.UTF_8)));channel.force(true)
                    val lock=channel.tryLock()?:run{channel.close();return null}
                    return InstanceGuard(path,channel,lock)
                }catch(e:Exception){channel.close();runCatching{Files.deleteIfExists(path)};throw e}
            }
            return null
        }
    }
}
