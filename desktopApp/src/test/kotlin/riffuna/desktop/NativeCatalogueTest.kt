package riffuna.desktop

import java.nio.file.*
import kotlin.test.*
import kotlinx.coroutines.*

class NativeCatalogueTest {
    @Test
    fun realCatalogueDirectLinksOstLyricsAndAlternatives() = runBlocking {
        org.junit.Assume.assumeTrue(System.getenv("RIFFUNA_CATALOGUE_TEST") == "1")
        val root = Path.of(System.getProperty("user.dir")).parent
        val source =
            DesktopSource(
                root.resolve("build/desktop-resources/common"),
                Files.createTempDirectory("riffuna-catalogue-test"),
            )
        try {
            val direct =
                withTimeout(60000) {
                    source.search("https://www.youtube.com/watch?v=zyr7b4yYfl4", 1)
                }
            assertEquals("zyr7b4yYfl4", direct.single().id)
            val artist = withTimeout(120000) { source.search("Дора", 40) }
            assertTrue(artist.size >= 10)
            assertTrue(artist.none { MusicRules.excluded.containsMatchIn(it.title) })
            println("CATALOGUE_ARTIST results=${artist.size}")
            val ost = withTimeout(120000) { source.search("rule of nature", 40) }
            assertTrue(
                ost.any { it.title.contains("Rules", true) && it.title.contains("Nature", true) },
                "Requested OST absent",
            )
            println("CATALOGUE_OST results=${ost.size}")
            val dora =
                withTimeout(60000) {
                    source.lyricsPacket(direct.single().copy(duration = 147), true)
                }
            assertTrue(dora.state in setOf("synced", "plain"), "Native lyrics unavailable")
            println(
                "CATALOGUE_LYRICS state=${dora.state} lines=${dora.lines.size} last_ms=${dora.lines.lastOrNull()?.startMs}"
            )
            val target =
                withTimeout(120000) { source.search("Слава КПСС Кайфоград", 8) }
                    .firstOrNull { it.title.contains("Кайфоград", true) }
            assertNotNull(target, "Reference recording absent")
            val alternatives = withTimeout(240000) { source.alternatives(target) }
            assertTrue(
                alternatives.all {
                    it.track.id != target.id && MusicRules.versionMatches(target, it.track)
                }
            )
            println("CATALOGUE_ALTERNATIVES results=${alternatives.size}")
        } finally {
            source.close()
        }
    }
}
