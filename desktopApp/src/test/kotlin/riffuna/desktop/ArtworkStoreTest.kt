package riffuna.desktop

import java.awt.image.BufferedImage
import java.io.ByteArrayOutputStream
import java.nio.file.*
import javax.imageio.ImageIO
import kotlin.test.*

class ArtworkStoreTest {
    private fun image(): ByteArray =
        ByteArrayOutputStream().use { out ->
            ImageIO.write(BufferedImage(32, 32, BufferedImage.TYPE_INT_RGB), "png", out)
            out.toByteArray()
        }

    @Test
    fun damagedCoverIsRecoveredAndInvalidResponsesAreNotPersisted() {
        val directory = Files.createTempDirectory("riffuna-covers")
        var requests = 0
        val bytes = image()
        val store =
            ArtworkStore(
                directory,
                fetch = {
                    requests++
                    bytes
                },
            )
        val url = "https://i.ytimg.com/vi/aaaaaaaaaaa/hqdefault.jpg"
        assertContentEquals(bytes, store.load(url))
        assertContentEquals(bytes, store.load(url))
        assertEquals(1, requests)
        val cached = Files.list(directory).use { it.findFirst().orElseThrow() }
        Files.writeString(cached, "broken")
        assertContentEquals(bytes, store.load(url))
        assertEquals(2, requests)
        val invalid =
            ArtworkStore(directory.resolve("bad"), fetch = { "not an image".toByteArray() })
        assertFailsWith<IllegalArgumentException> { invalid.load(url) }
        assertFalse(Files.exists(directory.resolve("bad")))
        assertFailsWith<IllegalArgumentException> { store.load("file:///private.png") }
    }

    @Test
    fun oldArtworkIsEvictedWithinBudget() {
        val directory = Files.createTempDirectory("riffuna-covers-budget")
        val bytes = image()
        val store = ArtworkStore(directory, bytes.size.toLong(), fetch = { bytes })
        repeat(17) {
            store.load("https://i.ytimg.com/vi/${it.toString().padStart(11,'0')}/hqdefault.jpg")
        }
        assertTrue(
            Files.list(directory).use { stream -> stream.mapToLong { Files.size(it) }.sum() } <=
                bytes.size
        )
    }
}
