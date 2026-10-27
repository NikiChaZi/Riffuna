package riffuna.android

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import riffuna.core.*

/** A device-private library. Windows data is never read or overwritten. */
class AndroidLibrary(context: Context, name: String = "library.sqlite3") : MusicLibrary {
    private val helper =
        object : SQLiteOpenHelper(context, name, null, 1) {
            override fun onCreate(db: SQLiteDatabase) {
                db.execSQL("CREATE TABLE tracks(id TEXT PRIMARY KEY,payload TEXT NOT NULL)")
                db.execSQL("CREATE TABLE likes(id TEXT PRIMARY KEY,position INTEGER NOT NULL)")
                db.execSQL(
                    "CREATE TABLE history(sequence INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT NOT NULL)"
                )
                db.execSQL("CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
                db.execSQL(
                    "CREATE TABLE playlists(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,description TEXT NOT NULL DEFAULT '')"
                )
                db.execSQL(
                    "CREATE TABLE items(playlist INTEGER NOT NULL,id TEXT NOT NULL,position INTEGER NOT NULL,PRIMARY KEY(playlist,id))"
                )
            }

            override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) = Unit
        }
    private val db = helper.writableDatabase

    private fun put(track: Track) =
        db.execSQL(
            "INSERT OR REPLACE INTO tracks VALUES(?,?)",
            arrayOf(track.id, Json.encodeToString(track)),
        )

    private fun findTrack(id: String): Track? =
        db.rawQuery("SELECT payload FROM tracks WHERE id=?", arrayOf(id)).use {
            if (it.moveToFirst()) Json.decodeFromString<Track>(it.getString(0)) else null
        }

    private fun rows(sql: String, vararg args: String): List<Track> =
        db.rawQuery(sql, args).use { c ->
            buildList { while (c.moveToNext()) add(Json.decodeFromString<Track>(c.getString(0))) }
        }

    private fun <T> transaction(block: () -> T): T {
        db.beginTransaction()
        try {
            val result = block()
            db.setTransactionSuccessful()
            return result
        } finally {
            db.endTransaction()
        }
    }

    @Synchronized
    override fun likes() =
        rows(
            "SELECT t.payload FROM likes l JOIN tracks t ON l.id=t.id ORDER BY l.position DESC,l.rowid DESC"
        )

    @Synchronized
    override fun history() =
        rows(
            "SELECT t.payload FROM tracks t JOIN (SELECT id,MAX(sequence) latest FROM history GROUP BY id) h ON h.id=t.id ORDER BY h.latest DESC LIMIT 100"
        )

    @Synchronized
    override fun queue(): Pair<List<Track>, Int> {
        val tracks =
            runCatching { Json.decodeFromString<List<Track>>(setting("queue", "[]")) }
                .getOrDefault(emptyList())
        val index = setting("queue_index", "-1").toIntOrNull() ?: -1
        return tracks to index.takeIf { it in tracks.indices }.let { it ?: -1 }
    }

    @Synchronized override fun current() = findTrack(setting("current", ""))

    @Synchronized
    override fun saveQueue(tracks: List<Track>, index: Int, current: Track?) = transaction {
        tracks.forEach(::put)
        current?.let(::put)
        setSetting("queue", Json.encodeToString(tracks))
        setSetting("queue_index", index.toString())
        setSetting("current", current?.id ?: "")
    }

    @Synchronized
    override fun like(track: Track, value: Boolean) = transaction {
        put(track)
        if (value)
            db.execSQL(
                "INSERT OR IGNORE INTO likes VALUES(?,?)",
                arrayOf<Any>(track.id, System.currentTimeMillis()),
            )
        else db.execSQL("DELETE FROM likes WHERE id=?", arrayOf(track.id))
    }

    @Synchronized
    override fun recordPlay(track: Track) = transaction {
        put(track)
        db.execSQL("INSERT INTO history(id) VALUES(?)", arrayOf(track.id))
        db.execSQL(
            "DELETE FROM history WHERE sequence NOT IN(SELECT sequence FROM history ORDER BY sequence DESC LIMIT 2000)"
        )
    }

