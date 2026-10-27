package riffuna.android

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.util.UUID
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.*
import okhttp3.OkHttpClient
import okhttp3.Request
import org.junit.*
import org.junit.Assert.*
import org.junit.runner.RunWith
import riffuna.core.*

@RunWith(AndroidJUnit4::class)
class AndroidSmokeTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context
        get() = instrumentation.targetContext

    @Test
    fun sqliteRoundTripPreservesQueueLikesAndPlaylist() {
        val name = "test-${UUID.randomUUID()}.sqlite3"
        val first = AndroidLibrary(context, name)
        val track = Track("aaaaaaaaaaa", "Song", "Artist", 180)
        first.like(track, true)
        first.saveQueue(listOf(track), 0, track)
        first.recordPlay(track)
        val playlist = first.createPlaylist("Road")
        first.addToPlaylist(playlist, listOf(track, track))
        first.close()
        val reopened = AndroidLibrary(context, name)
        try {
            assertEquals(listOf(track), reopened.likes())
            assertEquals(listOf(track), reopened.history())
            assertEquals(listOf(track) to 0, reopened.queue())
            assertEquals(track, reopened.current())
            assertEquals(listOf(track), reopened.playlistTracks(playlist))
            assertEquals(1, reopened.playlists().single().trackCount)
            reopened.like(track, false)
            assertTrue(reopened.likes().isEmpty())
            val copy = reopened.duplicatePlaylist(playlist)
            assertEquals(listOf(track), reopened.playlistTracks(copy))
        } finally {
            reopened.close()
            context.deleteDatabase(name)
        }
    }

    @Test
    fun boundedRangesReadAcrossChunksAndSeek() {
        val content =
            ByteArray((RangeAudioDataSource.CHUNK * 2 + 731).toInt()) { (it % 251).toByte() }
        val requested = mutableListOf<LongRange>()
        val http =
            OkHttpClient.Builder()
                .addInterceptor { chain ->
                    val request = chain.request()
                    val match =
                        Regex("bytes=(\\d+)-(\\d+)")
                            .matchEntire(request.header("Range").orEmpty())!!
                    val from = match.groupValues[1].toLong()
                    val end = minOf(match.groupValues[2].toLong(), content.lastIndex.toLong())
                    requested.add(from..end)
                    okhttp3.Response.Builder()
                        .request(request)
                        .protocol(okhttp3.Protocol.HTTP_1_1)
                        .code(206)
                        .message("Partial Content")
                        .header("Content-Range", "bytes $from-$end/${content.size}")
                        .body(
                            okhttp3.ResponseBody.create(
                                null,
                                content.copyOfRange(from.toInt(), end.toInt() + 1),
                            )
                        )
                        .build()
                }
                .build()
        val source = RangeAudioDataSource(http) { mapOf("User-Agent" to "RiffunaTest") }
        val uri = android.net.Uri.parse("https://audio.googlevideo.com/videoplayback")
        try {
            assertEquals(
                content.size.toLong(),
                source.open(androidx.media3.datasource.DataSpec(uri)),
            )
            val output = java.io.ByteArrayOutputStream()
            val buffer = ByteArray(8192)
            while (true) {
                val n = source.read(buffer, 0, buffer.size)
                if (n < 0) break
                output.write(buffer, 0, n)
            }
            assertArrayEquals(content, output.toByteArray())
            assertEquals(3, requested.size)
            assertTrue(requested.all { it.last - it.first + 1 <= RangeAudioDataSource.CHUNK })
            source.close()
            val position = RangeAudioDataSource.CHUNK + 17
            assertEquals(
                content.size - position,
                source.open(
                    androidx.media3.datasource.DataSpec.Builder()
                        .setUri(uri)
                        .setPosition(position)
                        .build()
                ),
            )
            val n = source.read(buffer, 0, buffer.size)
            assertArrayEquals(
                content.copyOfRange(position.toInt(), position.toInt() + n),
                buffer.copyOf(n),
            )
        } finally {
            source.close()
        }
    }

    @Test
    fun playbackContinuesInBackgroundAndMediaSessionPausesIt(): Unit = runBlocking {
        Assume.assumeTrue(InstrumentationRegistry.getArguments().getString("liveNetwork") == "true")
        val name = "background-${UUID.randomUUID()}.sqlite3"
        val app = instrumentation.targetContext.applicationContext as RiffunaApplication
        lateinit var graph: AppGraph
        instrumentation.runOnMainSync {
            graph = AppGraph(context, name, "test-background-${UUID.randomUUID()}")
            app.testGraph = graph
            graph.controller.setVolume(0f)
        }
        val activity =
            instrumentation.startActivitySync(
                android.content
                    .Intent(context, MainActivity::class.java)
                    .addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK)
            )
        var media: androidx.media3.session.MediaController? = null
        try {
            val track = graph.source.search("Дора Понарошку", 1).first()
            instrumentation.runOnMainSync { graph.controller.play(track) }
            withTimeout(120000) {
                while (!graph.controller.state.value.playing) {
                    graph.controller.state.value.playbackError?.let { error(it) }
                    delay(100)
                }
            }
            val before = graph.controller.state.value.positionMs
            instrumentation.runOnMainSync { activity.moveTaskToBack(true) }
            withTimeout(10000) {
                while (graph.controller.state.value.positionMs < before + 2500) delay(100)
            }
            assertTrue(graph.controller.state.value.playing)
            val token =
                androidx.media3.session.SessionToken(
                    context,
                    android.content.ComponentName(context, PlaybackService::class.java),
                )
            lateinit var future:
                com.google.common.util.concurrent.ListenableFuture<
                    androidx.media3.session.MediaController
                >
            instrumentation.runOnMainSync {
                future =
                    androidx.media3.session.MediaController.Builder(context, token).buildAsync()
            }
            media = future.get(15, TimeUnit.SECONDS)
            instrumentation.runOnMainSync { media!!.pause() }
            withTimeout(5000) { while (graph.controller.state.value.playing) delay(100) }
            android.util.Log.i("RiffunaTest", "BACKGROUND_AND_MEDIA_SESSION_OK")
        } finally {
            instrumentation.runOnMainSync {
                media?.release()
                activity.finish()
                context.stopService(android.content.Intent(context, PlaybackService::class.java))
            }
            instrumentation.waitForIdleSync()
            instrumentation.runOnMainSync {
                graph.controller.close()
                app.testGraph = null
            }
            context.deleteDatabase(name)
        }
    }

    @Test
    fun publicEndpointConnectivity() {
        Assume.assumeTrue(InstrumentationRegistry.getArguments().getString("liveNetwork") == "true")
        val client =
            OkHttpClient.Builder()
                .connectTimeout(10, TimeUnit.SECONDS)
                .readTimeout(15, TimeUnit.SECONDS)
                .callTimeout(20, TimeUnit.SECONDS)
                .build()
        for (host in listOf("music.youtube.com", "youtubei.googleapis.com", "lrclib.net")) {
            try {
                client
                    .newCall(Request.Builder().url("https://" + host + "/").build())
                    .execute()
                    .use {
                        android.util.Log.i("RiffunaTest", "probe=" + host + " status=" + it.code)
                    }
            } catch (error: Exception) {
                android.util.Log.w(
                    "RiffunaTest",
                    "probe=" + host + " failure=" + error.javaClass.simpleName,
                )
            }
        }
    }

    @Test
    fun browserSearchResolveAndSilentMedia3Playback() = runBlocking {
        Assume.assumeTrue(InstrumentationRegistry.getArguments().getString("liveNetwork") == "true")
        val name = "live-${UUID.randomUUID()}.sqlite3"
        val library = AndroidLibrary(context, name)
        val http =
            OkHttpClient.Builder().callTimeout(25, TimeUnit.SECONDS).followRedirects(false).build()
        lateinit var source: BrowserMusicSource
        instrumentation.runOnMainSync { source = BrowserMusicSource(context, http, library) }
        var audio: AndroidAudio? = null
        try {
            android.util.Log.i("RiffunaTest", "phase=search")
            val tracks = withTimeout(120000) { source.search("Дора Понарошку", 10) }
            assertTrue("No catalog songs", tracks.isNotEmpty())
            val track = tracks.first()
            android.util.Log.i("RiffunaTest", "phase=resolve results=" + tracks.size)
            val stream = withTimeout(120000) { source.resolve(track) }
            assertTrue(stream.uri.startsWith("https://"))
            http
                .newCall(
                    Request.Builder()
                        .url(stream.uri)
                        .headers(
                            okhttp3.Headers.Builder()
                                .apply {
                                    stream.headers.forEach { (k, v) -> add(k, v) }
                                    add("Range", "bytes=0-1023")
                                }
                                .build()
                        )
                        .build()
                )
                .execute()
                .use { assertEquals(206, it.code) }
            instrumentation.runOnMainSync {
                audio = AndroidAudio(context, http) { track }
                audio!!.setVolume(0f)
            }
            val total = android.net.Uri.parse(stream.uri).getQueryParameter("clen")!!.toLong()
            require(total in 1..24L * 1024 * 1024)
            http
                .newCall(
                    Request.Builder()
                        .url(stream.uri)
                        .headers(
                            okhttp3.Headers.Builder()
                                .apply {
                                    stream.headers.forEach { (k, v) -> add(k, v) }
                                    add("Range", "bytes=0-${total-1}")
                                }
                                .build()
                        )
                        .build()
                )
                .execute()
                .use { response ->
                    assertEquals(206, response.code)
                    var received = 0L
                    val buffer = ByteArray(16384)
                    response.body!!.byteStream().use { input ->
                        while (true) {
                            val size = input.read(buffer)
                            if (size < 0) break
                            received += size
                            require(received <= total)
                        }
                    }
                    assertEquals(total, received)
                    android.util.Log.i("RiffunaTest", "phase=complete-stream bytes=" + received)
                }
            android.util.Log.i("RiffunaTest", "phase=playback")
            audio!!.open(stream)
            withTimeout(45000) {
                while (!audio!!.state.value.playing) {
                    audio!!.state.value.error?.let { error(it) }
                    delay(100)
                }
            }
            instrumentation.runOnMainSync {
                audio!!.pause()
                audio!!.seek(5000)
            }
            withTimeout(15000) {
                while (kotlin.math.abs(audio!!.state.value.positionMs - 5000) > 1000) delay(100)
            }
            assertFalse(audio!!.state.value.playing)
        } finally {
            instrumentation.runOnMainSync {
                audio?.close()
                source.close()
            }
            library.close()
            context.deleteDatabase(name)
        }
    }
}
