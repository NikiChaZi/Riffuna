package riffuna.core

import kotlinx.coroutines.flow.StateFlow

data class AudioState(
    val positionMs: Long = 0,
    val durationMs: Long = 0,
    val playing: Boolean = false,
    val ended: Boolean = false,
    val error: String? = null,
    val buffering: Boolean = false,
    val seekable: Boolean = false,
    val outputRevision: Long = 0,
)

data class AudioSource(
    val uri: String,
    val headers: Map<String, String> = emptyMap(),
    val proxy: String = "",
    val autoPlay: Boolean = true,
)

data class AudioDevice(val id: String, val name: String)

interface AudioEngine {
    val state: StateFlow<AudioState>

    suspend fun open(source: AudioSource)

    fun toggle()

    fun pause()

    fun resume()

    fun seek(positionMs: Long)

    fun setVolume(volume: Float)

    fun devices(): List<AudioDevice> = emptyList()

    fun selectDevice(id: String) {}

    fun close()
}

interface MusicSource {
    suspend fun search(query: String, limit: Int = 40): List<Track>

    suspend fun searchSorted(query: String, limit: Int, order: SearchOrder): List<Track> =
        search(query, limit)

    suspend fun alternatives(track: Track): List<RecordingVersion> = emptyList()

    suspend fun lyricsPacket(track: Track, force: Boolean = false): LyricsPacket =
        LyricsPacket(lines = lyrics(track))

    suspend fun enrichLyrics(track: Track, base: LyricsPacket): LyricsPacket = base

    suspend fun importLyrics(track: Track, text: String, format: String): LyricsPacket =
        error("Lyrics import unavailable")

    suspend fun prefetch(track: Track) {}

    fun invalidate(track: Track) {}

    suspend fun resolve(track: Track): AudioSource

    suspend fun lyrics(track: Track): List<LyricLine> = emptyList()

    suspend fun recommend(seeds: List<Track>, excluded: List<Track>): List<Suggestion> = emptyList()

    suspend fun resolveSuggestion(suggestion: Suggestion): Track =
        error("Suggestion source unavailable")

    fun close() {}
}

interface MusicLibrary {
    fun likes(): List<Track>

    fun history(): List<Track>

    fun queue(): Pair<List<Track>, Int>

    fun current(): Track?

    fun saveQueue(tracks: List<Track>, index: Int, current: Track?)

    fun like(track: Track, value: Boolean)

    fun recordPlay(track: Track)

    fun playlists(): List<PlaylistSummary>

    fun playlistTracks(id: Long): List<Track>

    fun createPlaylist(name: String): Long

    fun addToPlaylist(id: Long, tracks: List<Track>)

    fun editPlaylist(id: Long, name: String, description: String)

    fun deletePlaylist(id: Long)

    fun removeFromPlaylist(id: Long, trackId: String)

    fun setting(name: String, default: String): String

    fun setSetting(name: String, value: String)

    fun reorderPlaylist(id: Long, ids: List<String>)

    fun duplicatePlaylist(id: Long): Long

    fun setPreferred(original: Track, replacement: Track?)

    fun preferred(track: Track): Track

    fun close()
}
