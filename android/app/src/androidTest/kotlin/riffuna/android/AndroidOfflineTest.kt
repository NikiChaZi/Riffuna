package riffuna.android

import android.content.Context
import android.content.ContextWrapper
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.security.MessageDigest
import java.util.UUID
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.awaitCancellation
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import riffuna.core.Track

@RunWith(AndroidJUnit4::class)
class AndroidOfflineTest {
    @Test
    fun cancellingResolutionRemovesQueuedEntryAndAllowsRetry() = runBlocking {
        val app = ApplicationProvider.getApplicationContext<Context>()
        val profile = File(app.filesDir, "offline-test-${UUID.randomUUID()}").apply { mkdirs() }
        try {
            val context =
                object : ContextWrapper(app) {
                    override fun getFilesDir(): File = profile
                }
            val firstStarted = CompletableDeferred<Unit>()
            val firstCancelled = CompletableDeferred<Unit>()
            val retryStarted = CompletableDeferred<Unit>()
            val offline =
                AndroidOffline(context, this) {
                    val first = firstStarted.complete(Unit)
                    if (!first) retryStarted.complete(Unit)
                    try {
                        awaitCancellation()
                    } finally {
                        if (first) firstCancelled.complete(Unit)
                    }
                }
            val track = Track("waiting", "Waiting")
            offline.enqueue(listOf(track, track))
            withTimeout(5_000) { firstStarted.await() }
            assertEquals(AndroidOfflineStatus.Queued, offline.entries.value.single().status)

            offline.cancel(track.id)
            withTimeout(5_000) { firstCancelled.await() }
            assertTrue(offline.entries.value.isEmpty())
            assertNull(offline.find(track.id))

            offline.enqueue(track)
            withTimeout(5_000) { retryStarted.await() }
            offline.deleteAll()
            assertTrue(offline.entries.value.isEmpty())
        } finally {
            profile.deleteRecursively()
        }
    }

    @Test
    fun restoresOnlyCompleteAndVerifiedAudioWithoutResolvingSource() = runBlocking {
        val app = ApplicationProvider.getApplicationContext<Context>()
        val profile = File(app.filesDir, "offline-test-${UUID.randomUUID()}").apply { mkdirs() }
        try {
            val directory = File(profile, "offline-audio").apply { mkdirs() }
            val expected = testWav()
            fixture(directory, "valid", expected, expected)
            fixture(directory, "truncated", expected, expected.copyOf(3))
            val corrupt = expected.copyOf().also { it[it.lastIndex] = 1 }
            fixture(directory, "corrupt", expected, corrupt)
            val interrupted = File(directory, "interrupted.part").apply { writeBytes(expected) }
            val orphan = File(directory, "${hash("orphan".toByteArray())}.audio")
            orphan.writeBytes(expected)
            val context =
                object : ContextWrapper(app) {
                    override fun getFilesDir(): File = profile

                    override fun getCacheDir(): File = File(profile, "cache").apply { mkdirs() }
                }
            val offline = AndroidOffline(context, this) { error("Restore must use disk only") }

            offline.awaitReady()

            assertEquals(listOf("valid"), offline.entries.value.map { it.track.id })
            val source = checkNotNull(offline.find("valid"))
            assertTrue(source.uri.startsWith("file:"))
            assertNull(offline.find("truncated"))
            assertNull(offline.find("corrupt"))
            assertFalse(interrupted.exists())
            assertFalse(orphan.exists())

            withContext(Dispatchers.Main) {
                val track = offline.entries.value.single().track
                val audio = AndroidAudio(context, SourceHttp.client()) { track }
                try {
                    audio.open(source)
                    withTimeout(10_000) { audio.state.first { it.positionMs >= 300L } }
                    audio.setLoudnessNormalization(true)
                    audio.seek(1_000)
                    withTimeout(10_000) { audio.state.first { it.positionMs >= 1_200L } }
                } finally {
                    audio.close()
                }
            }

            offline.delete("valid")
            assertNull(offline.find("valid"))
            val reopened = AndroidOffline(context, this) { error("Restore must use disk only") }
            reopened.awaitReady()
            assertTrue(reopened.entries.value.isEmpty())
        } finally {
            profile.deleteRecursively()
        }
    }

    private fun fixture(directory: File, id: String, expected: ByteArray, actual: ByteArray) {
        val key = hash(id.toByteArray())
        File(directory, "$key.audio").writeBytes(actual)
        File(directory, "$key.json")
            .writeText(
                """{"id":"$id","title":"Title","artist":"Artist","bytes":${expected.size},"sha256":"${hash(expected)}"}"""
            )
    }

    private fun hash(bytes: ByteArray) =
        MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }

    private fun testWav(): ByteArray {
        val sampleRate = 8_000
        val bytes = sampleRate * 2 * 2
        return ByteBuffer.allocate(44 + bytes)
            .order(ByteOrder.LITTLE_ENDIAN)
            .apply {
                put("RIFF".toByteArray())
                putInt(36 + bytes)
                put("WAVEfmt ".toByteArray())
                putInt(16)
                putShort(1)
                putShort(1)
                putInt(sampleRate)
                putInt(sampleRate * 2)
                putShort(2)
                putShort(16)
                put("data".toByteArray())
                putInt(bytes)
            }
            .array()
    }
}
