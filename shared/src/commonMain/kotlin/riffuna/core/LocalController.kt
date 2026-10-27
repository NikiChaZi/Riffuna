package riffuna.core

import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import kotlinx.serialization.json.*

class LocalController(private val library:MusicLibrary,private val source:MusicSource,private val audio:AudioEngine,private val ioDispatcher:CoroutineDispatcher=Dispatchers.IO):RiffunaController {
    private val scope=CoroutineScope(SupervisorJob()+Dispatchers.Main)
    private val initialQueue=library.queue()
    private val initialCurrent=library.current()
    private val initialLikes=library.likes()
    private val initialHistory=library.history()
    private val initialReference=runCatching{Json.decodeFromJsonElement<Track>(Json.parseToJsonElement(library.setting("playback_reference","")))}.getOrNull()?.takeIf{library.preferred(it).id==initialCurrent?.id}
        ?:initialQueue.first.getOrNull(initialQueue.second)?.takeIf{library.preferred(it).id==initialCurrent?.id}
        ?:(initialQueue.first+initialLikes+initialHistory).distinctBy{it.id}.take(256).firstOrNull{it.id!=initialCurrent?.id&&library.preferred(it).id==initialCurrent?.id}
        ?:initialCurrent
    private val mutable=MutableStateFlow(AppState(likes=initialLikes,history=initialHistory,playbackReference=initialReference,queue=initialQueue.first,
        queueIndex=initialQueue.second,current=initialCurrent,durationMs=initialCurrent?.duration?.times(1000L)?:0,playlists=library.playlists(),
        volume=(library.setting("volume","0.65").toFloatOrNull()?:.65f).coerceIn(0f,1f),
        repeatMode=library.setting("repeat_mode","off"),reducedMotion=library.setting("reduced_motion","off")=="on",shuffle=library.setting("shuffle","off")=="on"))
    override val state:StateFlow<AppState> = mutable
    private data class Navigation(val view:String,val playlistId:Long?=null)
    private val navigation=mutableListOf(Navigation("home"))
    private var navigationIndex=0
    private val preferences=mutableMapOf<String,Pair<String,String>>()
    private var selectionAnchor:String?=null
    private var versionJob:Job?=null
    private var versionGeneration=0L
    private var toastJob:Job?=null
    private var volumeJob:Job?=null
    private var prefetchJob:Job?=null
    private var prefetchedId:String?=null
    private var plannedShuffle:String?=null
    private var observedOutputRevision=0L
    private var wantPlay=true
    private var pendingSeek:Long?=null
    private var searchResults=emptyList<Track>()
    private var searchJob:Job?=null
    private var playJob:Job?=null
    private var lyricsJob:Job?=null
    private var recommendationJob:Job?=null
    private var suggestionJob:Job?=null
    private var suggestionGeneration=0L
    private var searchGeneration=0L
    private var playGeneration=0L
    private var logged=false
    private var sourceAttached=false
    private var endHandled=false
    private val visited=mutableSetOf<String>()
    private val priority=mutableListOf<String>()
    private val traversal=mutableListOf<String>()
    private var traversalIndex=-1
    private var continuation:List<String>?=null
    private var preserveTraversal=false
    init {
        initialQueue.first.getOrNull(initialQueue.second)?.let{visited.add(it.id);traversal.add(it.id);traversalIndex=0}
        val devices=audio.devices()
        val old=library.setting("audio_output","")
        val decoded=runCatching{old.chunked(2).map{it.toInt(16).toByte()}.toByteArray().decodeToString().replace("\u0000","")}.getOrDefault("")
        val legacyGuid=Regex("\\{[0-9a-fA-F-]{36}\\}").find(decoded)?.value
        val legacy=legacyGuid?.let{guid->devices.firstOrNull{it.id.contains(guid,true)}?.id}?:"auto"
        val selected=library.setting("mpv_audio_device",legacy).takeIf{key->devices.any{it.id==key}}?:"auto"
        if(devices.isNotEmpty())runCatching{audio.selectDevice(selected)}
        mutable.update{it.copy(audioDevices=devices,audioDevice=selected)}
        val ids=initialQueue.first.map{it.id}.toSet()
        runCatching{Json.parseToJsonElement(library.setting("queue_next_ids","[]")).jsonArray.forEach{v->v.jsonPrimitive.content.takeIf{it in ids}?.let(priority::add)}}
        if(initialQueue.second==-1)runCatching{continuation=Json.parseToJsonElement(library.setting("queue_continuation","null")).jsonArray.map{it.jsonPrimitive.content}.filter{it in ids}}
        audio.setVolume(state.value.volume)
        scope.launch { audio.state.collect { value ->
            if(value.outputRevision!=observedOutputRevision){observedOutputRevision=value.outputRevision;refreshAudioDevices()}
            if(!sourceAttached)return@collect
            mutable.update{it.copy(positionMs=value.positionMs,durationMs=if(value.durationMs>0)value.durationMs else it.current?.duration?.times(1000L)?:0,playing=value.playing,seekable=value.seekable,playbackLoading=value.buffering&&wantPlay)}
            if(value.seekable)pendingSeek?.let{target->pendingSeek=null;audio.seek(target)}
            if(value.playing&&state.value.status=="Подключаем запись…")mutable.update{it.copy(status="Сейчас играет")}
            if(value.playing&&!logged) {
                state.value.current?.let{library.recordPlay(it)};logged=true
                mutable.update{it.copy(history=library.history())}
            }
            if(!value.ended&&value.playing)endHandled=false
            if(value.ended&&!endHandled) { endHandled=true;if(state.value.repeatMode=="one"){audio.seek(0);audio.resume()}else next() }
            if(value.error!=null){state.value.current?.let(source::invalidate);sourceAttached=false;wantPlay=false;mutable.update{it.copy(status=value.error,playbackError=value.error,playing=false,seekable=false,loading=false,playbackLoading=false)};toast(value.error)}
        } }
    }
    private fun toast(text:String) {toastJob?.cancel();mutable.update{it.copy(toast=text)};toastJob=scope.launch{delay(2800);mutable.update{it.copy(toast="")}}}
    private fun contextKey()=state.value.view+":"+state.value.playlistId
    private fun applyNavigation(target:Navigation,push:Boolean) {
        preferences[contextKey()]=state.value.localFilter to state.value.localOrder
        if(push&&navigation.getOrNull(navigationIndex)!=target){while(navigation.lastIndex>navigationIndex)navigation.removeAt(navigation.lastIndex);navigation.add(target);navigationIndex=navigation.lastIndex}
        val prefs=preferences[target.view+":"+target.playlistId]?:Pair("","custom")
        mutable.update{it.copy(view=target.view,playlistId=target.playlistId,visibleTracks=when(target.view){"likes"->it.likes;"history"->it.history;"search"->searchResults;"playlist"->target.playlistId?.let(library::playlistTracks).orEmpty();else->emptyList()},localFilter=prefs.first,localOrder=prefs.second,selectedIds=emptySet(),canGoBack=navigationIndex>0,canGoForward=navigationIndex<navigation.lastIndex)}
        selectionAnchor=null
        if(target.view=="resonance"&&state.value.suggestions.isEmpty())recommendations()
    }
    override fun navigateBack() {if(navigationIndex>0){navigationIndex--;applyNavigation(navigation[navigationIndex],false)}}
    override fun navigateForward() {if(navigationIndex<navigation.lastIndex){navigationIndex++;applyNavigation(navigation[navigationIndex],false)}}
    override fun setLocalFilter(value:String) {mutable.update{it.copy(localFilter=value,selectedIds=emptySet())};selectionAnchor=null}
    override fun setLocalOrder(value:String) {require(value in setOf("custom","title","artist","short","long"));mutable.update{it.copy(localOrder=value,selectedIds=emptySet())};selectionAnchor=null}
    override fun selectTrack(id:String,control:Boolean,shift:Boolean) {
        val ids=displayedTracks(state.value).map{it.id};if(id !in ids)return
        val anchor=ids.indexOf(selectionAnchor);val at=ids.indexOf(id)
        val chosen=if(shift&&anchor>=0)ids.subList(minOf(anchor,at),maxOf(anchor,at)+1).toSet() else setOf(id)
        mutable.update{it.copy(selectedIds=when{shift&&control->it.selectedIds+chosen;shift->chosen;control->if(id in it.selectedIds)it.selectedIds-id else it.selectedIds+id;else->chosen})}
        if(!shift)selectionAnchor=id
    }
    override fun selectAll(){mutable.update{it.copy(selectedIds=displayedTracks(it).map{t->t.id}.toSet())}}
    override fun clearSelection(){mutable.update{it.copy(selectedIds=emptySet())};selectionAnchor=null}
    override fun removeSelected(){val s=state.value;val ids=s.selectedIds
        when(s.view){"likes"->s.likes.filter{it.id in ids}.forEach{library.like(it,false)};"playlist"->s.playlistId?.let{p->ids.forEach{library.removeFromPlaylist(p,it)}};else->return}
        refreshCollections();if(s.view=="playlist")mutable.update{it.copy(visibleTracks=library.playlistTracks(s.playlistId!!))};clearSelection();toast("Удалено из подборки: ${ids.size}")
    }
    override fun enqueueMany(tracks:List<Track>) {val s=state.value;val known=s.queue.map{it.id}.toMutableSet();val added=tracks.filter{known.add(it.id)}
        mutable.update{it.copy(queue=it.queue+added)};save();toast(if(added.isEmpty())"Эти записи уже в очереди" else "В очереди добавлено: ${added.size}");prepareNext()
    }
    override fun reorderQueue(ids:List<String>) {val s=state.value;require(ids.size==s.queue.size&&ids.toSet()==s.queue.map{it.id}.toSet());val anchor=s.queue.getOrNull(s.queueIndex)?.id;val byId=s.queue.associateBy{it.id};mutable.update{it.copy(queue=ids.map{key->byId.getValue(key)},queueIndex=ids.indexOf(anchor))};save();prepareNext()}
    override fun reorderPlaylist(ids:List<String>) {val s=state.value;val id=s.playlistId?:return;if(s.localFilter.isNotBlank()||s.localOrder!="custom")return;library.reorderPlaylist(id,ids);mutable.update{it.copy(visibleTracks=library.playlistTracks(id))};refreshCollections()}
    override fun createPlaylistFrom(name:String,tracks:List<Track>):Long {val id=library.createPlaylist(name);if(tracks.isNotEmpty())library.addToPlaylist(id,tracks);refreshCollections();toast("Плейлист создан");return id}
    override fun duplicatePlaylist(id:Long) {library.duplicatePlaylist(id);refreshCollections();toast("Копия плейлиста создана")}
    private fun playbackReference(track:Track):Track {val s=state.value;return s.playbackReference?.takeIf{it.id==track.id||s.current?.id==track.id}?:track}
    override fun findVersions(track:Track) {val reference=playbackReference(track);versionJob?.cancel();val generation=++versionGeneration;val preferred=library.preferred(reference);val saved=if(preferred.id!=reference.id)listOf(RecordingVersion(preferred,"Сохранённая запись","Ранее выбранная тобой загрузка. Содержание и доступность могут измениться."))else emptyList();mutable.update{it.copy(versionReference=reference,versions=saved,versionsLoading=true,versionError="")}
        versionJob=scope.launch{try{val versions=withContext(ioDispatcher){source.alternatives(reference)};if(generation==versionGeneration)mutable.update{it.copy(versions=(saved+versions).distinctBy{v->v.track.id},versionsLoading=false)}}catch(e:CancellationException){throw e}catch(e:Exception){if(generation==versionGeneration)mutable.update{it.copy(versionsLoading=false,versionError="Не удалось проверить другие записи. Повтори запрос.")}}}
    }
    override fun closeVersions(){versionJob?.cancel();versionGeneration++;mutable.update{it.copy(versionReference=null,versionsLoading=false)}}
    override fun chooseVersion(original:Track,replacement:Track){val reference=playbackReference(original);library.setPreferred(reference,replacement);closeVersions();play(reference)}
    override fun resetVersion(original:Track){val reference=playbackReference(original);library.setPreferred(reference,null);closeVersions();play(reference)}
    private fun loadLyrics(track:Track,force:Boolean=false) {
        lyricsJob?.cancel();val generation=playGeneration;mutable.update{it.copy(lyricsLoading=true)}
        lyricsJob=scope.launch {try{
            val packet=withContext(ioDispatcher){source.lyricsPacket(track,force)}
            if(generation!=playGeneration)return@launch
            mutable.update{it.copy(lyrics=packet.lines,lyricsPacket=packet,lyricsLoading=false,approximateWords=packet.approximateWords)}
            if(packet.state=="synced"&&packet.approximateWords){val richer=withContext(ioDispatcher){source.enrichLyrics(track,packet)};if(generation==playGeneration)mutable.update{it.copy(lyrics=richer.lines,lyricsPacket=richer,approximateWords=richer.approximateWords)}}
        }catch(e:CancellationException){throw e}catch(_:Exception){if(generation==playGeneration)mutable.update{it.copy(lyricsLoading=false,lyricsPacket=LyricsPacket(message="Не удалось получить текст. Можно повторить запрос."))}}}
    }
    override fun reloadLyrics(){state.value.current?.let{loadLyrics(it,true)}}
    override fun importLyrics(text:String,format:String){val track=state.value.current?:return;val generation=playGeneration;lyricsJob?.cancel();lyricsJob=scope.launch{try{val packet=withContext(ioDispatcher){source.importLyrics(track,text,format)};if(generation==playGeneration)mutable.update{it.copy(lyrics=packet.lines,lyricsPacket=packet,approximateWords=packet.approximateWords,lyricsLoading=false)}}catch(e:CancellationException){throw e}catch(_:Exception){if(generation==playGeneration){mutable.update{it.copy(lyricsLoading=false)};toast("Не удалось прочитать файл текста")}}}}
    override fun setReducedMotion(value:Boolean){library.setSetting("reduced_motion",if(value)"on" else "off");mutable.update{it.copy(reducedMotion=value)}}
    override fun setSearchOrder(value:String){require(value in setOf("relevance","views"));mutable.update{it.copy(searchOrder=value)};if(state.value.query.isNotBlank())startSearch(state.value.query,40,false)}
    override fun loadMore(){val s=state.value;if(!s.searchLoading&&s.canLoadMore)startSearch(s.query,(s.searchLimit+40).coerceAtMost(120),false)}
    private fun prepareNext(){val s=state.value
        val priorityTrack=priority.firstOrNull()?.let{id->s.queue.firstOrNull{it.id==id}}
        val forward=if(s.shuffle)(traversalIndex+1..traversal.lastIndex).firstOrNull{i->s.queue.any{it.id==traversal[i]}}?.let{i->s.queue.first{it.id==traversal[i]}}else null
        val candidate=priorityTrack?:if(s.shuffle){
            val candidates=s.queue.filter{it.id !in visited}.ifEmpty{if(s.repeatMode=="all")s.queue.filter{it.id!=s.queue.getOrNull(s.queueIndex)?.id}else emptyList()}
            forward?:candidates.firstOrNull{it.id==plannedShuffle}?:candidates.randomOrNull()?.also{plannedShuffle=it.id}
        }else if(continuation!=null)continuation?.firstOrNull()?.let{id->s.queue.firstOrNull{it.id==id}}?:if(s.repeatMode=="all")s.queue.firstOrNull()else null
        else s.queue.getOrNull(s.queueIndex+1)?:if(s.repeatMode=="all")s.queue.firstOrNull()else null
        val effective=candidate?.let(library::preferred)?:run{prefetchJob?.cancel();prefetchedId=null;return}
        if(effective.id==prefetchedId)return
        prefetchedId=effective.id;prefetchJob?.cancel();prefetchJob=scope.launch{try{withContext(ioDispatcher){source.prefetch(effective)}}catch(e:CancellationException){throw e}catch(_:Exception){prefetchedId=null}}
    }
    private fun save() {val s=state.value;library.saveQueue(s.queue,s.queueIndex,s.current)
        library.setSetting("playback_reference",s.playbackReference?.let{Json.encodeToJsonElement(it).toString()}?:"")
        library.setSetting("queue_next_ids",JsonArray(priority.map(::JsonPrimitive)).toString())
        library.setSetting("queue_continuation",continuation?.let{JsonArray(it.map(::JsonPrimitive))}?.toString()?:"null")
    }
    private fun refreshCollections() { mutable.update{it.copy(likes=library.likes(),history=library.history(),playlists=library.playlists())} }
    override fun search(query:String) {val input=query.trim();if(input.isNotEmpty())startSearch(input,40,true)}
    private fun startSearch(input:String,limit:Int,navigate:Boolean) {
        if(input.length>500){toast("Поисковый запрос слишком длинный");return}
        searchJob?.cancel();val generation=++searchGeneration
        if(navigate)applyNavigation(Navigation("search"),true)
        val order=state.value.searchOrder
        val expanding=input==state.value.query&&limit>state.value.searchLimit
        if(!expanding)searchResults=emptyList()
        mutable.update{it.copy(query=input,searchLoading=true,visibleTracks=if(!expanding&&it.view=="search")emptyList()else it.visibleTracks,searchLimit=if(expanding)it.searchLimit else 40,canLoadMore=if(expanding)it.canLoadMore else false,status="Ищем музыку…")}
        searchJob=scope.launch {try{
            val results=withContext(ioDispatcher){source.searchSorted(input,limit,order)}
            if(generation==searchGeneration){searchResults=results;mutable.update{it.copy(visibleTracks=if(it.view=="search")results else it.visibleTracks,searchLoading=false,searchLimit=limit,canLoadMore=results.size>=limit&&limit<120,status=if(results.isEmpty())"Ничего не найдено" else "Найдено: ${results.size}")}}
        }catch(e:CancellationException){throw e}catch(e:Exception){if(generation==searchGeneration)mutable.update{it.copy(searchLoading=false,status="Не удалось выполнить поиск. Проверь соединение и повтори запрос.")}}}
    }
    override fun playSuggestion(suggestion:Suggestion) {
        suggestionJob?.cancel();val generation=++suggestionGeneration
        mutable.update{it.copy(resolvingSuggestionId=suggestion.catalogId,status="Ищем запись для рекомендации…")}
        suggestionJob=scope.launch {
            try {
                val track=withContext(ioDispatcher){source.resolveSuggestion(suggestion)}
                if(generation==suggestionGeneration){suggestionJob=null;play(track)}
            }catch(e:CancellationException){throw e}catch(_:Exception){if(generation==suggestionGeneration){mutable.update{it.copy(resolvingSuggestionId=null,status="Подходящая запись не найдена")};toast("Подходящая запись не найдена")}}
        }
    }
    override fun refreshRecommendations(){recommendations()}
    private fun recommendations() {
        recommendationJob?.cancel()
        val seeds=state.value.likes
        if(seeds.isEmpty()){mutable.update{it.copy(suggestions=emptyList(),status="Поставь лайки любимым трекам")};return}
        mutable.update{it.copy(recommendationsLoading=true,status="Подбираем музыку…")}
        recommendationJob=scope.launch {try {
            val items=withContext(ioDispatcher){source.recommend(seeds,state.value.history)}
            mutable.update{it.copy(suggestions=items,recommendationsLoading=false,status=if(items.isEmpty())"В музыкальном каталоге недостаточно данных" else "Рекомендации готовы")}
        }catch(e:CancellationException){throw e}catch(e:Exception){mutable.update{it.copy(recommendationsLoading=false,status="Рекомендации пока недоступны")}}}
    }
    override fun showView(view:String){applyNavigation(Navigation(view),true)}
    override fun openPlaylist(id:Long){applyNavigation(Navigation("playlist",id),true)}
    override fun play(track:Track) {
        suggestionGeneration++;suggestionJob?.cancel();suggestionJob=null
        playJob?.cancel();lyricsJob?.cancel();val generation=++playGeneration;logged=false;endHandled=false;sourceAttached=false
        wantPlay=true;pendingSeek=null;plannedShuffle=null
        val selected=library.preferred(track)
        val s=state.value
        val context=if(s.view=="playlist"||s.view=="likes")displayedTracks(s) else s.queue
        if(context.map{it.id}!=s.queue.map{it.id}) {visited.clear();priority.clear();traversal.clear();traversalIndex=-1}
        continuation=null
        mutable.update{it.copy(playbackReference=track,playbackError=null,lyricsLoading=false,resolvingSuggestionId=null,current=selected,queue=context,queueIndex=context.indexOfFirst{t->t.id==track.id},loading=true,playbackLoading=true,playing=false,seekable=false,positionMs=0,durationMs=selected.duration*1000L,lyrics=emptyList(),lyricsPacket=LyricsPacket(),status="Подключаем запись…")}
        visited.add(track.id);priority.removeAll{it==track.id}
        if(!preserveTraversal) {
            if(traversalIndex+1<traversal.size)traversal.subList(traversalIndex+1,traversal.size).clear()
            if(traversal.lastOrNull()!=track.id)traversal.add(track.id)
            traversalIndex=traversal.lastIndex
        }
        save();audio.pause()
        playJob=scope.launch {
            try { val stream=withContext(ioDispatcher){source.resolve(selected)}
                if(generation!=playGeneration)return@launch
                audio.open(stream.copy(autoPlay=wantPlay))
                if(generation==playGeneration) {
                    sourceAttached=true
                    mutable.update{it.copy(loading=false,playbackLoading=false,status="Подключаем запись…")}
                    loadLyrics(selected)
                    prepareNext()
                }
            }catch(e:CancellationException){throw e}catch(e:Exception){if(generation==playGeneration)mutable.update{it.copy(playbackError="Запись недоступна. Повтори попытку.",loading=false,playbackLoading=false,playing=false,status="Запись недоступна. Повтори попытку.")}}
        }
    }
    override fun enqueue(track:Track){enqueueMany(listOf(track))}
    override fun playNext(track:Track) {
        if(state.value.current?.id==library.preferred(track).id)return
        val currentAnchor=state.value.queue.getOrNull(state.value.queueIndex)?.id
        val list=state.value.queue.filter{it.id!=track.id}.toMutableList()
        val anchor=list.indexOfFirst{it.id==currentAnchor}
        list.add((anchor+1).coerceIn(0,list.size),track)
        priority.removeAll{it==track.id};priority.add(0,track.id)
        continuation=continuation?.let{listOf(track.id)+it.filter{key->key!=track.id}}
        mutable.update{it.copy(queue=list,queueIndex=anchor)};save();prepareNext()
    }
    private fun playQueued(index:Int,record:Boolean=true) {
        if(index !in state.value.queue.indices)return
        val track=state.value.queue[index]
        val previousView=state.value.view
        // Queue navigation must never replace the queue with an unrelated visible list.
        preserveTraversal=!record
        try {mutable.update{it.copy(view="queue")};play(track)} finally{preserveTraversal=false;mutable.update{it.copy(view=previousView)}}
    }
    override fun playQueueTrack(id:String) {playQueued(state.value.queue.indexOfFirst{it.id==id})}
    override fun playQueue() {if(state.value.queue.isNotEmpty())playQueued(0)}
    override fun playAll() {
        val tracks=displayedTracks(state.value).distinctBy{it.id};if(tracks.isEmpty())return
        priority.clear();traversal.clear();visited.clear();traversalIndex=-1;continuation=null
        mutable.update{it.copy(queue=tracks,queueIndex=-1)};playQueued(0)
    }
    override fun removeFromQueue(id:String) {
        val s=state.value;val anchor=s.queue.getOrNull(s.queueIndex)?.id
        val list=s.queue.filter{it.id!=id};priority.removeAll{it==id}
        continuation=if(anchor==id)s.queue.drop(s.queueIndex+1).map{it.id}.filter{it!=id}else continuation?.filter{it!=id}
        mutable.update{it.copy(queue=list,queueIndex=list.indexOfFirst{t->t.id==anchor})};save();prepareNext()
    }
    override fun moveInQueue(id:String,offset:Int) {
        require(offset in listOf(-1,1));val s=state.value;val anchor=s.queue.getOrNull(s.queueIndex)?.id
        val from=s.queue.indexOfFirst{it.id==id};val to=from+offset
        if(from<0||to !in s.queue.indices)return
        val list=s.queue.toMutableList();list.add(to,list.removeAt(from))
        mutable.update{it.copy(queue=list,queueIndex=list.indexOfFirst{t->t.id==anchor})};save();prepareNext()
    }
    override fun refreshAudioDevices(){val devices=audio.devices();var selected=state.value.audioDevice
        if(devices.isNotEmpty()&&devices.none{it.id==selected}){selected="auto";runCatching{audio.selectDevice(selected)};library.setSetting("mpv_audio_device",selected)}
        mutable.update{it.copy(audioDevices=devices,audioDevice=selected)}
    }
    override fun selectAudioDevice(id:String) {
        runCatching{audio.selectDevice(id)}.onSuccess{library.setSetting("mpv_audio_device",id);mutable.update{it.copy(audioDevice=id)}}.onFailure{mutable.update{it.copy(status="Не удалось переключить аудиовыход")}}
    }
    override fun editPlaylist(id:Long,name:String,description:String) {library.editPlaylist(id,name,description);refreshCollections()}
    override fun deletePlaylist(id:Long) {
        val wasCurrent=state.value.playlistId==id;library.deletePlaylist(id);refreshCollections()
        val position=navigation.take(navigationIndex+1).count{it.playlistId!=id}-1
        navigation.removeAll{it.playlistId==id};if(navigation.isEmpty())navigation.add(Navigation("home"))
        navigationIndex=position.coerceIn(0,navigation.lastIndex)
        if(wasCurrent)showView("playlists")else mutable.update{it.copy(canGoBack=navigationIndex>0,canGoForward=navigationIndex<navigation.lastIndex)}
        preferences.remove("playlist:$id")
    }
    override fun removeFromPlaylist(id:Long,trackId:String) {library.removeFromPlaylist(id,trackId);refreshCollections();if(state.value.playlistId==id)openPlaylist(id)}
    override fun next() {
        val s=state.value;if(s.queue.isEmpty())return
        val preferred=priority.firstOrNull{key->s.queue.any{it.id==key}}
        if(preferred!=null){playQueued(s.queue.indexOfFirst{it.id==preferred});return}
        if(s.shuffle) {
            val forward=(traversalIndex+1..traversal.lastIndex).firstOrNull{i->s.queue.any{it.id==traversal[i]}}
            if(forward!=null){traversalIndex=forward;playQueued(s.queue.indexOfFirst{it.id==traversal[forward]},false);return}
            var candidates=s.queue.indices.filter{s.queue[it].id !in visited}
            if(candidates.isEmpty()&&s.repeatMode=="all") {visited.clear();s.queue.getOrNull(s.queueIndex)?.let{visited.add(it.id)};candidates=s.queue.indices.filter{s.queue[it].id !in visited};if(candidates.isEmpty())candidates=s.queue.indices.toList()}
            if(candidates.isNotEmpty()){val selected=candidates.firstOrNull{s.queue[it].id==plannedShuffle}?:candidates.random();plannedShuffle=null;playQueued(selected)}
        }else{
            val after=continuation?.firstOrNull{key->s.queue.any{it.id==key}}
            if(after!=null){playQueued(s.queue.indexOfFirst{it.id==after});return}
            if(continuation!=null){if(s.repeatMode=="all")playQueued(0);return}
            val index=s.queueIndex+1;if(index<s.queue.size)playQueued(index)else if(s.repeatMode=="all")playQueued(0)
        }
    }
    override fun previous() {
        if(state.value.positionMs>3000){seek(0);return}
        if(state.value.shuffle) {
            val index=(traversalIndex-1 downTo 0).firstOrNull{i->state.value.queue.any{it.id==traversal[i]}}?:return
            traversalIndex=index;playQueued(state.value.queue.indexOfFirst{it.id==traversal[index]},false)
        }else playQueued(state.value.queueIndex-1)
    }
    override fun toggle(){val s=state.value
        if(s.playbackLoading){wantPlay=!wantPlay;if(sourceAttached){if(wantPlay)audio.resume()else audio.pause()};return}
        if(s.current==null){if(s.queue.isNotEmpty())playQueued(0)}else if(!sourceAttached)play(s.queue.getOrNull(s.queueIndex)?:s.current)else if(audio.state.value.ended){wantPlay=true;audio.seek(0);audio.resume()}else {wantPlay=!audio.state.value.playing;audio.toggle()}
    }
    override fun seek(positionMs:Long){val s=state.value;val target=positionMs.coerceIn(0,s.durationMs.coerceAtLeast(0))
        if(!sourceAttached){if(s.current!=null){if(!s.playbackLoading)play(s.queue.getOrNull(s.queueIndex)?:s.current);pendingSeek=target};return}
        if(s.seekable)audio.seek(target)else pendingSeek=target
    }
    override fun setVolume(volume:Float){val value=volume.coerceIn(0f,1f);audio.setVolume(value);mutable.update{it.copy(volume=value)};volumeJob?.cancel();volumeJob=scope.launch{delay(250);withContext(ioDispatcher){library.setSetting("volume",value.toString())}}}
    override fun toggleLike(track:Track) {library.like(track,state.value.likes.none{it.id==track.id});recommendationJob?.cancel();mutable.update{it.copy(suggestions=emptyList(),recommendationsLoading=false)};refreshCollections();if(state.value.view=="likes")showView("likes");if(state.value.view=="resonance")recommendations()}
    override fun clearQueue() { prefetchJob?.cancel();prefetchedId=null;plannedShuffle=null;priority.clear();continuation=null;traversal.clear();traversalIndex=-1;mutable.update{it.copy(queue=emptyList(),queueIndex=-1)};save() }
    override fun createPlaylist(name:String) {library.createPlaylist(name);refreshCollections()}
    override fun addToPlaylist(id:Long,tracks:List<Track>) {library.addToPlaylist(id,tracks);refreshCollections();toast("Плейлист обновлён")}
    override fun toggleShuffle() { mutable.update{it.copy(shuffle=!it.shuffle)};visited.clear();(state.value.queue.getOrNull(state.value.queueIndex)?:state.value.current)?.let{visited.add(it.id)};plannedShuffle=null;library.setSetting("shuffle",if(state.value.shuffle)"on" else "off");prepareNext() }
    override fun cycleRepeat() { val modes=listOf("off","one","all");mutable.update{it.copy(repeatMode=modes[(modes.indexOf(it.repeatMode)+1)%3])};library.setSetting("repeat_mode",state.value.repeatMode);prepareNext() }
    override fun openNowPlaying(open:Boolean){mutable.update{it.copy(expanded=open)};val s=state.value;if(open&&s.current!=null&&!s.lyricsLoading&&s.lyricsPacket.lines.isEmpty()&&s.lyricsPacket.plainText.isBlank())loadLyrics(s.current)}
    override fun setLyricsFocus(focus:Boolean) {mutable.update{it.copy(lyricsFocus=focus)}}
    override fun toggleQueue() {mutable.update{it.copy(queueVisible=!it.queueVisible)}}
    fun close(){save();library.setSetting("volume",state.value.volume.toString());scope.cancel();audio.close();source.close();library.close()}
}
