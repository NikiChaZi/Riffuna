package riffuna.core

import kotlin.test.*
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.*

@OptIn(ExperimentalCoroutinesApi::class)
class SessionStateTest {
    private fun track(id:Char,title:String="Song $id",artist:String="Artist")=Track(id.toString().repeat(11),title,artist,180)
    private fun TestScope.session(library:SessionLibrary=SessionLibrary(),source:SessionSource=SessionSource(),audio:SessionAudio=SessionAudio()):LocalController {
        val dispatcher=StandardTestDispatcher(testScheduler);Dispatchers.setMain(dispatcher)
        return LocalController(library,source,audio,dispatcher)
    }
    @Test fun selectionFilteringAndNavigationPreserveSavedOrder()=runTest {
        val library=SessionLibrary();val a=track('a',"Alpha","Дора");val b=track('b',"Beta","Дора");val c=track('c',"Gamma","Other")
        library.liked.addAll(listOf(a,b,c));val controller=session(library)
        try {
            controller.showView("likes");controller.selectTrack(a.id);controller.selectTrack(c.id,shift=true)
            assertEquals(setOf(a.id,b.id,c.id),controller.state.value.selectedIds)
            controller.selectTrack(b.id,control=true);assertEquals(setOf(a.id,c.id),controller.state.value.selectedIds)
            controller.setLocalFilter("Дора");controller.setLocalOrder("title");assertEquals(listOf(a,b),displayedTracks(controller.state.value))
            controller.showView("history");controller.setLocalFilter("Other");controller.navigateBack()
            assertEquals("likes",controller.state.value.view);assertEquals("Дора",controller.state.value.localFilter)
            assertEquals(listOf(a,b,c),library.liked);controller.navigateForward();assertEquals("Other",controller.state.value.localFilter)
        }finally{controller.close();Dispatchers.resetMain()}
    }
    @Test fun onlyActualPlaybackWritesHistoryAndPreferredKeepsQueueAnchor()=runTest {
        val library=SessionLibrary();val audio=SessionAudio();val controller=session(library,audio=audio)
        try {
            val a=track('a');val b=track('b');val alternate=track('x')
            controller.enqueueMany(listOf(a,b));controller.play(a);runCurrent()
            assertTrue(library.plays.isEmpty());audio.state.value=AudioState(500,180000,true);runCurrent();assertEquals(listOf(a),library.plays)
            audio.state.value=AudioState(1000,180000,true);runCurrent();assertEquals(1,library.plays.size)
            controller.chooseVersion(a,alternate);runCurrent()
            assertEquals(alternate,controller.state.value.current);assertEquals(0,controller.state.value.queueIndex);assertEquals(listOf(a,b),controller.state.value.queue)
            controller.next();assertEquals(b,controller.state.value.current)
        }finally{controller.close();Dispatchers.resetMain()}
    }
    @Test fun staleSearchAndLateLyricsCannotReplaceCurrentContent()=runTest {
        val source=SessionSource();val controller=session(source=source)
        try {
            source.slowQuery="old";controller.search("old");runCurrent();controller.search("new");advanceUntilIdle()
            assertEquals("new",controller.state.value.visibleTracks.single().title)
            val a=track('a');val b=track('b');source.slowLyrics=a.id
            controller.play(a);runCurrent();controller.play(b);advanceUntilIdle()
            assertEquals(b.id,controller.state.value.lyricsPacket.plainText)
        }finally{controller.close();Dispatchers.resetMain()}
    }
    @Test fun playNextAndRemovedCurrentContinuationSurviveRestart()=runTest {
        val library=SessionLibrary();val first=session(library);val a=track('a');val b=track('b');val c=track('c');val d=track('d')
        first.enqueueMany(listOf(a,b,c,d));first.play(b);first.playNext(d);first.removeFromQueue(b.id);first.close()
        val second=session(library)
        try {second.next();assertEquals(d,second.state.value.current);assertEquals(listOf(a,d,c),second.state.value.queue)}
        finally{second.close();Dispatchers.resetMain()}
    }
    @Test fun filteredPlaylistReorderIsRejectedAndDuplicateQueueIdsAreRejected()=runTest {
        val library=SessionLibrary();val a=track('a');val b=track('b');val c=track('c');val controller=session(library)
        try {
            controller.createPlaylistFrom("Test",listOf(a,b,c));controller.openPlaylist(1);controller.setLocalFilter("a")
            controller.reorderPlaylist(listOf(c.id,b.id,a.id));assertEquals(listOf(a,b,c),library.list)
            controller.setLocalFilter("");controller.reorderPlaylist(listOf(c.id,b.id,a.id));assertEquals(listOf(c,b,a),library.list)
            controller.enqueueMany(listOf(a,b,a));assertFailsWith<IllegalArgumentException>{controller.reorderQueue(listOf(a.id,a.id))}
        }finally{controller.close();Dispatchers.resetMain()}
    }
    @Test fun repeatingOneTrackCanRepeatMoreThanOnceAndPauseDuringResolveIsKept()=runTest {
        val audio=SessionAudio();val source=SessionSource();source.resolveDelay=100
        val controller=session(source=source,audio=audio)
        try {
            controller.play(track('a'));controller.toggle();advanceTimeBy(150);runCurrent();assertFalse(audio.opened.last().autoPlay)
            controller.cycleRepeat();audio.state.value=AudioState(180000,180000,false,ended=true);runCurrent();assertEquals(1,audio.resumed)
            audio.state.value=AudioState(1000,180000,true);runCurrent();audio.state.value=AudioState(180000,180000,false,ended=true);runCurrent();assertEquals(2,audio.resumed)
        }finally{controller.close();Dispatchers.resetMain()}
    }
    @Test fun legacyOutputSelectionAndDeviceRemovalPreserveUsableOutput()=runTest {
        val library=SessionLibrary();val audio=SessionAudio();val guid="{12345678-1234-1234-1234-123456789abc}"
        library.settings["audio_output"]=guid.encodeToByteArray().joinToString(""){it.toUByte().toString(16).padStart(2,'0')}
        audio.outputs=listOf(AudioDevice("auto","System"),AudioDevice("wasapi/$guid","Headphones"))
        val controller=session(library,audio=audio)
        try {
            assertEquals("wasapi/$guid",controller.state.value.audioDevice)
            audio.outputs=listOf(AudioDevice("auto","System"));audio.state.value=AudioState(outputRevision=1);runCurrent()
            assertEquals("auto",controller.state.value.audioDevice);assertEquals("auto",audio.selected)
        }finally{controller.close();Dispatchers.resetMain()}
    }

