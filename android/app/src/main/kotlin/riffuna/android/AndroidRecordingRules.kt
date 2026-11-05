package riffuna.android

import riffuna.catalog.*
import riffuna.core.Track

/** Both platforms use the same recording identity and musical version rules. */
internal object AndroidRecordingRules {
    fun profile(title: String): List<String> = MusicRules.profile(title)

    fun songTitle(title: String, artist: String): String = MusicRules.songTitle(title, artist)

    fun acceptable(track: Track): Boolean =
        track.duration in 1..1200 && !CatalogPresentation.excludes(track.title, "")

    fun matches(reference: Track, candidate: Track): Boolean =
        MusicRules.versionMatches(reference, candidate)
}
