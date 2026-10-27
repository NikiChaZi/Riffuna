package riffuna.desktop

import kotlin.test.*
import kotlinx.serialization.json.*

class CatalogPresentationTest {
    private fun row(
        title: String,
        album: String = "",
        type: String = "MUSIC_VIDEO_TYPE_ATV",
        live: Boolean = false,
        available: Boolean = true,
    ) = buildJsonObject {
        put("id", "aaaaaaaaaaa")
        put("title", title)
        put("artist", "Artist")
        put("duration", 180)
        put("album", album)
        put("musicType", type)
        put("live", live)
        put("available", available)
    }

    @Test
    fun studioTitlesContainingAmbiguousWordsAreKept() {
        listOf(
                "Live Forever",
                "Repeat After Me (Interlude)",
                "The Loop",
                "Live in the Moment",
                "Live and Let Die",
                "Video Games",
                "Clip",
                "Review",
            )
            .forEach { assertNotNull(MusicRules.catalog(row(it), ""), it) }
        assertNotNull(MusicRules.catalog(row("Violet", "Live Through This"), ""))
        assertNotNull(MusicRules.catalog(row("Song", "Repeat After Me"), ""))
    }

    @Test
    fun declaredEditionsAndNonMusicRemainExcluded() {
        listOf(
                "Song (Live)",
                "Song Live",
                "Song - Live at Wembley",
                "Song [Loop]",
                "Song (Review)",
                "Song 1 час",
                "Song (Премьера клипа)",
                "Song Разбор трека",
                "Song Мультфильм",
            )
            .forEach { assertNull(MusicRules.catalog(row(it), ""), it) }
        assertNull(MusicRules.catalog(row("Song", "Live at Wembley"), ""))
        assertNull(MusicRules.catalog(row("Song", type = "MUSIC_VIDEO_TYPE_OMV"), ""))
        assertNull(MusicRules.catalog(row("Song", type = "MUSIC_VIDEO_TYPE_UGC"), ""))
        assertNull(MusicRules.catalog(row("Song", live = true), ""))
        assertNull(MusicRules.catalog(row("Song", available = false), ""))
        assertNull(MusicRules.catalog(row("Song"), "different title"))
    }

    @Test
    fun musicalProcessingRemainsAvailable() {
        listOf(
                "Song (Slowed)",
                "Song (Sped Up)",
                "Song (Mashup)",
                "Song (Remix)",
                "Rules of Nature Extended",
            )
            .forEach { assertNotNull(MusicRules.catalog(row(it), ""), it) }
    }
}
