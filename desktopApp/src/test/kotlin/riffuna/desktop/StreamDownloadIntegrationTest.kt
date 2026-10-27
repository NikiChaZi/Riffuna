package riffuna.desktop

import java.net.URI
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.nio.file.Files
import java.nio.file.Path
import java.util.concurrent.TimeUnit
import kotlin.test.*
import kotlinx.coroutines.*
import kotlinx.serialization.json.Json
import riffuna.core.Track

/** Opt-in whole-stream regression check; private fixtures and audio stay outside the repository. */
class StreamDownloadIntegrationTest {
    @Test
    fun freshStreamsDownloadCompletelyAndReplayFromDisk() = runBlocking {
        org.junit.Assume.assumeTrue(System.getenv("RIFFUNA_LIVE_TEST") == "1")
        val root = Path.of(System.getProperty("user.dir")).parent
        val home =
            System.getenv("RIFFUNA_STREAM_HOME")?.let(Path::of)
                ?: root.resolve("Riffuna.runtime/app/resources")
        val data = Files.createTempDirectory("riffuna-whole-stream")
        val source = DesktopSource(home, data)
        val http = HttpClient.newBuilder().proxy(HttpClient.Builder.NO_PROXY).build()
        try {
            val fixture = System.getenv("RIFFUNA_STREAM_FIXTURE")
            val tracks =
                if (fixture.isNullOrBlank()) source.search("Дора Понарошку", 1)
                else Json.decodeFromString<List<Track>>(Files.readString(Path.of(fixture)))
            assertTrue(tracks.isNotEmpty())
            for ((index, track) in tracks.withIndex()) {
                val started = System.nanoTime()
                val stream = source.resolve(track)
                assertTrue(stream.uri.startsWith("http://127.0.0.1:"))
                val response =
                    http
                        .sendAsync(
                            HttpRequest.newBuilder(URI(stream.uri)).GET().build(),
                            HttpResponse.BodyHandlers.ofByteArray(),
                        )
                        .get(180, TimeUnit.SECONDS)
                assertEquals(200, response.statusCode())
                val length = response.headers().firstValueAsLong("Content-Length").orElseThrow()
                assertTrue(length > 0)
                assertEquals(length, response.body().size.toLong(), "Incomplete stream $index")
                var disk = source.resolve(track)
                withTimeout(20000) {
                    while (!disk.uri.startsWith("file:")) {
                        delay(250)
                        disk = source.resolve(track)
                    }
                }
                assertContentEquals(response.body(), Files.readAllBytes(Path.of(URI(disk.uri))))
                println(
                    "WHOLE_STREAM_OK index=$index bytes=$length elapsed_ms=${(System.nanoTime()-started)/1000000}"
                )
            }
        } finally {
            http.shutdownNow()
            source.close()
        }
    }
}
