package riffuna.desktop

import java.net.URI
import java.nio.file.*
import java.nio.file.attribute.FileTime
import java.security.MessageDigest
import javax.imageio.ImageIO

/** Validates before persistence; a damaged cached cover is downloaded again. */
internal class ArtworkStore(
    private val directory: Path,
    private val budget: Long = 128L * 1024 * 1024,
    private val fetch: (String) -> ByteArray = { DesktopNetwork.bytes(it, 4 * 1024 * 1024) },
) {
    private val locks = Array(32) { Any() }

    fun load(url: String): ByteArray =
        synchronized(locks[(url.hashCode() and Int.MAX_VALUE) % locks.size]) {
            val uri = URI(url)
            require(uri.scheme == "https" && uri.host != null)
            val name =
                MessageDigest.getInstance("SHA-256").digest(url.toByteArray()).joinToString("") {
                    "%02x".format(it)
                }
            val file = directory.resolve("$name.img")
            if (Files.isRegularFile(file)) {
                val cached =
                    runCatching {
                            require(Files.size(file) <= 4 * 1024 * 1024)
                            Files.readAllBytes(file).also(::validate)
                        }
                        .getOrNull()
                if (cached != null) {
                    runCatching {
                        Files.setLastModifiedTime(
                            file,
                            FileTime.fromMillis(System.currentTimeMillis()),
                        )
                    }
                    return@synchronized cached
                }
                Files.deleteIfExists(file)
            }
            val bytes = fetch(url).also(::validate)
            Files.createDirectories(directory)
            val temporary = Files.createTempFile(directory, "cover-", ".tmp")
            try {
                Files.write(temporary, bytes)
                try {
                    Files.move(
                        temporary,
                        file,
                        StandardCopyOption.ATOMIC_MOVE,
                        StandardCopyOption.REPLACE_EXISTING,
                    )
                } catch (_: AtomicMoveNotSupportedException) {
                    Files.move(temporary, file, StandardCopyOption.REPLACE_EXISTING)
                }
            } finally {
                Files.deleteIfExists(temporary)
            }
            runCatching { prune(file) }
            bytes
        }

    private fun validate(bytes: ByteArray) {
        require(bytes.isNotEmpty() && bytes.size <= 4 * 1024 * 1024)
        ImageIO.createImageInputStream(bytes.inputStream()).use { input ->
            require(input != null)
            val readers = ImageIO.getImageReaders(input)
            require(readers.hasNext())
            val reader = readers.next()
            try {
                reader.input = input
                val width = reader.getWidth(0)
                val height = reader.getHeight(0)
                require(width > 0 && height > 0 && width.toLong() * height <= 4_000_000)
                require(reader.read(0) != null)
            } finally {
                reader.dispose()
            }
        }
    }

    @Synchronized
    private fun prune(keep: Path) {
        val entries =
            Files.list(directory)
                .use { stream ->
                    stream.filter { it.fileName.toString().endsWith(".img") }.toList()
                }
                .sortedBy { Files.getLastModifiedTime(it).toMillis() }
        var size = entries.sumOf { Files.size(it) }
        for (entry in entries) {
            if (size <= budget) break
            if (entry != keep) {
                val length = Files.size(entry)
                if (Files.deleteIfExists(entry)) size -= length
            }
        }
    }
}
