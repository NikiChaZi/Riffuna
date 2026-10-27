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

data class PlaybackUiState(
    val loading: Boolean = false,
    val playbackLoading: Boolean = false,
    val playing: Boolean = false,
    val playbackError: String? = null,
    val expanded: Boolean = false,
    val lyricsFocus: Boolean = false,
    val audioDevices: List<AudioDevice> = emptyList(),
    val audioDevice: String = "auto",
    val playbackReference: Track? = null,
    val current: Track? = null,
    val seekable: Boolean = false,
    val positionMs: Long = 0,
    val durationMs: Long = 0,
    val volume: Float = .65f,
)

data class QueueUiState(
    val queueVisible: Boolean = true,
    val shuffle: Boolean = false,
    val repeatMode: RepeatMode = RepeatMode.OFF,
    val queue: List<Track> = emptyList(),
    val queueIndex: Int = -1,
)

data class LibraryUiState(
    val localImporting: Boolean = false,
    val visibleTracks: List<Track> = emptyList(),
    val likes: List<Track> = emptyList(),
    val history: List<Track> = emptyList(),
    val playlists: List<PlaylistSummary> = emptyList(),
)

data class SearchUiState(
    val searchLoading: Boolean = false,
    val query: String = "",
    val searchOrder: SearchOrder = SearchOrder.RELEVANCE,
    val searchLimit: Int = 40,
    val canLoadMore: Boolean = false,
)

data class NavigationUiState(
    val view: LibraryView = LibraryView.HOME,
    val localFilter: String = "",
    val localOrder: LocalOrder = LocalOrder.CUSTOM,
    val selectedIds: Set<String> = emptySet(),
    val canGoBack: Boolean = false,
    val canGoForward: Boolean = false,
    val reducedMotion: Boolean = false,
    val playlistId: Long? = null,
)

data class LyricsUiState(
    val approximateWords: Boolean = true,
    val lyricsPacket: LyricsPacket = LyricsPacket(),
    val lyricsLoading: Boolean = false,
    val lyrics: List<LyricLine> = emptyList(),
)

data class RecommendationUiState(
    val recommendationsLoading: Boolean = false,
    val resolvingSuggestionId: String? = null,
    val suggestions: List<Suggestion> = emptyList(),
)

data class VersionsUiState(
    val versionReference: Track? = null,
    val versions: List<RecordingVersion> = emptyList(),
    val versionsLoading: Boolean = false,
    val versionError: String = "",
)

data class AppState(
    val playback: PlaybackUiState = PlaybackUiState(),
    val queueState: QueueUiState = QueueUiState(),
    val libraryState: LibraryUiState = LibraryUiState(),
    val searchState: SearchUiState = SearchUiState(),
    val navigationState: NavigationUiState = NavigationUiState(),
    val lyricsState: LyricsUiState = LyricsUiState(),
    val recommendationState: RecommendationUiState = RecommendationUiState(),
    val versionsState: VersionsUiState = VersionsUiState(),
    val toast: String = "",
    val status: String = "Готово к музыке",
) {
    val loading: Boolean
        get() = playback.loading

    val playbackLoading: Boolean
        get() = playback.playbackLoading

    val searchLoading: Boolean
        get() = searchState.searchLoading

    val localImporting: Boolean
        get() = libraryState.localImporting

    val recommendationsLoading: Boolean
        get() = recommendationState.recommendationsLoading

    val playing: Boolean
        get() = playback.playing

    val queueVisible: Boolean
        get() = queueState.queueVisible

    val playbackError: String?
        get() = playback.playbackError

    val expanded: Boolean
        get() = playback.expanded

    val lyricsFocus: Boolean
        get() = playback.lyricsFocus

    val shuffle: Boolean
        get() = queueState.shuffle

    val resolvingSuggestionId: String?
        get() = recommendationState.resolvingSuggestionId

    val approximateWords: Boolean
        get() = lyricsState.approximateWords

    val suggestions: List<Suggestion>
        get() = recommendationState.suggestions

    val view: LibraryView
        get() = navigationState.view

    val query: String
        get() = searchState.query

    val localFilter: String
        get() = navigationState.localFilter

    val localOrder: LocalOrder
        get() = navigationState.localOrder

    val selectedIds: Set<String>
        get() = navigationState.selectedIds

    val canGoBack: Boolean
        get() = navigationState.canGoBack

    val canGoForward: Boolean
        get() = navigationState.canGoForward

    val reducedMotion: Boolean
        get() = navigationState.reducedMotion

    val searchOrder: SearchOrder
        get() = searchState.searchOrder

    val searchLimit: Int
        get() = searchState.searchLimit

    val canLoadMore: Boolean
        get() = searchState.canLoadMore

    val lyricsPacket: LyricsPacket
        get() = lyricsState.lyricsPacket

    val lyricsLoading: Boolean
        get() = lyricsState.lyricsLoading

    val versionReference: Track?
        get() = versionsState.versionReference

    val versions: List<RecordingVersion>
        get() = versionsState.versions

    val versionsLoading: Boolean
        get() = versionsState.versionsLoading

    val versionError: String
        get() = versionsState.versionError

    val repeatMode: RepeatMode
        get() = queueState.repeatMode

    val playlistId: Long?
        get() = navigationState.playlistId

    val audioDevices: List<AudioDevice>
        get() = playback.audioDevices

    val audioDevice: String
        get() = playback.audioDevice

    val visibleTracks: List<Track>
        get() = libraryState.visibleTracks

    val likes: List<Track>
        get() = libraryState.likes

    val history: List<Track>
        get() = libraryState.history

    val queue: List<Track>
        get() = queueState.queue

    val playbackReference: Track?
        get() = playback.playbackReference

    val current: Track?
        get() = playback.current

    val queueIndex: Int
        get() = queueState.queueIndex

    val seekable: Boolean
        get() = playback.seekable

    val positionMs: Long
        get() = playback.positionMs

    val durationMs: Long
        get() = playback.durationMs

    val volume: Float
        get() = playback.volume

    val playlists: List<PlaylistSummary>
        get() = libraryState.playlists

    val lyrics: List<LyricLine>
        get() = lyricsState.lyrics
}

/** Screens do not observe the 10 Hz playback position; player and lyrics collect it locally. */
fun AppState.screenSnapshot(): AppState = copy(playback = playback.copy(positionMs = 0))

interface RiffunaController {
    fun importLocalFiles(paths: List<String>)

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

data class LocalImportResult(val imported: Int, val updated: Int = 0, val skipped: Int = 0)

val Track.isLocalFile: Boolean
    get() = id.startsWith("local-")
