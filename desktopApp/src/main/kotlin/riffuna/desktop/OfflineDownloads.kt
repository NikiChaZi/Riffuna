package riffuna.desktop

import java.nio.file.*
import java.security.MessageDigest
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import riffuna.core.Track
import riffuna.core.isLocalFile

internal const val offlineGib = 1024L * 1024 * 1024

@Serializable internal data class OfflineAudio(val bytes: Long, val sha256: String)

@Serializable internal data class OfflineEntry(val track: Track, val audio: OfflineAudio)

internal class OfflineStorageFull : IllegalStateException("Offline storage is full")

internal fun moveOfflineFile(source: Path, destination: Path) {
    try {
        Files.move(
            source,
            destination,
            StandardCopyOption.ATOMIC_MOVE,
            StandardCopyOption.REPLACE_EXISTING,
        )
    } catch (_: AtomicMoveNotSupportedException) {
        Files.move(source, destination, StandardCopyOption.REPLACE_EXISTING)
    }
}

internal class OfflineStore(private val directory: Path) {
    private val json = Json { ignoreUnknownKeys = true }
    private val verified = VerifiedAudioCache()
    private val limitFile = directory.resolve("limit.txt")
    private val metadataName = Regex("[0-9a-f]{64}\\.json")
    @Volatile
    var limit = readLimit()
        private set

    @Volatile
    var entries = readEntries()
        private set

    private fun key(id: String): String =
        MessageDigest.getInstance("SHA-256").digest(id.toByteArray(Charsets.UTF_8)).joinToString(
            ""
        ) {
            "%02x".format(it)
        }

    fun destination(id: String): Path = directory.resolve(key(id) + ".audio")

    private fun metadata(id: String): Path = directory.resolve(key(id) + ".json")

    private fun readLimit(): Long =
        runCatching { Files.readString(limitFile).trim().toLong() }
            .getOrNull()
            ?.takeIf { it in offlineGib..20 * offlineGib } ?: 5 * offlineGib

    private fun readEntries(): Map<String, OfflineEntry> {
        if (!Files.isDirectory(directory)) return emptyMap()
        return Files.list(directory).use { files ->
            files
                .filter { metadataName.matches(it.fileName.toString()) }
                .map { path ->
                    runCatching {
                            check(
                                Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS) &&
                                    Files.size(path) <= 128 * 1024
                            )
                            val entry = json.decodeFromString<OfflineEntry>(Files.readString(path))
                            val file = destination(entry.track.id)
                            check(path == metadata(entry.track.id))
                            check(entry.audio.bytes in 1..offlineGib)
                            check(entry.audio.sha256.matches(Regex("[0-9a-f]{64}")))
                            check(Files.isRegularFile(file, LinkOption.NOFOLLOW_LINKS))
                            check(Files.size(file) == entry.audio.bytes)
                            entry
                        }
                        .getOrNull()
                }
                .filter { it != null }
                .toList()
                .filterNotNull()
                .associateBy { it.track.id }
        }
    }

    fun find(id: String): Path? {
        val entry = entries[id] ?: return null
        return destination(id).takeIf { verified.verify(it, entry.audio.bytes, entry.audio.sha256) }
    }

    fun add(track: Track, audio: OfflineAudio) {
        val entry = OfflineEntry(track, audio)
        write(metadata(track.id), json.encodeToString(entry))
        entries = entries + (track.id to entry)
    }

    fun discardIncomplete(id: String) {
        if (id !in entries) Files.deleteIfExists(destination(id))
    }

    fun remove(id: String) {
        Files.deleteIfExists(destination(id))
        entries = entries - id
        Files.deleteIfExists(metadata(id))
    }

    fun setLimit(bytes: Long) {
        require(bytes in offlineGib..20 * offlineGib)
        if (bytes < entries.values.sumOf { it.audio.bytes }) throw OfflineStorageFull()
        write(limitFile, bytes.toString())
        limit = bytes
    }

    private fun write(path: Path, data: String) {
        Files.createDirectories(directory)
        val temporary = Files.createTempFile(directory, ".offline-", ".part")
        try {
            Files.writeString(temporary, data)
            moveOfflineFile(temporary, path)
        } finally {
            Files.deleteIfExists(temporary)
        }
    }
}

