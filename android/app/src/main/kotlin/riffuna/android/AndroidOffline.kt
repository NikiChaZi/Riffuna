package riffuna.android

import android.content.Context
import android.net.Uri
import androidx.media3.common.C
import androidx.media3.datasource.DataSpec
import java.io.File
import java.io.IOException
import java.security.MessageDigest
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import okhttp3.Call
import riffuna.core.AudioSource
import riffuna.core.Track
import riffuna.core.isLocalFile

private const val MIB = 1024L * 1024

internal enum class AndroidOfflineStatus {
    Queued,
    Downloading,
    Ready,
    Failed,
}

internal data class AndroidOfflineEntry(
    val track: Track,
    val status: AndroidOfflineStatus,
    val bytes: Long = 0,
    val total: Long = 0,
    val error: String? = null,
)

@Serializable
private data class OfflineRecord(
    val id: String,
    val title: String,
    val artist: String,
    val duration: Int = 0,
    val version: String = "",
    val bytes: Long,
    val sha256: String,
) {
    fun entry() =
        AndroidOfflineEntry(
            Track(id, title, artist, duration, version = version),
            AndroidOfflineStatus.Ready,
            bytes,
            bytes,
        )
}

@androidx.annotation.OptIn(androidx.media3.common.util.UnstableApi::class)
internal class AndroidOffline(
    context: Context,
    private val scope: CoroutineScope,
    storageName: String = "offline-audio",
    private val resolveRemote: suspend (Track) -> AudioSource,
) {
    private class Transfer {
        lateinit var job: Job
        var call: Call? = null
    }

    private val lock = Any()
    private val transferQueue = Mutex()
    private val directory = File(context.filesDir, storageName)
    private val settings = context.getSharedPreferences(storageName, Context.MODE_PRIVATE)
    private val http = SourceHttp.client()
    private val active = mutableMapOf<String, Transfer>()
    private val items = linkedMapOf<String, AndroidOfflineEntry>()
    private val verifiedChanges = mutableMapOf<String, Long>()
    private var restoring = true
    private var clearOnRestore = false
    private val mutableEntries = MutableStateFlow<List<AndroidOfflineEntry>>(emptyList())
    val entries = mutableEntries.asStateFlow()
    private val mutableLimit = MutableStateFlow(settings.getInt("capacity-mib", 1024))
    val limitMiB = mutableLimit.asStateFlow()
    val capacitiesMiB = listOf(256, 512, 1024, 2048, 4096)

    private val restored =
        scope.async(Dispatchers.IO) {
            try {
                restore()
            } finally {
                synchronized(lock) { restoring = false }
            }
        }

    suspend fun awaitReady() = restored.await()

    suspend fun findForPlayback(id: String): AudioSource? {
        if (!recordFile(id).isFile) return null
        awaitReady()
        return find(id)
    }

    fun setLimitMiB(value: Int) {
        require(value in capacitiesMiB)
        synchronized(lock) {
            settings.edit().putInt("capacity-mib", value).apply()
            mutableLimit.value = value
        }
    }

    fun find(id: String): AudioSource? =
        synchronized(lock) {
            val entry = items[id]?.takeIf { it.status == AndroidOfflineStatus.Ready } ?: return null
            val file = audioFile(id)
            if (
                !recordFile(id).isFile ||
                    !file.isFile ||
                    file.length() != entry.bytes ||
                    file.lastModified() != verifiedChanges[id]
            )
                return null
            AudioSource(Uri.fromFile(file).toString())
        }

    fun enqueue(tracks: List<Track>) = tracks.forEach(::enqueue)

    fun enqueue(track: Track) {
        if (track.isLocalFile || track.id.isBlank()) return
        synchronized(lock) {
            if (find(track.id) != null || track.id in active) return
            val transfer = Transfer()
            transfer.job =
                scope.launch(Dispatchers.IO, start = CoroutineStart.LAZY) {
                    try {
                        awaitReady()
                        transferQueue.withLock {
                            if (find(track.id) == null) download(track, transfer)
                        }
                    } catch (cancelled: CancellationException) {
                        throw cancelled
                    } catch (failure: Exception) {
                        synchronized(lock) {
                            if (active[track.id] === transfer) {
                                update(
                                    AndroidOfflineEntry(
                                        track,
                                        AndroidOfflineStatus.Failed,
                                        error =
                                            if (failure is OfflineCapacityException)
                                                "Недостаточно места для загрузки"
                                            else "Не удалось скачать трек",
                                    )
                                )
                            }
                        }
                    } finally {
                        synchronized(lock) {
                            if (active[track.id] === transfer) active.remove(track.id)
                        }
                    }
                }
            active[track.id] = transfer
            update(AndroidOfflineEntry(track, AndroidOfflineStatus.Queued))
            transfer.job.start()
        }
    }

    fun cancel(id: String) {
        synchronized(lock) {
            val transfer = active.remove(id) ?: return
            transfer.job.cancel()
            transfer.call?.cancel()
            if (items[id]?.status != AndroidOfflineStatus.Ready) {
                items.remove(id)
                publish()
            }
        }
    }

    fun delete(id: String) {
        synchronized(lock) {
            cancel(id)
            if (!removeFiles(id) && recordFile(id).isFile && audioFile(id).isFile) {
                items[id]?.let { update(it.copy(error = "Не удалось удалить загрузку")) }
                return
            }
            items.remove(id)
            verifiedChanges.remove(id)
            publish()
        }
    }

    fun cancelAll() {
        synchronized(lock) { active.keys.toList().forEach(::cancel) }
    }

    fun deleteAll() {
        synchronized(lock) {
            if (restoring) clearOnRestore = true
            (items.keys + active.keys).forEach(::delete)
        }
    }

    private fun restore() {
        if (!directory.mkdirs() && !directory.isDirectory) return
        val files = directory.listFiles().orEmpty()
        for (metadata in files.filter { it.extension == "json" }) {
            val record =
                runCatching {
                        if (metadata.length() !in 1..65536) return@runCatching null
                        Json.decodeFromString<OfflineRecord>(metadata.readText())
                    }
                    .getOrNull()
            val audio = File(directory, metadata.nameWithoutExtension + ".audio")
            val valid =
                record != null &&
                    metadata == recordFile(record.id) &&
                    record.bytes > 0 &&
                    audio.isFile &&
                    audio.length() == record.bytes &&
                    runCatching { checksum(audio) == record.sha256 }.getOrDefault(false)
            synchronized(lock) {
                if (!clearOnRestore && valid && metadata.isFile && audio.isFile) {
                    verifiedChanges[record.id] = audio.lastModified()
                    update(record.entry())
                } else {
                    metadata.delete()
                    audio.delete()
                }
            }
        }
        for (file in files) {
            if (
                file.extension == "part" ||
                    (file.extension == "audio" &&
                        !File(directory, file.nameWithoutExtension + ".json").isFile)
            )
                file.delete()
        }
    }

    private suspend fun download(track: Track, transfer: Transfer) {
        if (!directory.isDirectory) throw IOException("Offline storage unavailable")
        val source = resolveRemote(track)
        val job = currentCoroutineContext().job
        val input =
            RangeAudioDataSource(
                http,
                onCall = { call -> synchronized(lock) { transfer.call = call } },
                isCancelled = { !job.isActive },
            ) {
                source.headers
            }
        val audio = File.createTempFile("audio-", ".part", directory)
        var metadata: File? = null
        try {
            job.ensureActive()
            val uri = Uri.parse(source.uri)
            val total = input.open(DataSpec(uri))
            val advertised = uri.getQueryParameter("clen")?.toLongOrNull()
            if (total <= 0 || (advertised != null && advertised != total)) {
                throw IOException("Invalid offline audio size")
            }
            synchronized(lock) { checkCapacity(total) }
            val digest = MessageDigest.getInstance("SHA-256")
            var bytes = 0L
            var lastProgress = 0L
            audio.outputStream().use { output ->
                val buffer = ByteArray(64 * 1024)
                while (bytes < total) {
                    job.ensureActive()
                    val read = input.read(buffer, 0, buffer.size)
                    if (read == C.RESULT_END_OF_INPUT) throw IOException("Incomplete offline audio")
                    output.write(buffer, 0, read)
                    digest.update(buffer, 0, read)
                    bytes += read
                    val now = android.os.SystemClock.elapsedRealtime()
                    if (now - lastProgress >= 200) {
                        synchronized(lock) {
                            if (active[track.id] === transfer) {
                                update(
                                    AndroidOfflineEntry(
                                        track,
                                        AndroidOfflineStatus.Downloading,
                                        bytes,
                                        total,
                                    )
                                )
                            }
                        }
                        lastProgress = now
                    }
                }
                output.fd.sync()
            }

            val record =
                OfflineRecord(
                    track.id,
                    track.title,
                    track.artist,
                    track.duration,
                    track.version,
                    bytes,
                    digest.digest().hex(),
                )
            val stagedMetadata = File.createTempFile("metadata-", ".part", directory)
            metadata = stagedMetadata
            stagedMetadata.outputStream().use { output ->
                output.write(Json.encodeToString(record).toByteArray(Charsets.UTF_8))
                output.fd.sync()
            }
            synchronized(lock) {
                job.ensureActive()
                if (active[track.id] !== transfer) throw CancellationException()
                checkCapacity(total)
                if (!removeFiles(track.id) || !audio.renameTo(audioFile(track.id))) {
                    throw IOException("Could not store offline audio")
                }
                if (!stagedMetadata.renameTo(recordFile(track.id))) {
                    audioFile(track.id).delete()
                    throw IOException("Could not store offline metadata")
                }
                verifiedChanges[track.id] = audioFile(track.id).lastModified()
                update(record.entry())
            }
        } finally {
            input.close()
            audio.delete()
            metadata?.delete()
        }
    }

    private fun checkCapacity(bytes: Long) {
        val used =
            items.values.filter { it.status == AndroidOfflineStatus.Ready }.sumOf { it.bytes }
        if (bytes > limitMiB.value * MIB - used) throw OfflineCapacityException()
    }

    private fun update(entry: AndroidOfflineEntry) {
        items[entry.track.id] = entry
        publish()
    }

    private fun publish() {
        mutableEntries.value = items.values.toList()
    }

    private fun removeFiles(id: String): Boolean {
        val record = recordFile(id)
        val audio = audioFile(id)
        val recordRemoved = !record.exists() || record.delete()
        val audioRemoved = !audio.exists() || audio.delete()
        return recordRemoved && audioRemoved
    }

    private fun audioFile(id: String) = File(directory, "${key(id)}.audio")

    private fun recordFile(id: String) = File(directory, "${key(id)}.json")

    private fun key(id: String) =
        MessageDigest.getInstance("SHA-256").digest(id.toByteArray(Charsets.UTF_8)).hex()

    private fun checksum(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input ->
            val buffer = ByteArray(64 * 1024)
            while (true) {
                val read = input.read(buffer)
                if (read < 0) break
                digest.update(buffer, 0, read)
            }
        }
        return digest.digest().hex()
    }

    private fun ByteArray.hex() = joinToString("") { "%02x".format(it) }

    private class OfflineCapacityException : IOException()
}
