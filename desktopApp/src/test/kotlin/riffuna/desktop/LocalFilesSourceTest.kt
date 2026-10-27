package riffuna.desktop

import java.nio.file.*
import kotlin.test.*
import kotlinx.coroutines.*
import riffuna.core.*

class LocalFilesSourceTest {
    private fun source(root: Path) =
        LocalFilesSource(root.resolve("index.sqlite3")) {
            LocalMetadata(it.fileName.toString().substringBeforeLast('.'), "Artist", 180)
        }

    @Test
    fun importDeduplicatesPersistsAndLeavesTheOriginalFileInPlace() =
        runBlocking<Unit> {
            val root = Files.createTempDirectory("riffuna-local")
            val folder = Files.createDirectory(root.resolve("music"))
            val audio = folder.resolve("Song.mp3")
            Files.write(audio, byteArrayOf(1, 2, 3))
            Files.writeString(folder.resolve("notes.txt"), "Not music")
            val first = source(root)
            assertEquals(
                LocalImportResult(1),
                first.importLocalFiles(listOf(folder.toString(), audio.toString())),
            )
            assertEquals(LocalImportResult(0, 1), first.importLocalFiles(listOf(audio.toString())))
            val reopened = source(root)
            val track = reopened.localTracks().single()
            assertTrue(track.isLocalFile)
            assertEquals(track, reopened.search("artist song", 40).single())
            assertEquals(audio.toRealPath().toUri().toString(), reopened.resolve(track).uri)
            assertContentEquals(byteArrayOf(1, 2, 3), Files.readAllBytes(audio))
            Files.delete(audio)
            assertFailsWith<IllegalStateException> { reopened.resolve(track) }
        }

    @Test
    fun localPlaybackAndPrefetchDoNotUseTheRemoteProvider() =
        runBlocking<Unit> {
            val root = Files.createTempDirectory("riffuna-local-route")
            val file = root.resolve("Offline.flac")
            Files.write(file, byteArrayOf(1))
            val local = source(root)
            local.importLocalFiles(listOf(file.toString()))
            var calls = 0
            val remote =
                object : MusicSource {
                    override suspend fun search(query: String, limit: Int): List<Track> {
                        calls++
                        error("Offline")
                    }

                    override suspend fun resolve(track: Track): AudioSource {
                        calls++
                        error("Offline")
                    }

                    override suspend fun prefetch(track: Track) {
                        calls++
                        error("Offline")
                    }
                }
            val combined = DeviceMusicSource(remote, local)
            val track = combined.localTracks().single()
            assertEquals(file.toRealPath().toUri().toString(), combined.resolve(track).uri)
            combined.prefetch(track)
            combined.invalidate(track)
            assertEquals(0, calls)
            assertEquals(listOf(track), combined.search("offline", 40))
            assertEquals(1, calls)
            assertFailsWith<IllegalStateException> {
                combined.resolve(Track("aaaaaaaaaaa", "Remote", "Artist"))
            }
            assertEquals(2, calls)
        }

    @Test
    fun unreadableMetadataIsReportedAndEmptyImportsAreSafe() =
        runBlocking<Unit> {
            val root = Files.createTempDirectory("riffuna-local-corrupt")
            val file = root.resolve("Bad.wav")
            Files.write(file, byteArrayOf(1))
            val local = LocalFilesSource(root.resolve("index.sqlite3")) { error("Invalid audio") }
            assertEquals(
                LocalImportResult(0, 0, 1),
                local.importLocalFiles(listOf(file.toString())),
            )
            assertEquals(LocalImportResult(0), local.importLocalFiles(emptyList()))
            assertTrue(local.localTracks().isEmpty())
            assertFailsWith<IllegalArgumentException> {
                local.resolve(Track("aaaaaaaaaaa", "Remote"))
            }
        }

    @Test
    fun cancellationIsNotTurnedIntoAnEmptyOnlineResult() =
        runBlocking<Unit> {
            val root = Files.createTempDirectory("riffuna-local-cancel")
            val remote =
                object : MusicSource {
                    override suspend fun search(query: String, limit: Int): List<Track> =
                        throw CancellationException("Cancelled")

                    override suspend fun resolve(track: Track): AudioSource = error("Unused")
                }
            val combined = DeviceMusicSource(remote, source(root))
            assertFailsWith<CancellationException> { combined.search("song", 40) }
        }
}
