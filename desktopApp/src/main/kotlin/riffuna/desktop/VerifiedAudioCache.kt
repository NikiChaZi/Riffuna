package riffuna.desktop

import java.nio.file.*
import java.nio.file.attribute.BasicFileAttributes
import java.nio.file.attribute.FileTime
import java.security.MessageDigest
import java.time.Instant

/** Verify once per unchanged file version; never trust a remembered path alone. */
internal class VerifiedAudioCache(private val hash: (Path) -> String = ::fileSha256) {
    private data class Stamp(
        val size: Long,
        val modified: FileTime,
        val created: FileTime,
        val fileKey: Any?,
        val digest: String,
    )

    private val verified =
        object : LinkedHashMap<Path, Stamp>(256, .75f, true) {
            override fun removeEldestEntry(eldest: MutableMap.MutableEntry<Path, Stamp>?): Boolean =
                size > 256
        }

    private fun stamp(path: Path, digest: String): Stamp {
        val attributes =
            Files.readAttributes(path, BasicFileAttributes::class.java, LinkOption.NOFOLLOW_LINKS)
        check(attributes.isRegularFile)
        return Stamp(
            attributes.size(),
            attributes.lastModifiedTime(),
            attributes.creationTime(),
            attributes.fileKey(),
            digest,
        )
    }

    @Synchronized
    fun verify(path: Path, size: Long, digest: String): Boolean {
        try {
            val before = stamp(path, digest)
            check(before.size == size)
            if (verified[path] != before) {
                check(hash(path) == digest)
                check(stamp(path, digest) == before) { "Cache changed while hashing" }
            }
            val touched = FileTime.from(Instant.now())
            Files.setLastModifiedTime(path, touched)
            verified[path] = stamp(path, digest)
            return true
        } catch (_: Exception) {
            verified.remove(path)
            return false
        }
    }
}

internal fun fileSha256(path: Path): String {
    val checksum = MessageDigest.getInstance("SHA-256")
    Files.newInputStream(path).use { input ->
        val chunk = ByteArray(256 * 1024)
        while (true) {
            val read = input.read(chunk)
            if (read < 0) break
            checksum.update(chunk, 0, read)
        }
    }
    return checksum.digest().joinToString("") { "%02x".format(it) }
}
