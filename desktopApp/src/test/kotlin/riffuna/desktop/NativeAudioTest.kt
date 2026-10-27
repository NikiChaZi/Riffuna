package riffuna.desktop

import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.file.Files
import java.nio.file.Path
import kotlin.test.*
import kotlinx.coroutines.*
import riffuna.core.AudioSource

class NativeAudioTest {
    @Test
    fun realLibmpvKeepsPauseAndSeeksWithoutReload() = runBlocking {
        val home = Path.of(System.getProperty("user.dir")).parent
        val dll = home.resolve("vendor/libmpv/libmpv-2.dll")
        org.junit.Assume.assumeTrue(Files.isRegularFile(dll))
        val payload = ByteArray(48000 * 4 * 6)
        val header = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN)
        header
            .put("RIFF".toByteArray())
            .putInt(36 + payload.size)
            .put("WAVEfmt ".toByteArray())
            .putInt(16)
            .putShort(1)
            .putShort(2)
            .putInt(48000)
            .putInt(192000)
            .putShort(4)
            .putShort(16)
            .put("data".toByteArray())
            .putInt(payload.size)
        val file = Files.createTempFile("riffuna-native-test", ".wav")
        Files.write(file, header.array() + payload)
        val audio = MpvAudio(dll, audioDriver = if (System.getenv("CI") == "true") "null" else null)
        try {
            assertTrue(audio.devices().any { it.id == "auto" })
            audio.selectDevice("auto")
            audio.setVolume(0f)
            audio.open(AudioSource(file.toUri().toString()))
            withTimeout(8000) { while (audio.state.value.positionMs < 200) delay(50) }
            audio.pause()
            delay(200)
            val held = audio.state.value.positionMs
            delay(250)
            assertTrue(kotlin.math.abs(audio.state.value.positionMs - held) < 200)
            audio.seek(2500)
            withTimeout(4000) { while (audio.state.value.positionMs < 2350) delay(50) }
            assertFalse(audio.state.value.playing)
            audio.resume()
            withTimeout(4000) { while (audio.state.value.positionMs < 2800) delay(50) }
            assertTrue(audio.state.value.playing)
            audio.open(
                AudioSource(
                    file.resolveSibling("missing-audio-${System.nanoTime()}.m4a").toUri().toString()
                )
            )
            withTimeout(5000) { while (audio.state.value.error == null) delay(50) }
            assertFalse(audio.state.value.playing)
        } finally {
            audio.close()
            Files.deleteIfExists(file)
        }
    }
}
