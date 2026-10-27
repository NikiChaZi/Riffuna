package riffuna.desktop

import java.nio.file.Files
import kotlin.test.*
import riffuna.core.Track

class RecordingIdentityTest {
    @Test
    fun normalizationIsSharedBySearchModelAndIdentity() {
        val value = "  ЁЖ Straße ς _ Ａ  "
        assertEquals("еж strasse σ a", MusicText.normalized(value))
        assertEquals(MusicText.normalized(value), MusicRules.normal(value))
        assertEquals(MusicText.normalized(value), MusicModel.normal(value))
        assertEquals("еж strasse ς _ a", MusicText.legacyNormalized(value))
    }

    @Test
    fun canonicalRecordingDeclarationsAndArtistPlacementRemainEquivalent() {
        val key = "recording:artist::song"
        listOf(
                "Artist — Song (Official Audio 2025)",
                "Song — Artist",
                "Song (Uncensored)",
                "Song - Original Version",
            )
            .forEach { assertEquals(key, MusicRules.workKey(Track("a", it, "Artist - Topic")), it) }
        assertNotEquals(key, MusicRules.workKey(Track("a", "Song (Slowed)", "Artist")))
    }

    @Test
    fun previouslyPersistedKeysAreReadAndResetWithoutRewritingOtherCollections() {
        val path = Files.createTempDirectory("riffuna-identity").resolve("library.sqlite3")
        val original =
            Track(
                "aaaaaaaaaaa",
                "The_Artist — Song_Title (Official Audio)",
                "The_Artist - Topic",
                180,
            )
        val alternate = Track("bbbbbbbbbbb", "Song_Title (Uncensored)", "The_Artist", 180)
        assertEquals("recording:the_artist::song_title", RecordingIdentity.legacyKey(original))
        val library = SqliteLibrary(path)
        try {
            library.saveQueue(listOf(original, alternate), 0, original)
            library.like(original, true)
            library.setSetting("recording:the_artist::song_title", alternate.id)
            assertEquals(alternate, library.preferred(original))
            assertEquals(listOf(original), library.likes())
            library.setPreferred(original, null)
            assertEquals(original, library.preferred(original))
            assertEquals(listOf(original, alternate), library.queue().first)
        } finally { library.close() }
    }
}
