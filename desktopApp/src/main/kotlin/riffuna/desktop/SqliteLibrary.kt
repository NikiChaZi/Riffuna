package riffuna.desktop

import java.nio.file.Files
import java.nio.file.Path
import java.sql.Connection
import java.sql.DriverManager
import java.sql.ResultSet
import riffuna.core.*

class SqliteLibrary(val path: Path) : MusicLibrary {
    private val db: Connection

    init {
        Files.createDirectories(path.parent)
        db = DriverManager.getConnection("jdbc:sqlite:" + path.toAbsolutePath())
        db.createStatement().use { s ->
            s.execute("PRAGMA foreign_keys=ON")
            s.execute("PRAGMA busy_timeout=5000")
            s.execute(
                "CREATE TABLE IF NOT EXISTS tracks(video_id TEXT PRIMARY KEY,title TEXT NOT NULL,artist TEXT NOT NULL,duration INTEGER NOT NULL,thumbnail TEXT NOT NULL)"
            )
            s.execute(
                "CREATE TABLE IF NOT EXISTS likes(video_id TEXT PRIMARY KEY REFERENCES tracks(video_id),liked_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')))"
            )
            s.execute(
                "CREATE TABLE IF NOT EXISTS plays(id INTEGER PRIMARY KEY,video_id TEXT NOT NULL REFERENCES tracks(video_id),played_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')))"
            )
            s.execute(
                "CREATE TABLE IF NOT EXISTS queue(position INTEGER PRIMARY KEY,video_id TEXT NOT NULL REFERENCES tracks(video_id))"
            )
            s.execute(
                "CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL)"
            )
            s.execute(
                "CREATE TABLE IF NOT EXISTS user_playlists(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,description TEXT NOT NULL DEFAULT '')"
            )
            s.execute(
                "CREATE TABLE IF NOT EXISTS playlist_items(playlist_id INTEGER NOT NULL REFERENCES user_playlists(id) ON DELETE CASCADE,video_id TEXT NOT NULL REFERENCES tracks(video_id),position INTEGER NOT NULL,PRIMARY KEY(playlist_id,video_id),UNIQUE(playlist_id,position))"
            )
        }
        val columns =
            db.createStatement().use { st ->
                st.executeQuery("PRAGMA table_info(user_playlists)").use { r ->
                    buildSet { while (r.next()) add(r.getString("name")) }
                }
            }
        if ("description" !in columns)
            db.createStatement().use {
                it.execute(
                    "ALTER TABLE user_playlists ADD COLUMN description TEXT NOT NULL DEFAULT ''"
                )
            }
    }

    private fun track(r: ResultSet) =
        Track(
            r.getString("video_id"),
            r.getString("title"),
            r.getString("artist"),
            r.getInt("duration"),
            r.getString("thumbnail"),
            version = MusicRules.profile(r.getString("title")).joinToString(" · "),
        )

    private fun rows(sql: String, vararg args: Any): List<Track> =
        db.prepareStatement(sql).use { st ->
            args.forEachIndexed { i, v -> st.setObject(i + 1, v) }
            st.executeQuery().use { r -> buildList { while (r.next()) add(track(r)) } }
        }

    private fun update(sql: String, vararg args: Any) =
        db.prepareStatement(sql).use { st ->
            args.forEachIndexed { i, v -> st.setObject(i + 1, v) }
            st.executeUpdate()
        }

    private fun upsert(t: Track) {
        update(
            "INSERT INTO tracks VALUES(?,?,?,?,?) ON CONFLICT(video_id) DO UPDATE SET title=excluded.title,artist=excluded.artist,duration=excluded.duration,thumbnail=excluded.thumbnail",
            t.id,
            t.title,
            t.artist,
            t.duration,
            t.thumbnail,
        )
    }

    private fun transaction(block: () -> Unit) {
        val previous = db.autoCommit
        db.autoCommit = false
        try {
            block()
            db.commit()
        } catch (e: Exception) {
            db.rollback()
            throw e
        } finally {
            db.autoCommit = previous
        }
    }

    @Synchronized
    override fun likes() =
        rows(
            "SELECT t.* FROM likes l JOIN tracks t USING(video_id) ORDER BY l.liked_at DESC,l.rowid DESC"
        )

    @Synchronized
    override fun history() =
        rows(
            "SELECT t.* FROM tracks t JOIN(SELECT video_id,MAX(id) latest FROM plays GROUP BY video_id)p USING(video_id) ORDER BY p.latest DESC LIMIT 100"
        )

    @Synchronized
    override fun queue(): Pair<List<Track>, Int> {
        val tracks =
            rows("SELECT t.* FROM queue q JOIN tracks t USING(video_id) ORDER BY q.position")
        val index = setting("queue_index", "-1").toIntOrNull() ?: -1
        return tracks to if (index in tracks.indices) index else -1
    }

    @Synchronized
    override fun current() =
        rows("SELECT * FROM tracks WHERE video_id=?", setting("current_track", "")).firstOrNull()

    @Synchronized
    override fun saveQueue(tracks: List<Track>, index: Int, current: Track?) = transaction {
        update("DELETE FROM queue")
        tracks.forEachIndexed { i, t ->
            upsert(t)
            update("INSERT INTO queue VALUES(?,?)", i, t.id)
        }
        current?.let(::upsert)
        setSetting("queue_index", index.toString())
        setSetting("current_track", current?.id ?: "")
    }

