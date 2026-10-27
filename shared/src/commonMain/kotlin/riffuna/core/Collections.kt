package riffuna.core

fun displayedTracks(state:AppState):List<Track> {
    val source=when(state.view){"home","history"->state.history;"likes"->state.likes;else->state.visibleTracks}
    val filtered=source.filter{state.localFilter.isBlank()||it.title.contains(state.localFilter,true)||it.artist.contains(state.localFilter,true)}
    return when(state.localOrder){
        "title"->filtered.sortedBy{it.title.lowercase()};"artist"->filtered.sortedWith(compareBy<Track>{it.artist.lowercase()}.thenBy{it.title.lowercase()})
        "short"->filtered.sortedBy{it.duration};"long"->filtered.sortedByDescending{it.duration};else->filtered
    }
}

fun isCurrentTrack(state:AppState,track:Track)=state.current!=null&&(state.current.id==track.id||state.playbackReference?.id==track.id)
