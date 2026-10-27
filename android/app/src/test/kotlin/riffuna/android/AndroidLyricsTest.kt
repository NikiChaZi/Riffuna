package riffuna.android

import kotlin.test.*
import kotlinx.serialization.json.*
import riffuna.core.*

class AndroidLyricsTest {
    @Test
    fun matchesRecordingAndRejectsDifferentDurationOrArtist() {
        val row =
            Json.parseToJsonElement(
                    """{"trackName":"Понарошку","artistName":"Дора","duration":147}"""
                )
                .jsonObject
        assertTrue(AndroidLyrics.matches(row, Track("id", "Понарошку", "Дора", 147)))
        assertFalse(AndroidLyrics.matches(row, Track("id", "Понарошку", "Дора", 160)))
        assertFalse(AndroidLyrics.matches(row, Track("id", "Понарошку", "Другой", 147)))
    }

    @Test
    fun doesNotFabricateWordTimings() {
        val row =
            Json.parseToJsonElement(
                    """{"syncedLyrics":"[00:01.00]Hello\n[00:03.50]World","plainLyrics":"Hello World"}"""
                )
                .jsonObject
        val packet = AndroidLyrics.packet(row)
        assertEquals("synced", packet.state)
        assertTrue(packet.approximateWords)
        assertEquals(1000L, packet.lines.first().startMs)
        assertEquals(listOf("Hello", "World"), packet.lines.map { it.text })
        assertTrue(packet.lines.all { it.words.isEmpty() })
    }

    @Test
    fun instrumentalIsExplicit() {
        assertEquals(
            "instrumental",
            AndroidLyrics.packet(buildJsonObject { put("instrumental", true) }).state,
        )
    }
}
