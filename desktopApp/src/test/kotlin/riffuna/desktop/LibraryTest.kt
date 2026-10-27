package riffuna.desktop

import kotlin.test.*
import java.nio.file.Files
import java.sql.DriverManager
import riffuna.core.Track

class LibraryTest {
    private fun track(id:Char)=Track(id.toString().repeat(11),"Song $id","Artist",180)
    @Test fun legacyMigrationAndPersistencePreserveMusic() {
        val path=Files.createTempDirectory("riffuna-sql-test").resolve("library.sqlite3")
        val db=DriverManager.getConnection("jdbc:sqlite:$path")
        db.createStatement().use{it.execute("CREATE TABLE user_playlists(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL)");it.execute("PRAGMA user_version=2")};db.close()
        val a=track('a');val b=track('b')
        SqliteLibrary(path).useLibrary { lib ->
            lib.like(a,true);lib.recordPlay(a);lib.saveQueue(listOf(a,b),1,b)
            val key=lib.createPlaylist("Мои записи")
            lib.addToPlaylist(key,listOf(a,b,a))
            assertEquals(listOf(a,b),lib.playlistTracks(key))
            assertEquals(listOf(a),lib.likes())
            lib.like(a,false)
            assertEquals(listOf(a),lib.history())
            assertEquals(listOf(a,b) to 1,lib.queue())
        }
        SqliteLibrary(path).useLibrary { lib ->
            assertEquals(b,lib.current());assertEquals(listOf(a,b) to 1,lib.queue())
            assertEquals(2,lib.playlists().single().trackCount)
            assertEquals(emptyList(),lib.likes())
        }
    }
    @Test fun savedPreferredRecordingUsesCanonicalQueueIdentity() {
        val path=Files.createTempDirectory("riffuna-pref-test").resolve("library.sqlite3")
        val a=Track("aaaaaaaaaaa","Song","Artist",180);val b=Track("bbbbbbbbbbb","Song (Uncensored)","Artist",180)
        SqliteLibrary(path).useLibrary { lib ->
            lib.saveQueue(listOf(a,b),0,a)
            lib.setSetting("recording:artist::song",b.id)
            assertEquals(b,lib.preferred(a));assertEquals(a,lib.queue().first.first())
        }
    }
    @Test fun playlistEditingPreservesLikesAndHistoryAndCompactsOrder() {
        val path=Files.createTempDirectory("riffuna-playlist-test").resolve("library.sqlite3")
        val a=track('a');val b=track('b');val c=track('c')
        SqliteLibrary(path).useLibrary {lib->
            lib.like(a,true);lib.recordPlay(b)
            val id=lib.createPlaylist("Original");lib.addToPlaylist(id,listOf(a,b,c))
            lib.editPlaylist(id,"Избранное","Описание")
            assertEquals("Описание",lib.playlists().single().description)
            lib.removeFromPlaylist(id,b.id);assertEquals(listOf(a,c),lib.playlistTracks(id))
            lib.addToPlaylist(id,listOf(b));assertEquals(listOf(a,c,b),lib.playlistTracks(id))
            lib.deletePlaylist(id);assertTrue(lib.playlists().isEmpty())
            assertEquals(listOf(a),lib.likes());assertEquals(listOf(b),lib.history())
        }
    }
    private fun SqliteLibrary.useLibrary(block:(SqliteLibrary)->Unit) {try{block(this)}finally{close()}}
}
