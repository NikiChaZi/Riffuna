package riffuna.android

import android.net.Uri
import androidx.media3.common.C
import androidx.media3.datasource.DataSource
import androidx.media3.datasource.DataSpec
import androidx.media3.datasource.TransferListener
import java.io.IOException
import java.io.InputStream
import java.util.concurrent.CopyOnWriteArrayList
import okhttp3.Call
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response

/** Google audio is read in bounded HTTP ranges, including the first request at byte zero. */
@androidx.annotation.OptIn(androidx.media3.common.util.UnstableApi::class)
internal class RangeAudioDataSource(
    private val client: OkHttpClient,
    private val headers: () -> Map<String, String>,
) : DataSource {
    companion object {
        const val CHUNK = 1024L * 1024
    }

    private val listeners = CopyOnWriteArrayList<TransferListener>()
    private var spec: DataSpec? = null
    private var snapshot = emptyMap<String, String>()
    private var position = 0L
    private var endExclusive = Long.MAX_VALUE
    private var total: Long? = null
    private var chunkEnd = 0L
    private var response: Response? = null
    private var stream: InputStream? = null
    @Volatile private var call: Call? = null
    @Volatile private var cancelled = false
    private var started = false

    override fun addTransferListener(transferListener: TransferListener) {
        listeners.addIfAbsent(transferListener)
    }

    override fun getUri(): Uri? = spec?.uri

    override fun getResponseHeaders(): Map<String, List<String>> =
        response?.headers?.toMultimap().orEmpty()

    override fun open(dataSpec: DataSpec): Long {
        close()
        cancelled = false
        require(SourceTransportPolicy.allowed(dataSpec.uri.toString(), audioOnly = true))
        require(dataSpec.httpMethod == DataSpec.HTTP_METHOD_GET)
        spec = dataSpec
        snapshot = headers().toMap() + dataSpec.httpRequestHeaders
        position = dataSpec.position
        endExclusive =
            if (dataSpec.length == C.LENGTH_UNSET.toLong()) Long.MAX_VALUE
            else Math.addExact(position, dataSpec.length)
        listeners.forEach { it.onTransferInitializing(this, dataSpec, true) }
        try {
            openChunk()
            started = true
            listeners.forEach { it.onTransferStart(this, dataSpec, true) }
            return endExclusive - position
        } catch (error: Exception) {
            close()
            throw error
        }
    }

    private fun openChunk() {
        response?.close()
        response = null
        stream = null
        val data = checkNotNull(spec)
        val last = minOf(position + CHUNK - 1, endExclusive - 1)
        val request =
            Request.Builder()
                .url(data.uri.toString())
                .apply {
                    snapshot.forEach { (key, value) ->
                        if (!key.equals("Range", true)) header(key, value)
                    }
                    header("Range", "bytes=$position-$last")
                    header("Accept-Encoding", "identity")
                }
                .build()
        val result =
            SourceHttp.execute(
                client,
                request,
                audioOnly = true,
                onCall = { call = it },
                cancelled = { cancelled },
            )
        try {
            if (result.code != 206) throw IOException("Audio HTTP " + result.code)
            val match =
                Regex("bytes (\\d+)-(\\d+)/(\\d+)")
                    .matchEntire(result.header("Content-Range").orEmpty())
                    ?: throw IOException("Invalid audio range")
            val first = match.groupValues[1].toLong()
            val final = match.groupValues[2].toLong()
            val size = match.groupValues[3].toLong()
            if (
                first != position ||
                    final < first ||
                    final > last ||
                    size <= final ||
                    (total != null && total != size)
            )
                throw IOException("Mismatched audio range")
            total = size
            endExclusive = minOf(endExclusive, size)
            chunkEnd = final + 1
            response = result
            stream = result.body?.byteStream() ?: throw IOException("Empty audio body")
        } catch (error: Exception) {
            result.close()
            throw error
        }
    }

    override fun read(buffer: ByteArray, offset: Int, length: Int): Int {
        if (length == 0) return 0
        if (position >= endExclusive) return C.RESULT_END_OF_INPUT
        if (position >= chunkEnd) openChunk()
        val count =
            checkNotNull(stream)
                .read(
                    buffer,
                    offset,
                    minOf(length.toLong(), chunkEnd - position, endExclusive - position).toInt(),
                )
        if (count < 0) throw IOException("Truncated audio range")
        position += count
        spec?.let { data -> listeners.forEach { it.onBytesTransferred(this, data, true, count) } }
        return count
    }

    override fun close() {
        cancelled = true
        call?.cancel()
        call = null
        response?.close()
        response = null
        stream = null
        val data = spec
        if (started && data != null) listeners.forEach { it.onTransferEnd(this, data, true) }
        spec = null
        started = false
        total = null
    }
}
