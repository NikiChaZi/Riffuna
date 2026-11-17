package riffuna.core

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

@Serializable
data class PortablePlaylist(val name: String, val description: String, val tracks: List<Track>)

@Serializable
data class CollectionSnapshot(
    val version: Int,
    val likes: List<Track>,
    val playlists: List<PortablePlaylist>,
    val recordingChoices: Map<String, Track>,
)

data class CollectionImport(val likes: Int, val playlists: Int, val recordingChoices: Int)

object CollectionTransfer {
    const val maxBytes = 16 * 1024 * 1024
    private val videoId = Regex("[A-Za-z0-9_-]{11}")
    private val artworkHost =
        Regex(
            """https://(?:[a-z0-9-]+\.)*(?:ytimg\.com|ggpht\.com|googleusercontent\.com)/[^\s]+""",
            RegexOption.IGNORE_CASE,
        )
    private val json = Json { ignoreUnknownKeys = true }

    fun encode(library: MusicLibrary): String {
        val playlists =
            library.playlists().map { playlist ->
                PortablePlaylist(
                    playlist.name,
                    playlist.description,
                    library.playlistTracks(playlist.id).filter { videoId.matches(it.id) },
                )
            }
        return json
            .encodeToString(
                CollectionSnapshot(
                    version = 1,
                    likes = library.likes().filter { videoId.matches(it.id) },
                    playlists = playlists,
                    recordingChoices =
                        library.recordingChoices().filterValues { videoId.matches(it.id) },
                )
            )
            .also { require(it.encodeToByteArray().size <= maxBytes) }
    }

    fun decode(text: String): CollectionSnapshot {
        require(text.length <= maxBytes && text.encodeToByteArray().size <= maxBytes)
        val snapshot = json.decodeFromString<CollectionSnapshot>(text)
        require(snapshot.version == 1)
        require(snapshot.playlists.size <= 2_000 && snapshot.likes.size <= 50_000)
        require(snapshot.recordingChoices.size <= 50_000)
        require(snapshot.playlists.sumOf { it.tracks.size.toLong() } <= 100_000)
        return snapshot.copy(
            likes = snapshot.likes.map(::validateTrack),
            playlists =
                snapshot.playlists.map { playlist ->
                    require(playlist.name.isNotBlank() && playlist.name.length <= 100)
                    require(playlist.description.length <= 2_000)
                    playlist.copy(tracks = playlist.tracks.map(::validateTrack))
                },
            recordingChoices =
                snapshot.recordingChoices
                    .map { (key, track) ->
                        require(key.length <= 1_024 && key.none { it.isISOControl() })
                        require(
                            (key.startsWith("recording:") && "::" in key) ||
                                (key.startsWith("preferred:") &&
                                    videoId.matches(key.substringAfter(':')))
                        )
                        key to validateTrack(track)
                    }
                    .toMap(),
        )
    }

    private fun validateTrack(track: Track): Track {
        require(videoId.matches(track.id))
        require(
            track.title.isNotBlank() && track.title.length <= 1_000 && track.artist.length <= 1_000
        )
        require(track.duration in 0..86_400)
        require(track.version.length <= 200 && track.published.length <= 200)
        return track.copy(
            thumbnail =
                track.thumbnail.takeIf { it.length <= 4_096 && artworkHost.matches(it) }.orEmpty()
        )
    }
}

fun mergeCollection(library: MusicLibrary, snapshot: CollectionSnapshot): CollectionImport {
    val likedIds = library.likes().mapTo(mutableSetOf()) { it.id }
    val newLikes = snapshot.likes.filter { likedIds.add(it.id) }
    newLikes.asReversed().forEach { library.like(it, true) }

    data class PlaylistIdentity(
        val name: String,
        val description: String,
        val tracks: List<String>,
    )
    val known =
        library.playlists().mapTo(mutableSetOf()) {
            PlaylistIdentity(it.name, it.description, library.playlistTracks(it.id).map(Track::id))
        }
    var added = 0
    for (playlist in snapshot.playlists.asReversed()) {
        val tracks = playlist.tracks.distinctBy { it.id }
        if (
            !known.add(PlaylistIdentity(playlist.name, playlist.description, tracks.map(Track::id)))
        )
            continue
        val id = library.createPlaylist(playlist.name)
        library.editPlaylist(id, playlist.name, playlist.description)
        if (tracks.isNotEmpty()) library.addToPlaylist(id, tracks)
        added++
    }

    var preferences = 0
    for ((key, track) in snapshot.recordingChoices) {
        if (library.setting(key, "\u0000") == "\u0000") {
            library.putRecordingChoice(key, track)
            preferences++
        }
    }
    return CollectionImport(newLikes.size, added, preferences)
}
