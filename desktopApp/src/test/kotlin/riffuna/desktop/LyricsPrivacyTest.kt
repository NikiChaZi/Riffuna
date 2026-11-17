package riffuna.desktop

import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLDecoder
import java.nio.file.Files
import kotlin.test.*
import riffuna.core.LyricLine
import riffuna.core.LyricsPacket
import riffuna.core.Track

class LyricsPrivacyTest {
    @Test
    fun localTracksStayOfflineAndRemoteErrorsExposeOnlyLookupFields() {
        val privatePath = "C:\\private\\PRIVATE_PROFILE_FIXTURE\\local.wav"
        val history = "PRIVATE_HISTORY_FIXTURE"
        val requested = mutableListOf<URL>()
        val followedRedirects = mutableListOf<Boolean>()
        val directory = Files.createTempDirectory("lyrics-privacy")
        val repo =
            LyricsRepository(directory) { address ->
                val url = requireNotNull(java.net.URI(address).toURL())
                requested += url
                object : HttpURLConnection(url) {
                    override fun connect() = Unit

                    override fun disconnect() = Unit

                    override fun usingProxy() = false

                    override fun getResponseCode(): Int {
                        followedRedirects += instanceFollowRedirects
                        if (url.path == "/api/get") return 302
                        throw IOException("$privatePath $history")
                    }
                }
            }
        val library = SqliteLibrary(directory.resolve("library.sqlite3"))
        try {
            library.recordPlay(Track("aaaaaaaaaaa", history))
            val local = Track("local-123", privatePath, history, 12)
            repo.load(local, true)
            repo.enrich(local, synced)
            val accidentalPath = local.copy(id = "ccccccccccc", title = "Mix($privatePath)")
            repo.load(accidentalPath, true)
            repo.enrich(accidentalPath, synced)
            assertTrue(requested.isEmpty(), "Local tracks must not contact a lyrics provider")

            val track = Track("bbbbbbbbbbb", "Synthetic song", "Synthetic artist", 12, privatePath)
            val failed = repo.load(track, true)
            repo.enrich(track, synced)
            assertEquals(
                setOf("lrclib.net", "api.betterlyrics.org"),
                requested.map { it.host }.toSet(),
            )
            assertEquals(
                mapOf(
                    "/api/get" to setOf("track_name", "artist_name", "duration"),
                    "/api/search" to setOf("track_name", "artist_name"),
                    "/getLyrics" to setOf("s", "a", "al", "d"),
                    "/qq/getLyrics" to setOf("s", "a", "al", "d"),
                ),
                requested
                    .groupBy { it.path }
                    .mapValues { (_, urls) ->
                        urls
                            .flatMap { url -> url.query.split('&').map { it.substringBefore('=') } }
                            .toSet()
                    },
            )
            assertTrue(
                requested.none { url ->
                    val decoded = URLDecoder.decode(url.toString(), Charsets.UTF_8)
                    history in decoded || privatePath in decoded || track.id in decoded
                }
            )
            assertTrue(history !in failed.message && privatePath !in failed.message)
            assertTrue(followedRedirects.isNotEmpty() && followedRedirects.none { it })
        } finally {
            library.close()
        }
    }

    @Test
    fun diagnosticFailuresDropRawMessagesUrlsAndPaths() {
        val private = "C:\\private\\PRIVATE_PROFILE_FIXTURE\\library.sqlite3"
        val signed =
            "https://r1---fixture.googlevideo.com/videoplayback?sig=FAKE_SIGNATURE_01234567"
        assertNull(safeSourceTrace("IOException: $private $signed PRIVATE_HISTORY_FIXTURE"))
        val safe =
            assertNotNull(
                safeSourceTrace(
                    """{"phase":"range-bridge-error","type":"TypeError","cause":"UND_ERR_CONNECT_TIMEOUT","url":"$signed","message":"PRIVATE_HISTORY_FIXTURE"}"""
                )
            )
        assertContains(safe, "UND_ERR_CONNECT_TIMEOUT")
        assertTrue("PRIVATE_" !in safe && "googlevideo" !in safe)
        assertTrue("path" !in startupReport("0.4.0", true).toString())
    }

    private val synced =
        LyricsPacket(
            state = "synced",
            plainText = "line one",
            lines = listOf(LyricLine(1000, 6000, "line one")),
        )
}
