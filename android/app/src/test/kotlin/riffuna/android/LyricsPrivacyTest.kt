package riffuna.android

import java.io.IOException
import kotlin.test.*
import kotlinx.coroutines.runBlocking
import okhttp3.HttpUrl
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import riffuna.core.LyricLine
import riffuna.core.LyricsPacket
import riffuna.core.Track

class LyricsPrivacyTest {
    @Test
    fun importedLyricsStayLocalAndSurviveAnInvalidReplacement() = runBlocking {
        val cache = mutableMapOf<String, String>()
        val http =
            OkHttpClient.Builder().addInterceptor { error("Unexpected network request") }.build()
        val track =
            Track(
                "local-0123456789abcdef0123456789abcdef",
                "Synthetic song",
                "Synthetic artist",
                12,
                "content://PRIVATE_PROFILE_FIXTURE/document/1",
            )
        val repository =
            AndroidLyrics(http, { cache[it].orEmpty() }, { key, value -> cache[key] = value })
        val imported = repository.importLocal(track, "[00:02.00]Synthetic line", "lrc")
        assertEquals("local_lrc", imported.timingSource)
        assertEquals(2_000L, imported.lines.single().startMs)
        assertTrue(imported.approximateWords)
        assertFailsWith<IllegalArgumentException> {
            repository.importLocal(track, "bad file", "lrc")
        }
        val reopened =
            AndroidLyrics(http, { cache[it].orEmpty() }, { key, value -> cache[key] = value })
        assertEquals(imported, reopened.load(track, force = true))
        assertTrue(cache.values.none { "PRIVATE_PROFILE_FIXTURE" in it })
    }

    @Test
    fun diagnosticLogBodiesDropOriginalExceptionDetails() {
        val failure =
            IOException(
                "content://PRIVATE_PROFILE_FIXTURE/document PRIVATE_HISTORY_FIXTURE " +
                    "https://r1---fixture.googlevideo.com/videoplayback?sig=FAKE_SIGNATURE_01234567"
            )
        assertEquals("HTTPS failure=IOException", sourceFailureLog(failure))
        assertEquals("code=2001 cause=IOException", audioFailureLog(2001, failure))
        assertEquals(
            "Preparing foreground unavailable: IllegalStateException",
            foregroundFailureLog(IllegalStateException(failure)),
        )
    }

    @Test
    fun lyricsRequestsNeverContainLocalUriOrListeningHistory() = runBlocking {
        val privateUri = "content://PRIVATE_PROFILE_FIXTURE/documents/recording"
        val history = "PRIVATE_HISTORY_FIXTURE"
        val requested = mutableListOf<HttpUrl>()
        val client =
            OkHttpClient.Builder()
                .addInterceptor { chain ->
                    requested += chain.request().url
                    if (chain.request().url.encodedPath == "/api/get") {
                        Response.Builder()
                            .request(chain.request())
                            .protocol(Protocol.HTTP_1_1)
                            .code(404)
                            .message("Not found")
                            .body("".toResponseBody())
                            .build()
                    } else {
                        throw IOException("$privateUri $history")
                    }
                }
                .build()
        val library = mutableMapOf("history" to history, "local-path" to privateUri)
        val repo =
            AndroidLyrics(client, { library[it].orEmpty() }, { key, value -> library[key] = value })
        val local = Track("local-37", privateUri, history, 12)
        val base = LyricsPacket(state = "synced", lines = listOf(LyricLine(1000, 8000, "one line")))
        repo.load(local, true)
        repo.enrich(local, base)
        val accidentalPath = local.copy(id = "ccccccccccc", title = "Mix(C:\\takes\\private.wav)")
        repo.load(accidentalPath, true)
        repo.enrich(accidentalPath, base)
        assertTrue(requested.isEmpty(), "Local tracks must not be sent to a lyrics provider")
        val remote = Track("bbbbbbbbbbb", "Synthetic song", "Synthetic artist", 12, privateUri)
        val failed = repo.load(remote, true)
        repo.enrich(remote, base)
        assertEquals(setOf("lrclib.net", "api.betterlyrics.org"), requested.map { it.host }.toSet())
        assertEquals(
            mapOf(
                "/api/get" to setOf("track_name", "artist_name", "duration"),
                "/api/search" to setOf("track_name", "artist_name"),
                "/getLyrics" to setOf("s", "a", "d"),
                "/qq/getLyrics" to setOf("s", "a", "d"),
            ),
            requested.associate { it.encodedPath to it.queryParameterNames },
        )
        assertTrue(
            requested.none { url ->
                url.query.orEmpty().let { history in it || privateUri in it || remote.id in it }
            }
        )
        assertTrue(history !in failed.message && privateUri !in failed.message)
    }
}