    @Synchronized
    override fun like(track: Track, value: Boolean) = transaction {
        upsert(track)
        if (value) update("INSERT OR IGNORE INTO likes(video_id) VALUES(?)", track.id)
        else update("DELETE FROM likes WHERE video_id=?", track.id)
    }

    @Synchronized
    override fun recordPlay(track: Track) = transaction {
        upsert(track)
        update("INSERT INTO plays(video_id) VALUES(?)", track.id)
    }

    @Synchronized
    override fun playlists(): List<PlaylistSummary> =
        db.createStatement().use { st ->
            st.executeQuery(
                    "SELECT p.id,p.name,p.description,COUNT(i.video_id) track_count,COALESCE((SELECT t.thumbnail FROM playlist_items f JOIN tracks t USING(video_id) WHERE f.playlist_id=p.id ORDER BY f.position LIMIT 1),'') thumbnail FROM user_playlists p LEFT JOIN playlist_items i ON i.playlist_id=p.id GROUP BY p.id ORDER BY p.id DESC"
                )
                .use { r ->
                    buildList {
                        while (r.next()) add(
                            PlaylistSummary(
                                r.getLong("id"),
                                r.getString("name"),
                                r.getString("description"),
                                r.getString("thumbnail"),
                                r.getInt("track_count"),
                            )
                        )
                    }
                }
        }

    @Synchronized
    override fun playlistTracks(id: Long) =
        rows(
            "SELECT t.* FROM playlist_items i JOIN tracks t USING(video_id) WHERE i.playlist_id=? ORDER BY i.position",
            id,
        )

    @Synchronized
    override fun createPlaylist(name: String): Long {
        require(name.trim().length in 1..100)
        update("INSERT INTO user_playlists(name) VALUES(?)", name.trim())
        return db.createStatement().use {
            it.executeQuery("SELECT last_insert_rowid()").use { r ->
                r.next()
                r.getLong(1)
            }
        }
    }

    @Synchronized
    override fun addToPlaylist(id: Long, tracks: List<Track>) = transaction {
        tracks.forEach { t ->
            upsert(t)
            update(
                "INSERT OR IGNORE INTO playlist_items SELECT ?,?,COUNT(*) FROM playlist_items WHERE playlist_id=?",
                id,
                t.id,
                id,
            )
        }
    }

    @Synchronized
    override fun editPlaylist(id: Long, name: String, description: String) {
        require(name.trim().length in 1..100 && description.length <= 2000)
        check(
            update(
                "UPDATE user_playlists SET name=?,description=? WHERE id=?",
                name.trim(),
                description,
                id,
            ) == 1
        )
    }

    @Synchronized
    override fun deletePlaylist(id: Long) {
        update("DELETE FROM user_playlists WHERE id=?", id)
    }

    @Synchronized
    override fun removeFromPlaylist(id: Long, trackId: String) = transaction {
        val tracks = playlistTracks(id).filter { it.id != trackId }
        update("DELETE FROM playlist_items WHERE playlist_id=?", id)
        tracks.forEachIndexed { index, track ->
            update("INSERT INTO playlist_items VALUES(?,?,?)", id, track.id, index)
        }
    }

    @Synchronized
    override fun reorderPlaylist(id: Long, ids: List<String>) = transaction {
        val known = playlistTracks(id).map { it.id }
        require(ids.size == known.size && ids.toSet() == known.toSet())
        update("DELETE FROM playlist_items WHERE playlist_id=?", id)
        ids.forEachIndexed { index, key ->
            update("INSERT INTO playlist_items VALUES(?,?,?)", id, key, index)
        }
    }

    @Synchronized
    override fun duplicatePlaylist(id: Long): Long {
        val original = playlists().firstOrNull { it.id == id } ?: error("Playlist missing")
        var copied = 0L
        transaction {
            copied = createPlaylist(original.name.take(90) + " (копия)")
            editPlaylist(copied, (original.name.take(90) + " (копия)"), original.description)
            update(
                "INSERT INTO playlist_items SELECT ?,video_id,position FROM playlist_items WHERE playlist_id=?",
                copied,
                id,
            )
        }
        return copied
    }

    @Synchronized
    override fun setPreferred(original: Track, replacement: Track?) = transaction {
        replacement?.let(::upsert)
        setSetting(MusicRules.workKey(original), replacement?.id ?: "")
    }

    @Synchronized
    override fun setting(name: String, default: String): String =
        db.prepareStatement("SELECT value FROM settings WHERE key=?").use { st ->
            st.setString(1, name)
            st.executeQuery().use { r -> if (r.next()) r.getString(1) else default }
        }

    @Synchronized
    override fun setSetting(name: String, value: String) {
        update("INSERT OR REPLACE INTO settings VALUES(?,?)", name, value)
    }

    @Synchronized
    override fun preferred(track: Track): Track {
        val selected =
            setting(RecordingIdentity.key(track), setting(RecordingIdentity.legacyKey(track), ""))
        return if (selected.isBlank()) track
        else rows("SELECT * FROM tracks WHERE video_id=?", selected).firstOrNull() ?: track
    }

    @Synchronized
    override fun close() {
        db.close()
    }
}