    @Test fun previouslyChosenRecordingRemainsAvailableWhenSearchReturnsNoAlternatives()=runTest {
        val library=SessionLibrary();val original=track('a');val replacement=track('b');library.replacements[original.id]=replacement
        val controller=session(library)
        try{controller.findVersions(original);advanceUntilIdle();assertEquals(replacement,controller.state.value.versions.single().track);assertFalse(controller.state.value.versionsLoading)}
        finally{controller.close();Dispatchers.resetMain()}
    }

    @Test fun shuffleDoesNotRepeatCanonicalEntryWhenAnotherRecordingIsPlaying()=runTest {
        val library=SessionLibrary();val original=track('a');val alternate=track('x');val b=track('b');val c=track('c');library.replacements[original.id]=alternate
        val controller=session(library)
        try{controller.enqueueMany(listOf(original,b,c));controller.play(original);controller.toggleShuffle();val played=mutableSetOf<String>();repeat(2){controller.next();played.add(controller.state.value.current!!.id)};assertEquals(setOf(b.id,c.id),played)}
        finally{controller.close();Dispatchers.resetMain()}
    }

    @Test fun lateRecommendationCannotInterruptExplicitPlaybackAndPrefetchStopsAtRemovedEnd()=runTest {
        val source=SessionSource();val controller=session(source=source)
        try {
            controller.playSuggestion(Suggestion("a","Suggested","Artist"));runCurrent()
            val a=track('a');val b=track('b');controller.play(b);advanceUntilIdle();assertEquals(b,controller.state.value.current)
            controller.enqueueMany(listOf(a,b));controller.playQueueTrack(b.id);advanceUntilIdle();controller.removeFromQueue(b.id);advanceUntilIdle()
            val before=source.prepared.size;controller.enqueueMany(emptyList());advanceUntilIdle();assertEquals(before,source.prepared.size)
            controller.next();assertEquals(b,controller.state.value.current)
        }finally{controller.close();Dispatchers.resetMain()}
    }

    @Test fun playbackCanBeRetriedAfterAudioFailureAndRestartedAfterTheEnd()=runTest {
        val audio=SessionAudio();val source=SessionSource();val controller=session(source=source,audio=audio)
        try {
            val song=track('a');controller.play(song);runCurrent();audio.state.value=AudioState(error="Audio failed");runCurrent()
            assertEquals("Audio failed",controller.state.value.playbackError);assertEquals(listOf(song.id),source.invalidated)
            controller.toggle();runCurrent();assertEquals(2,audio.opened.size);assertNull(controller.state.value.playbackError)
            audio.state.value=AudioState(180000,180000,false,ended=true);runCurrent();controller.toggle()
            assertEquals(0L,audio.seeks.last());assertEquals(1,audio.resumed)
        }finally{controller.close();Dispatchers.resetMain()}
    }

    @Test fun deletedPlaylistDoesNotReappearThroughBackNavigation()=runTest {
        val controller=session()
        try{controller.createPlaylist("Temporary");controller.showView("playlists");controller.openPlaylist(1);controller.deletePlaylist(1);assertEquals("playlists",controller.state.value.view);controller.navigateBack();assertNull(controller.state.value.playlistId);controller.navigateForward();assertEquals("playlists",controller.state.value.view)}
        finally{controller.close();Dispatchers.resetMain()}
    }

