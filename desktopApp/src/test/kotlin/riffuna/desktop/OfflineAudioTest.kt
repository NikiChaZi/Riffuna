package riffuna.desktop

import com.sun.net.httpserver.HttpServer
import java.net.InetSocketAddress
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.file.Files
import java.nio.file.Path
import kotlin.test.*
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import riffuna.core.AudioSource
import riffuna.core.Track

class OfflineAudioTest {
    private val track = Track("abcdefghijk", "Offline fixture", "Riffuna")
    private val payload =
        ByteBuffer.allocate(44 + 300_000)
            .order(ByteOrder.LITTLE_ENDIAN)
            .put("RIFF".toByteArray())
            .putInt(36 + 300_000)
            .put("WAVEfmt ".toByteArray())
            .putInt(16)
            .putShort(1)
            .putShort(1)
            .putInt(48_000)
            .putInt(96_000)
            .putShort(2)
            .putShort(16)
            .put("data".toByteArray())
            .putInt(300_000)
            .array()

    @Test
    fun savedRecordingResolvesAfterRestartWithoutAWorkerOrAutomaticCache() {
        val root = Files.createTempDirectory("riffuna-offline-test")
        try {
            val store = OfflineStore(root.resolve("offline-audio"))
            var progress = 0L
            withSource { source ->
                AudioTransport(root.resolve("discardable-cache")).use { transport ->
                    val audio =
                        transport.downloadOffline(
                            track.id,
                            source,
                            store.destination(track.id),
                            offlineGib,
                        ) { bytes, total ->
                            assertEquals(payload.size.toLong(), total)
                            assertTrue(bytes >= progress)
                            progress = bytes
                        }
                    store.add(track, audio)
                }
            }
            assertEquals(payload.size.toLong(), progress)
            val reloaded = OfflineStore(root.resolve("offline-audio"))
            assertEquals(track, reloaded.entries[track.id]?.track)
            assertEquals(
                fileSha256(reloaded.destination(track.id)),
                reloaded.entries[track.id]?.audio?.sha256,
            )
            val source = DesktopSource(root.resolve("no-worker-installed"), root)
            try {
                val audio = runBlocking { source.resolve(track) }
                assertEquals(reloaded.destination(track.id).toUri().toString(), audio.uri)
                assertContentEquals(payload, Files.readAllBytes(reloaded.destination(track.id)))
                val dll =
                    Path.of(System.getProperty("user.dir"))
                        .parent
                        .resolve("vendor/libmpv/libmpv-2.dll")
                if (Files.isRegularFile(dll)) {
                    val player = MpvAudio(dll, audioDriver = "null")
                    try {
                        runBlocking {
                            player.open(audio)
                            withTimeout(6_000) {
                                while (player.state.value.positionMs < 150) delay(40)
                            }
                        }
                    } finally {
                        player.close()
                    }
                }
            } finally {
                source.close()
            }
            reloaded.remove(track.id)
            assertNull(OfflineStore(root.resolve("offline-audio")).find(track.id))
        } finally {
            root.toFile().deleteRecursively()
        }
    }

    @Test
    fun quotaAndIncompleteRangesDoNotPublishAPartialRecording() {
        val root = Files.createTempDirectory("riffuna-offline-test")
        try {
            val destination = root.resolve("offline-audio").resolve("fixture.audio")
            AudioTransport(root.resolve("discardable-cache")).use { transport ->
                withSource { source ->
                    assertFailsWith<OfflineStorageFull> {
                        transport.downloadOffline(track.id, source, destination, 1) { _, _ -> }
                    }
                    assertFalse(Files.exists(destination))
                }
                withSource(truncateSecondRange = true) { source ->
                    assertFails {
                        transport.downloadOffline(track.id, source, destination, offlineGib) { _, _
                            ->
                        }
                    }
                    assertFalse(Files.exists(destination))
                    assertEquals(0L, Files.list(destination.parent).use { it.count() })
                }
            }
        } finally {
            root.toFile().deleteRecursively()
        }
    }

    private fun withSource(truncateSecondRange: Boolean = false, block: (AudioSource) -> Unit) {
        val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        server.createContext("/") { exchange ->
            try {
                val range = exchange.requestHeaders.getFirst("Range").removePrefix("bytes=")
                val start = range.substringBefore('-').toInt()
                val end = minOf(range.substringAfter('-').toInt(), payload.lastIndex)
                val size = end - start + 1
                val responseSize = if (truncateSecondRange && start > 0) size - 1 else size
                exchange.responseHeaders.set("Content-Type", "audio/wav")
                exchange.responseHeaders.set("Content-Range", "bytes $start-$end/${payload.size}")
                exchange.sendResponseHeaders(206, responseSize.toLong())
                exchange.responseBody.use { it.write(payload, start, responseSize) }
            } finally {
                exchange.close()
            }
        }
        server.start()
        try {
            block(AudioSource("http://127.0.0.1:${server.address.port}/"))
        } finally {
            server.stop(0)
        }
    }
}
