package riffuna.core

import kotlinx.coroutines.flow.StateFlow
import kotlinx.serialization.Serializable

@Serializable
data class Track(
    val id: String,
    val title: String,
    val artist: String = "YouTube",
    val duration: Int = 0,
    val thumbnail: String = "",
    val version: String = "",
    val viewCount: Long? = null,
    val published: String = "",
)

@Serializable
data class PlaylistSummary(
    val id: Long,
    val name: String,
    val description: String = "",
    val thumbnail: String = "",
    val trackCount: Int = 0,
)

@Serializable
data class Suggestion(
    val catalogId: String,
    val title: String,
    val artist: String,
    val genres: List<String> = emptyList(),
)

@Serializable data class LyricWord(val startMs: Long, val endMs: Long, val text: String)

@Serializable
data class LyricLine(
    val startMs: Long,
    val endMs: Long? = null,
    val text: String,
    val words: List<LyricWord> = emptyList(),
)

@Serializable
data class LyricsPacket(
    val state: String = "not_found",
    val lines: List<LyricLine> = emptyList(),
    val plainText: String = "",
    val source: String = "",
    val sourceUrl: String = "",
    val timingSource: String = "none",
    val message: String = "",
    val approximateWords: Boolean = true,
)

@Serializable
data class RecordingVersion(val track: Track, val label: String, val evidence: String)

data class AppState(
    val loading: Boolean = false,
    val playbackLoading: Boolean = false,
    val searchLoading: Boolean = false,
    val recommendationsLoading: Boolean = false,
    val playing: Boolean = false,
    val queueVisible: Boolean = true,
    val playbackError: String? = null,
    val expanded: Boolean = false,
    val lyricsFocus: Boolean = false,
    val shuffle: Boolean = false,
    val resolvingSuggestionId: String? = null,
    val approximateWords: Boolean = true,
    val suggestions: List<Suggestion> = emptyList(),
    val view: LibraryView = LibraryView.HOME,
    val query: String = "",
    val localFilter: String = "",
    val localOrder: LocalOrder = LocalOrder.CUSTOM,
    val selectedIds: Set<String> = emptySet(),
    val canGoBack: Boolean = false,
    val canGoForward: Boolean = false,
    val reducedMotion: Boolean = false,
    val searchOrder: SearchOrder = SearchOrder.RELEVANCE,
    val searchLimit: Int = 40,
    val canLoadMore: Boolean = false,
    val lyricsPacket: LyricsPacket = LyricsPacket(),
    val lyricsLoading: Boolean = false,
    val versionReference: Track? = null,
    val versions: List<RecordingVersion> = emptyList(),
    val versionsLoading: Boolean = false,
    val versionError: String = "",
    val toast: String = "",
    val status: String = "Готово к музыке",
    val repeatMode: RepeatMode = RepeatMode.OFF,
    val playlistId: Long? = null,
    val audioDevices: List<AudioDevice> = emptyList(),
    val audioDevice: String = "auto",
    val visibleTracks: List<Track> = emptyList(),
    val likes: List<Track> = emptyList(),
    val history: List<Track> = emptyList(),
    val queue: List<Track> = emptyList(),
    val playbackReference: Track? = null,
    val current: Track? = null,
    val queueIndex: Int = -1,
    val seekable: Boolean = false,
    val positionMs: Long = 0,
    val durationMs: Long = 0,
    val volume: Float = .65f,
    val playlists: List<PlaylistSummary> = emptyList(),
    val lyrics: List<LyricLine> = emptyList(),
)

interface RiffunaController {
    val state: StateFlow<AppState>

    fun refreshRecommendations()

    fun playSuggestion(suggestion: Suggestion)

    fun navigateBack()

    fun navigateForward()

    fun setLocalFilter(value: String)

    fun setLocalOrder(value: LocalOrder)

    fun setSearchOrder(value: SearchOrder)

    fun loadMore()

    fun selectTrack(id: String, control: Boolean = false, shift: Boolean = false)

    fun selectAll()

    fun clearSelection()

    fun enqueueMany(tracks: List<Track>)

    fun removeSelected()

    fun reorderQueue(ids: List<String>)

    fun reorderPlaylist(ids: List<String>)

    fun createPlaylistFrom(name: String, tracks: List<Track>): Long

    fun duplicatePlaylist(id: Long)

    fun findVersions(track: Track)

    fun closeVersions()

    fun chooseVersion(original: Track, replacement: Track)

    fun resetVersion(original: Track)

    fun reloadLyrics()

    fun importLyrics(text: String, format: String)

    fun setReducedMotion(value: Boolean)

    fun search(query: String)

    fun showView(view: LibraryView)

    fun openPlaylist(id: Long)

    fun play(track: Track)

    fun enqueue(track: Track)

    fun playNext(track: Track)

    fun playQueueTrack(id: String)

    fun playQueue()

    fun playAll()

    fun removeFromQueue(id: String)

    fun moveInQueue(id: String, offset: Int)

    fun refreshAudioDevices()

    fun selectAudioDevice(id: String)

    fun addToPlaylist(id: Long, tracks: List<Track>)

    fun editPlaylist(id: Long, name: String, description: String)

    fun deletePlaylist(id: Long)

    fun removeFromPlaylist(id: Long, trackId: String)

    fun next()

    fun previous()

    fun toggle()

    fun seek(positionMs: Long)

    fun setVolume(volume: Float)

    fun toggleLike(track: Track)

    fun clearQueue()

    fun createPlaylist(name: String)

    fun toggleShuffle()

    fun cycleRepeat()

    fun openNowPlaying(open: Boolean)

    fun setLyricsFocus(focus: Boolean)

    fun toggleQueue()
}