    @Test fun chosenRecordingOutsideQueueKeepsItsOriginalAndCanBeResetAfterRestart()=runTest {
        val library=SessionLibrary();val original=track('a');val alternate=track('b',"Song a (Slowed)")
        val first=session(library);first.play(original);runCurrent();first.chooseVersion(original,alternate);runCurrent()
        assertEquals(original,first.state.value.playbackReference);assertTrue(isCurrentTrack(first.state.value,original));assertTrue(first.state.value.queue.isEmpty());first.close()
        val restored=session(library)
        try{assertEquals(original,restored.state.value.playbackReference);restored.findVersions(alternate);advanceUntilIdle();assertEquals(original,restored.state.value.versionReference);assertEquals(alternate,restored.state.value.versions.single().track);restored.resetVersion(alternate);runCurrent();assertEquals(original,restored.state.value.current);assertTrue(library.replacements.isEmpty())}
        finally{restored.close();Dispatchers.resetMain()}
    }

}
private class SessionAudio:AudioEngine {
    var outputs=emptyList<AudioDevice>();var selected="auto"
    override fun devices()=outputs;override fun selectDevice(id:String){selected=id}
    override val state=MutableStateFlow(AudioState());val opened=mutableListOf<AudioSource>();val seeks=mutableListOf<Long>();var resumed=0
    override suspend fun open(source:AudioSource){opened.add(source);state.value=AudioState()}
    override fun toggle(){};override fun pause(){};override fun resume(){resumed++};override fun seek(positionMs:Long){seeks.add(positionMs)}
    override fun setVolume(volume:Float){};override fun close(){}
}
private class SessionSource:MusicSource {
    var slowQuery="";var slowLyrics="";var resolveDelay=0L;val prepared=mutableListOf<String>();val invalidated=mutableListOf<String>()
    override fun invalidate(track:Track){invalidated.add(track.id)}
    override suspend fun prefetch(track:Track){prepared.add(track.id)}
    override suspend fun resolveSuggestion(suggestion:Suggestion):Track{withContext(NonCancellable){delay(100)};return Track("rrrrrrrrrrr",suggestion.title,suggestion.artist,180)}
    override suspend fun search(query:String,limit:Int):List<Track>{if(query==slowQuery)delay(100);return listOf(Track("sssssssssss",query,"Artist",180))}
    override suspend fun resolve(track:Track):AudioSource{delay(resolveDelay);return AudioSource("file:///test.m4a")}
    override suspend fun lyricsPacket(track:Track,force:Boolean):LyricsPacket{if(track.id==slowLyrics)delay(100);return LyricsPacket("plain",plainText=track.id)}
}
private class SessionLibrary:MusicLibrary {
    val liked=mutableListOf<Track>();val plays=mutableListOf<Track>();val settings=mutableMapOf<String,String>();val replacements=mutableMapOf<String,Track>()
    var queued=emptyList<Track>() to -1;var selected:Track?=null;var list=emptyList<Track>();var playlist:PlaylistSummary?=null
    override fun likes()=liked.toList();override fun history()=plays.reversed().distinctBy{it.id};override fun queue()=queued;override fun current()=selected
    override fun saveQueue(tracks:List<Track>,index:Int,current:Track?){queued=tracks.toList() to index;selected=current}
    override fun like(track:Track,value:Boolean){liked.removeAll{it.id==track.id};if(value)liked.add(track)}
    override fun recordPlay(track:Track){plays.add(track)}
    override fun playlists()=listOfNotNull(playlist);override fun playlistTracks(id:Long)=list
    override fun createPlaylist(name:String):Long{playlist=PlaylistSummary(1,name);return 1}
    override fun addToPlaylist(id:Long,tracks:List<Track>){list=(list+tracks).distinctBy{it.id}}
    override fun editPlaylist(id:Long,name:String,description:String){playlist=playlist?.copy(name=name,description=description)}
    override fun deletePlaylist(id:Long){playlist=null;list=emptyList()}
    override fun removeFromPlaylist(id:Long,trackId:String){list=list.filter{it.id!=trackId}}
    override fun reorderPlaylist(id:Long,ids:List<String>){val map=list.associateBy{it.id};list=ids.map{map.getValue(it)}}
    override fun duplicatePlaylist(id:Long)=2L
    override fun setting(name:String,default:String)=settings[name]?:default;override fun setSetting(name:String,value:String){settings[name]=value}
    override fun preferred(track:Track)=replacements[track.id]?:track
    override fun setPreferred(original:Track,replacement:Track?){if(replacement==null)replacements.remove(original.id)else replacements[original.id]=replacement}
    override fun close(){}
}
