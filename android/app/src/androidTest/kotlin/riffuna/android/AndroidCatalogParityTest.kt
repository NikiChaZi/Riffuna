package riffuna.android

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.util.UUID
import kotlinx.coroutines.*
import org.junit.*
import org.junit.Assert.*
import org.junit.runner.RunWith
import riffuna.catalog.*
import riffuna.core.*

@RunWith(AndroidJUnit4::class)
class AndroidCatalogParityTest {
    @Test
    fun sharedMatchingRecognizesUploaderAndRejectsClips() {
        val reference = Track("aaaaaaaaaaa", "Кайфоград", "Слава КПСС", 200)
        assertTrue(
            MusicRules.versionMatches(
                reference,
                Track("bbbbbbbbbbb", "Слава КПСС - Кайфоград (uncensored)", "Архив музыки", 201),
            )
        )
        assertFalse(
            MusicRules.versionMatches(
                reference,
                Track("bbbbbbbbbbb", "Слава КПСС - Кайфоград Live", "Архив музыки", 201),
            )
        )
        assertTrue(SearchRelevance("карта в блоке").needsUploadFallback(emptyList()))
    }

    @Test
    fun missingTracksAndAlternativeUploadsAreDiscoverable(): Unit = runBlocking {
        Assume.assumeTrue(InstrumentationRegistry.getArguments().getString("liveNetwork") == "true")
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val name = "catalog-parity-${UUID.randomUUID()}.sqlite3"
        val library = AndroidLibrary(context, name)
        lateinit var source: BrowserMusicSource
        instrumentation.runOnMainSync {
            source = BrowserMusicSource(context, SourceHttp.client(), library)
        }
        try {
            val tracks = withTimeout(180000) { source.search("карта в блоке", 40) }
            assertTrue(
                "Original artist absent from card search",
                tracks.any {
                    MusicRules.artist(it.artist).contains("главный герой") &&
                        MusicRules.composition(it.title).contains("карта в блоке")
                },
            )
            android.util.Log.i("RiffunaTest", "CATALOG_CARD_OK results=${tracks.size}")
            val references =
                listOf(
                    Track("I7nnx5-tZUI", "Фенибут", "нексюша", 164),
                    Track("Pd38CuY4yWU", "Кайфоград", "Слава КПСС", 154),
                )
            for (original in references) {
                val title = original.title
                val results = withTimeout(180000) { source.search("${original.artist} $title", 12) }
                assertTrue(
                    "Original recording absent: $title",
                    results.any { MusicRules.composition(it.title) == MusicRules.normal(title) },
                )
                val alternatives = withTimeout(240000) { source.alternatives(original) }
                assertTrue("Alternative recordings absent: $title", alternatives.isNotEmpty())
                assertTrue(alternatives.all { MusicRules.versionMatches(original, it.track) })
                android.util.Log.i(
                    "RiffunaTest",
                    "CATALOG_ALTERNATIVES_OK song=$title count=${alternatives.size}",
                )
            }
        } finally {
            instrumentation.runOnMainSync { source.close() }
            library.close()
            context.deleteDatabase(name)
        }
    }
}
