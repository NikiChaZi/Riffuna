package riffuna.core

fun displayedTracks(state: AppState): List<Track> {
    val source =
        when (state.view) {
            LibraryView.HOME,
            LibraryView.HISTORY -> state.history
            LibraryView.LIKES -> state.likes
            else -> state.visibleTracks
        }
    val filtered =
        source.filter {
            state.localFilter.isBlank() ||
                it.title.contains(state.localFilter, true) ||
                it.artist.contains(state.localFilter, true)
        }
    return when (state.localOrder) {
        LocalOrder.TITLE -> filtered.sortedBy { it.title.lowercase() }
        LocalOrder.ARTIST ->
            filtered.sortedWith(
                compareBy<Track> { it.artist.lowercase() }.thenBy { it.title.lowercase() }
            )
        LocalOrder.SHORTEST -> filtered.sortedBy { it.duration }
        LocalOrder.LONGEST -> filtered.sortedByDescending { it.duration }
        else -> filtered
    }
}

fun isCurrentTrack(state: AppState, track: Track): Boolean =
    state.current?.let { it.id == track.id || state.playbackReference?.id == track.id } ?: false
