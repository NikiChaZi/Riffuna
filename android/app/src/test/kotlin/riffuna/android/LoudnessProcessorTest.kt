package riffuna.android

import androidx.media3.common.C
import androidx.media3.common.audio.AudioProcessor
import androidx.media3.common.audio.AudioProcessor.AudioFormat
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.abs
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class LoudnessProcessorTest {
    private fun processor() =
        LoudnessProcessor().apply {
            configure(AudioFormat(48_000, 2, C.ENCODING_PCM_16BIT))
            flush()
        }

    private fun LoudnessProcessor.output(peak: Int): List<Int> {
        val input = ByteBuffer.allocateDirect(96_000).order(ByteOrder.nativeOrder())
        repeat(48_000) { input.putShort((if (it % 2 == 0) peak else -peak).toShort()) }
        input.flip()
        queueInput(input)
        val decoded = getOutput().order(ByteOrder.nativeOrder()).asShortBuffer()
        return List(decoded.remaining()) { decoded.get().toInt() }
    }

    @Test
    fun sharedEmptyBufferDuringDrainDoesNotCopyIntoItself() {
        val processor = processor()
        processor.queueInput(AudioProcessor.EMPTY_BUFFER)
        assertEquals(0, processor.getOutput().remaining())
        assertEquals(48_000, processor.output(2_000).size)
    }

    @Test
    fun normalizesPcmWhileRetainingSampleCountAndLimitingPeaks() {
        val processor = processor()
        val untouched = processor.output(2_000)
        assertEquals(48_000, untouched.size)
        assertTrue(untouched.all { abs(it) == 2_000 })
        processor.enabled = true
        val boosted = processor.output(2_000)
        assertEquals(48_000, boosted.size)
        assertTrue(boosted.last() < -2_500)
        processor.flush()
        val limited = processor.output(32_760)
        assertTrue(limited.all { abs(it) <= 27_500 })
        assertTrue(abs(limited.last()) < 16_000)
        assertTrue(processor.output(0).all { it == 0 })
    }
}
