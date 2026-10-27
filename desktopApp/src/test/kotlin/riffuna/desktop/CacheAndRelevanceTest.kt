package riffuna.desktop

import java.nio.file.*
import java.nio.file.attribute.FileTime
import kotlin.test.*
import riffuna.core.Track

class CacheAndRelevanceTest {
    @Test
    fun unchangedCacheHitsDoNotRehashButChangedFilesAreRevalidated() {
        val file = Files.createTempFile("riffuna-verified", ".m4a")
        Files.writeString(file, "valid-audio")
        val digest = fileSha256(file)
        var checks = 0
        val verified = VerifiedAudioCache {
            checks++
            fileSha256(it)
        }
        repeat(5) { assertTrue(verified.verify(file, Files.size(file), digest)) }
        assertEquals(1, checks)
        val previous = Files.getLastModifiedTime(file).toMillis()
        Files.writeString(file, "bad---audio")
        Files.setLastModifiedTime(file, FileTime.fromMillis(previous + 2000))
        assertFalse(verified.verify(file, Files.size(file), digest))
        assertEquals(2, checks)
        Files.delete(file)
        assertFalse(verified.verify(file, 11, digest))
    }

    @Test
    fun expectedChecksumChangesInvalidateTheRememberedVerification() {
        val file = Files.createTempFile("riffuna-digest", ".m4a")
        Files.writeString(file, "audio")
        val verified = VerifiedAudioCache()
        assertTrue(verified.verify(file, Files.size(file), fileSha256(file)))
        assertFalse(verified.verify(file, Files.size(file), "0".repeat(64)))
    }

    @Test
    fun metadataCopiesShareOneScoreAndDifferentQueriesHaveSeparateCaches() {
        var calls = 0
        val relevance =
            SearchRelevance("alpha beta") { _, _, _ ->
                calls++
                200.0
            }
        val track = Track("a", "Alpha Beta", "Artist")
        repeat(5) { assertEquals(200.0, relevance.score(track.copy(viewCount = it.toLong()))) }
        assertFalse(relevance.needsUploadFallback(listOf(track)))
        assertEquals(1, calls)
        relevance.score(track.copy(title = "Different"))
        assertEquals(2, calls)
    }

    @Test
    fun fallbackKeepsOriginalSparseCatalogAndVersionPolicy() {
        val weak = Track("a", "Some Song", "Artist")
        assertTrue(
            SearchRelevance("alpha beta") { _, _, _ -> 100.0 }.needsUploadFallback(listOf(weak))
        )
        assertFalse(SearchRelevance("дора") { _, _, _ -> 100.0 }.needsUploadFallback(emptyList()))
        assertTrue(
            SearchRelevance("alpha slowed") { _, _, _ -> 200.0 }
                .needsUploadFallback(List(6) { weak })
        )
    }
}