internal data class OfflineTask(
    val track: Track,
    val percent: Int? = null,
    val error: String? = null,
)

internal data class OfflineState(
    val saved: Map<String, OfflineEntry>,
    val limit: Long,
    val tasks: Map<String, OfflineTask> = emptyMap(),
    val message: String? = null,
) {
    val used: Long
        get() = saved.values.sumOf { it.audio.bytes }
}

internal class OfflineDownloads(
    private val store: OfflineStore,
    private val scope: CoroutineScope,
    private val preferred: (Track) -> Track,
    private val playlistTracks: (Long) -> List<Track>,
    private val transfer: suspend (Track, Path, Long, (Long, Long) -> Unit) -> OfflineAudio,
) {
    private val mutable = MutableStateFlow(OfflineState(store.entries, store.limit))
    val state = mutable.asStateFlow()
    private val gate = Mutex()

    fun recording(track: Track): Track = preferred(track)

    fun savePlaylist(id: Long) = save(playlistTracks(id))

    fun save(tracks: List<Track>) = schedule(tracks.map(::recording))

    fun retry(track: Track) = schedule(listOf(track))

    private fun schedule(tracks: List<Track>) {
        val available =
            tracks.filterNot(Track::isLocalFile).distinctBy(Track::id).filter {
                it.id !in state.value.saved &&
                    (it.id !in state.value.tasks || state.value.tasks[it.id]?.error != null)
            }
        if (available.isEmpty()) return
        mutable.update { state ->
            state.copy(
                tasks = state.tasks + available.associate { it.id to OfflineTask(it) },
                message = null,
            )
        }
        scope.launch { for (track in available) gate.withLock { download(track) } }
    }

    private suspend fun download(track: Track) {
        try {
            val remaining = state.value.limit - state.value.used
            if (remaining <= 0) throw OfflineStorageFull()
            val audio =
                transfer(track, store.destination(track.id), remaining) { bytes, total ->
                    val percent = ((100 * bytes) / total).toInt().coerceIn(0, 99)
                    mutable.update { current ->
                        val previous = current.tasks[track.id]
                        if (previous == null || previous.percent == percent) current
                        else
                            current.copy(
                                tasks =
                                    current.tasks + (track.id to previous.copy(percent = percent))
                            )
                    }
                }
            withContext(Dispatchers.IO) { store.add(track, audio) }
            mutable.update { it.copy(saved = store.entries, tasks = it.tasks - track.id) }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            val error =
                if (e is OfflineStorageFull) "Достигнут лимит скачанных треков"
                else "Не удалось сохранить трек. Проверь сеть и место на диске."
            mutable.update {
                it.copy(tasks = it.tasks + (track.id to OfflineTask(track, error = error)))
            }
        } finally {
            withContext(NonCancellable + Dispatchers.IO) {
                runCatching { store.discardIncomplete(track.id) }
            }
        }
    }

    fun remove(id: String) {
        scope.launch {
            gate.withLock {
                val result = withContext(Dispatchers.IO) { runCatching { store.remove(id) } }
                mutable.update {
                    it.copy(
                        saved = store.entries,
                        tasks = it.tasks - id,
                        message =
                            if (result.isFailure)
                                "Не удалось удалить файл. Останови трек и попробуй снова."
                            else null,
                    )
                }
            }
        }
    }

    fun setLimit(bytes: Long) {
        scope.launch {
            gate.withLock {
                val result = withContext(Dispatchers.IO) { runCatching { store.setLimit(bytes) } }
                mutable.update {
                    it.copy(
                        limit = store.limit,
                        message =
                            when (result.exceptionOrNull()) {
                                null -> null
                                is OfflineStorageFull ->
                                    "Выбранный лимит меньше объёма скачанных треков"
                                else -> "Не удалось сохранить лимит"
                            },
                    )
                }
            }
        }
    }
}