    @Synchronized
    override fun playlists(): List<PlaylistSummary> =
        db.rawQuery("SELECT id,name,description FROM playlists ORDER BY id DESC", null).use { c ->
            buildList {
                while (c.moveToNext()) {
                    val id = c.getLong(0)
                    val tracks = playlistTracks(id)
                    add(
                        PlaylistSummary(
                            id,
                            c.getString(1),
                            c.getString(2),
                            tracks.firstOrNull()?.thumbnail ?: "",
                            tracks.size,
                        )
                    )
                }
            }
        }

    @Synchronized
    override fun playlistTracks(id: Long) =
        rows(
            "SELECT t.payload FROM items i JOIN tracks t ON t.id=i.id WHERE i.playlist=? ORDER BY i.position",
            id.toString(),
        )

    @Synchronized
    override fun createPlaylist(name: String): Long {
        require(name.trim().length in 1..100)
        return db.insertOrThrow(
            "playlists",
            null,
            ContentValues().apply { put("name", name.trim()) },
        )
    }

    @Synchronized
    override fun addToPlaylist(id: Long, tracks: List<Track>) = transaction {
        require(playlists().any { it.id == id })
        val combined = (playlistTracks(id) + tracks).distinctBy { it.id }
        db.execSQL("DELETE FROM items WHERE playlist=?", arrayOf(id))
        combined.forEachIndexed { i, t ->
            put(t)
            db.execSQL("INSERT INTO items VALUES(?,?,?)", arrayOf<Any>(id, t.id, i))
        }
    }

    @Synchronized
    override fun editPlaylist(id: Long, name: String, description: String) {
        require(name.trim().length in 1..100 && description.length <= 2000)
        db.execSQL(
            "UPDATE playlists SET name=?,description=? WHERE id=?",
            arrayOf<Any>(name.trim(), description, id),
        )
    }

    @Synchronized
    override fun deletePlaylist(id: Long) = transaction {
        db.execSQL("DELETE FROM items WHERE playlist=?", arrayOf(id))
        db.execSQL("DELETE FROM playlists WHERE id=?", arrayOf(id))
    }

    @Synchronized
    override fun removeFromPlaylist(id: Long, trackId: String) = transaction {
        db.execSQL("DELETE FROM items WHERE playlist=? AND id=?", arrayOf<Any>(id, trackId))
    }

    @Synchronized
    override fun reorderPlaylist(id: Long, ids: List<String>) = transaction {
        val known = playlistTracks(id).map { it.id }
        require(ids.size == known.size && ids.toSet() == known.toSet())
        ids.forEachIndexed { i, key ->
            db.execSQL(
                "UPDATE items SET position=? WHERE playlist=? AND id=?",
                arrayOf<Any>(i, id, key),
            )
        }
    }

    @Synchronized
    override fun duplicatePlaylist(id: Long): Long = transaction {
        val old = playlists().first { it.id == id }
        val copy = createPlaylist(old.name.take(90) + " (копия)")
        editPlaylist(copy, old.name.take(90) + " (копия)", old.description)
        addToPlaylist(copy, playlistTracks(id))
        copy
    }

    @Synchronized
    override fun setPreferred(original: Track, replacement: Track?) = transaction {
        replacement?.let(::put)
        setSetting("preferred:" + original.id, replacement?.id ?: "")
    }

    @Synchronized
    override fun preferred(track: Track) = findTrack(setting("preferred:" + track.id, "")) ?: track

    @Synchronized
    override fun setting(name: String, default: String): String =
        db.rawQuery("SELECT value FROM settings WHERE key=?", arrayOf(name)).use {
            if (it.moveToFirst()) it.getString(0) else default
        }

    @Synchronized
    override fun setSetting(name: String, value: String) =
        db.execSQL("INSERT OR REPLACE INTO settings VALUES(?,?)", arrayOf(name, value))

    @Synchronized override fun close() = helper.close()
}
