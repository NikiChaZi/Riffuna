package riffuna.android

import kotlin.test.*
import kotlinx.serialization.json.*
import riffuna.catalog.*
import riffuna.core.*

class AndroidRecordingRulesTest {
    @Test
    fun uploaderNameDoesNotHideMatchingArtistInUploadTitle() {
        val reference = Track("reference", "Кайфоград", "Слава КПСС", 200)
        val upload = Track("upload", "Слава КПСС - Кайфоград (uncensored)", "Архив музыки", 201)
        assertTrue(AndroidRecordingRules.matches(reference, upload))
        assertFalse(
            AndroidRecordingRules.matches(
                reference,
                upload.copy(title = "Другой артист - Кайфоград"),
            )
        )
    }

    @Test
    fun artistQueryRanksOriginalAboveRelatedWordsAndRequestsUploadFallback() {
        val relevance = SearchRelevance("карта в блоке главный герой")
        val original = Track("original", "Карта в блоке", "Главный герой", 131)
        val unrelated = Track("other", "карта в блоке, герой", "главный по рэпу, whole flow", 131)
        assertTrue(relevance.score(original) > relevance.score(unrelated))
        assertTrue(relevance.needsUploadFallback(emptyList()))
    }

    @Test
    fun missingMusicClassificationAndStoryboardCannotConfirmAnUpload() {
        val unknown = buildJsonObject {
            put("id", "abcdefghijk")
            put("title", "Song")
            put("duration", 180)
        }
        assertNull(MusicRules.catalog(unknown, ""))
        assertNull(
            StoryboardInspection.inspect(
                unknown,
                { _, _ -> error("No network expected") },
                { _, _ -> error("No decode expected") },
            )
        )
    }

    @Test
    fun alternativesKeepArtistAndCompositionAndAllowSpeedVariants() {
        val original = Track("id", "Paparazzi", "Alximo", 172)
        assertTrue(
            AndroidRecordingRules.matches(
                original,
                original.copy(id = "other", title = "Paparazzi (Slowed)", duration = 184),
            )
        )
        assertFalse(
            AndroidRecordingRules.matches(original, original.copy(artist = "Another artist"))
        )
        assertFalse(
            AndroidRecordingRules.matches(original, original.copy(title = "Different song"))
        )
        assertFalse(
            AndroidRecordingRules.matches(original, original.copy(title = "Paparazzi (Live)"))
        )
        assertFalse(AndroidRecordingRules.matches(original, original.copy(duration = 900)))
        assertTrue(AndroidRecordingRules.acceptable(Track("id", "Live Forever", "Artist", 180)))
    }

    @Test
    fun realWordTimingMustAgreeWithRecordingAndExistingLines() {
        val track = Track("id", "Song", "Artist", 10)
        val base =
            LyricsPacket(
                state = "synced",
                lines = listOf(LyricLine(1000, null, "Hello"), LyricLine(4000, null, "World")),
                plainText = "Hello World",
            )
        val words =
            AndroidLyricWords.parseTtml(
                """<tt xmlns="http://www.w3.org/ns/ttml"><body><p begin="1s" end="3s"><span begin="1s" end="2s">Hello</span></p><p begin="4s" end="6s"><span begin="4s" end="5s">World</span></p></body></tt>"""
            )
        assertTrue(AndroidLyrics.compatible(track, base, words))
        assertFalse(
            AndroidLyrics.compatible(
                track,
                base,
                words.map { it.copy(startMs = it.startMs + 5000) },
            )
        )
        assertFalse(
            AndroidLyrics.compatible(track, base, words.map { it.copy(text = "Different lyrics") })
        )
        assertFailsWith<IllegalArgumentException> {
            AndroidLyricWords.parseTtml("<!DOCTYPE tt><tt/>")
        }
    }
}
