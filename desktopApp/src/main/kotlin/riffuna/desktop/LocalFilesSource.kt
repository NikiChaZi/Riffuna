package riffuna.desktop

import java.nio.file.*
import java.security.MessageDigest
import java.sql.DriverManager
import java.util.Locale
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import riffuna.core.*

internal data class LocalMetadata(val title: String, val artist: String, val duration: Int)

/** Local paths never enter the YouTube protocol; only user-selected files are indexed. */
internal class LocalFilesSource(
    private val database: Path,
    private val readMetadata: (Path) -> LocalMetadata,
) : MusicSource {
    companion object {
        val extensions = setOf("mp3", "flac", "ogg", "opus", "m4a", "aac", "wav", "wma")

        fun owns(track: Track) = track.isLocalFile
    }

    init {
        Files.createDirectories(database.toAbsolutePath().parent)
        connection().use { db ->
            db.createStatement().use {
                it.execute(
                    "CREATE TABLE IF NOT EXISTS local_files(id TEXT PRIMARY KEY,path TEXT UNIQUE NOT NULL,title TEXT NOT NULL,artist TEXT NOT NULL,duration INTEGER NOT NULL)"
                )
            }
        }
    }

    private fun connection() =
        DriverManager.getConnection("jdbc:sqlite:" + database.toAbsolutePath())

    override suspend fun localTracks(): List<Track> =
        connection().use { db ->
            db.createStatement().use { statement ->
                statement
                    .executeQuery(
                        "SELECT id,title,artist,duration FROM local_files ORDER BY artist COLLATE NOCASE,title COLLATE NOCASE,id"
                    )
                    .use { rows ->
                        buildList {
                            while (rows.next()) add(
                                Track(
                                    rows.getString(1),
                                    rows.getString(2),
                                    rows.getString(3),
                                    rows.getInt(4),
                                )
                            )
                        }
                    }
            }
        }

    override suspend fun search(query: String, limit: Int): List<Track> {
        val tokens = MusicText.normalized(query).split(' ').filter { it.isNotBlank() }
        return localTracks()
            .filter { track ->
                val text = MusicText.normalized(track.artist + " " + track.title)
                tokens.all { it in text }
            }
            .take(limit.coerceAtLeast(0))
    }

    override suspend fun resolve(track: Track): AudioSource {
        require(owns(track))
        val path =
            connection().use { db ->
                db.prepareStatement("SELECT path FROM local_files WHERE id=?").use { statement ->
                    statement.setString(1, track.id)
                    statement.executeQuery().use { rows ->
                        if (rows.next()) Path.of(rows.getString(1)) else null
                    }
                }
            } ?: error("Локальная запись не найдена")
        check(Files.isRegularFile(path)) { "Аудиофайл перемещён или удалён" }
        return AudioSource(path.toUri().toString())
    }

    override suspend fun importLocalFiles(paths: List<String>): LocalImportResult {
        require(paths.size <= 10000)
        val files = linkedSetOf<Path>()
        for (value in paths) {
            currentCoroutineContext().ensureActive()
            val path = Path.of(value).toAbsolutePath().normalize()
            if (Files.isDirectory(path))
                Files.walk(path).use { stream ->
                    val iterator = stream.iterator()
                    while (iterator.hasNext()) {
                        currentCoroutineContext().ensureActive()
                        val candidate = iterator.next()
                        if (
                            Files.isRegularFile(candidate) &&
                                !Files.isSymbolicLink(candidate) &&
                                candidate.fileName
                                    .toString()
                                    .substringAfterLast('.')
                                    .lowercase(Locale.ROOT) in extensions
                        ) {
                            require(files.size < 10000) {
                                "За один импорт можно добавить до 10000 файлов"
                            }
                            files.add(candidate.toRealPath())
                        }
                    }
                }
            else if (
                Files.isRegularFile(path) &&
                    path.fileName.toString().substringAfterLast('.').lowercase(Locale.ROOT) in
                        extensions
            )
                files.add(path.toRealPath())
        }
        var imported = 0
        var updated = 0
        var skipped = 0
        connection().use { db ->
            for (path in files) {
                currentCoroutineContext().ensureActive()
                val metadata = runCatching { readMetadata(path) }.getOrNull()
                if (metadata == null) {
                    skipped++
                    continue
                }
                val id =
                    "local-" +
                        MessageDigest.getInstance("SHA-256")
                            .digest(path.toString().toByteArray(Charsets.UTF_8))
                            .joinToString("") { "%02x".format(it) }
                val exists =
                    db.prepareStatement("SELECT 1 FROM local_files WHERE id=?").use { statement ->
                        statement.setString(1, id)
                        statement.executeQuery().use { it.next() }
                    }
                db.prepareStatement(
                        "INSERT INTO local_files VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET path=excluded.path,title=excluded.title,artist=excluded.artist,duration=excluded.duration"
                    )
                    .use { statement ->
                        statement.setString(1, id)
                        statement.setString(2, path.toString())
                        statement.setString(3, metadata.title)
                        statement.setString(4, metadata.artist)
                        statement.setInt(5, metadata.duration)
                        statement.executeUpdate()
                    }
                if (exists) updated++ else imported++
            }
        }
        return LocalImportResult(imported, updated, skipped)
    }
}

/** Routing keeps offline playback independent from remote source availability. */
internal class DeviceMusicSource(
    private val remote: MusicSource,
    private val local: LocalFilesSource,
) : MusicSource by remote {
    override suspend fun localTracks() = local.localTracks()

    override suspend fun importLocalFiles(paths: List<String>) = local.importLocalFiles(paths)

    override suspend fun search(query: String, limit: Int) =
        searchSorted(query, limit, SearchOrder.RELEVANCE)

    override suspend fun searchSorted(query: String, limit: Int, order: SearchOrder): List<Track> {
        val own = local.search(query, limit)
        val online =
            try {
                remote.searchSorted(query, limit, order)
            } catch (e: kotlinx.coroutines.CancellationException) {
                throw e
            } catch (e: Exception) {
                if (own.isEmpty()) throw e else emptyList()
            }
        val combined = (own + online).distinctBy { it.id }
        return (if (order == SearchOrder.VIEWS) combined.sortedByDescending { it.viewCount ?: -1 }
            else combined)
            .take(limit.coerceAtLeast(0))
    }

    override suspend fun resolve(track: Track) =
        if (LocalFilesSource.owns(track)) local.resolve(track) else remote.resolve(track)

    override suspend fun prefetch(track: Track) {
        if (!LocalFilesSource.owns(track)) remote.prefetch(track)
    }

    override fun invalidate(track: Track) {
        if (!LocalFilesSource.owns(track)) remote.invalidate(track)
    }

    override suspend fun alternatives(track: Track) =
        if (LocalFilesSource.owns(track)) emptyList() else remote.alternatives(track)

    override fun close() {
        try {
            remote.close()
        } finally {
            local.close()
        }
    }
}
