package riffuna.android

import androidx.annotation.OptIn
import androidx.media3.common.C
import androidx.media3.common.audio.AudioProcessor.AudioFormat
import androidx.media3.common.audio.BaseAudioProcessor
import androidx.media3.common.util.UnstableApi
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.abs
import kotlin.math.exp
import kotlin.math.sqrt

/** Levels decoded PCM with a slow RMS estimate and limits peaks without buffering audio. */
@OptIn(UnstableApi::class)
internal class LoudnessProcessor : BaseAudioProcessor() {
    @Volatile var enabled = false
    private var power = 0.0
    private var gain = 1.0

    override fun onConfigure(inputAudioFormat: AudioFormat): AudioFormat =
        if (inputAudioFormat.encoding == C.ENCODING_PCM_16BIT) inputAudioFormat
        else AudioFormat.NOT_SET

    override fun onFlush() {
        power = 0.0
        gain = 1.0
    }

    override fun queueInput(inputBuffer: ByteBuffer) {
        // Media3 can pass the shared empty buffer while draining the processor chain.
        if (!inputBuffer.hasRemaining()) return
        val output = replaceOutputBuffer(inputBuffer.remaining())
        if (!enabled) {
            output.put(inputBuffer)
            onFlush()
        } else {
            val channels = inputAudioFormat.channelCount
            val rate = inputAudioFormat.sampleRate
            val maximumSamples = (rate / 100) * channels
            val input = inputBuffer.order(ByteOrder.nativeOrder()).asShortBuffer()
            while (input.hasRemaining()) {
                val count = minOf(input.remaining(), maximumSamples)
                val start = input.position()
                var squareSum = 0.0
                var peak = 1
                repeat(count) {
                    val sample = input.get().toInt()
                    squareSum += sample.toDouble() * sample
                    peak = maxOf(peak, abs(sample))
                }
                val seconds = count.toDouble() / (rate * channels)
                val current = squareSum / count
                if (current >= 96.0 * 96) {
                    val blend = 1 - exp(-seconds / 2)
                    power = if (power == 0.0) current else power + (current - power) * blend
                }
                val target = if (power > 0) (5_200 / sqrt(power)).coerceIn(0.25, 2.0) else 1.0
                val limit = 27_500.0 / peak
                val initial = minOf(gain, limit)
                val blend = 1 - exp(-seconds / if (target < gain) 0.15 else 0.6)
                val next = minOf(gain + (target - gain) * blend, limit)
                input.position(start)
                val step = (next - initial) / count
                repeat(count) { index ->
                    output.putShort((input.get() * (initial + step * index)).toInt().toShort())
                }
                gain = next
            }
            inputBuffer.position(inputBuffer.limit())
        }
        output.flip()
    }
}
