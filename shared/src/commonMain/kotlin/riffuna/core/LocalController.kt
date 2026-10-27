package riffuna.core

import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import kotlinx.serialization.json.*

class LocalController(
    private val library: MusicLibrary,
    private val source: MusicSource,
    private val audio: AudioEngine,
    private val ioDispatcher: CoroutineDispatcher = Dispatchers.IO,
) : RiffunaController {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private val initialQueue = library.queue()
    private val queue = PlaybackQueue(initialQueue.first, initialQueue.second)
    private val initialCurrent = library.current()
    private val initialLikes = library.likes()
    private val initialHistory = library.history()
    private val initialReference =
        runCatching {
                Json.decodeFromJsonElement<Track>(
                    Json.parseToJsonElement(library.setting("playback_reference", ""))
                )
            }
            .getOrNull()
            ?.takeIf { library.preferred(it).id == initialCurrent?.id }
            ?: initialQueue.first.getOrNull(initialQueue.second)?.takeIf {
                library.preferred(it).id == initialCurrent?.id
            }
            ?: (initialQueue.first + initialLikes + initialHistory)
                .distinctBy { it.id }
                .take(256)
                .firstOrNull {
                    it.id != initialCurrent?.id && library.preferred(it).id == initialCurrent?.id
                }
            ?: initialCurrent
    private val mutable =
        MutableStateFlow(
            AppState(
                libraryState =
                    LibraryUiState(
                        likes = initialLikes,
                        history = initialHistory,
                        playlists = library.playlists(),
                    ),
                playback =
                    PlaybackUiState(
                        playbackReference = initialReference,
                        current = initialCurrent,
                        durationMs = initialCurrent?.duration?.times(1000L) ?: 0,
                        volume =
                            (library.setting("volume", "0.65").toFloatOrNull() ?: .65f).coerceIn(
                                0f,
                                1f,
                            ),
                    ),
                queueState =
                    QueueUiState(
                        queue = queue.tracks,
                        queueIndex = queue.index,
                        repeatMode = RepeatMode.fromKey(library.setting("repeat_mode", "off")),
                        shuffle = library.setting("shuffle", "off") == "on",
                    ),
                navigationState =
                    NavigationUiState(
                        reducedMotion = library.setting("reduced_motion", "off") == "on"
                    ),
            )
        )
    override val state: StateFlow<AppState> = mutable

    private data class Navigation(val view: LibraryView, val playlistId: Long? = null)

    private val navigation = mutableListOf(Navigation(LibraryView.HOME))
    private var navigationIndex = 0
    private val preferences = mutableMapOf<String, Pair<String, LocalOrder>>()
    private var selectionAnchor: String? = null
    private var localLibraryJob: Job? = null
    private var localImportJob: Job? = null
    private var versionJob: Job? = null
    private var versionGeneration = 0L
    private var toastJob: Job? = null
    private var volumeJob: Job? = null
    private var prefetchJob: Job? = null
    private var prefetchedId: String? = null
    private var observedOutputRevision = 0L
    private var wantPlay = true
    private var pendingSeek: Long? = null
    private var searchResults = emptyList<Track>()
    private var searchJob: Job? = null
    private var playJob: Job? = null
    private var lyricsJob: Job? = null
    private var recommendationJob: Job? = null
    private var suggestionJob: Job? = null
    private var suggestionGeneration = 0L
    private var searchGeneration = 0L
    private var playGeneration = 0L
    private var logged = false
    private var sourceAttached = false
    private var endHandled = false
    private var preserveTraversal = false

    init {
        val devices = audio.devices()
        val old = library.setting("audio_output", "")
        val decoded =
            runCatching {
                    old.chunked(2)
                        .map { it.toInt(16).toByte() }
                        .toByteArray()
                        .decodeToString()
                        .replace("\u0000", "")
                }
                .getOrDefault("")
        val legacyGuid = Regex("\\{[0-9a-fA-F-]{36}\\}").find(decoded)?.value
        val legacy =
            legacyGuid?.let { guid -> devices.firstOrNull { it.id.contains(guid, true) }?.id }
                ?: "auto"
        val selected =
            library.setting("mpv_audio_device", legacy).takeIf { key ->
                devices.any { it.id == key }
            } ?: "auto"
        if (devices.isNotEmpty()) runCatching { audio.selectDevice(selected) }
        mutable.update {
            it.copy(playback = it.playback.copy(audioDevices = devices, audioDevice = selected))
        }
        val priorityIds =
            runCatching {
                    Json.parseToJsonElement(library.setting("queue_next_ids", "[]")).jsonArray.map {
                        it.jsonPrimitive.content
                    }
                }
                .getOrDefault(emptyList())
        val continuationIds =
            runCatching {
                    Json.parseToJsonElement(library.setting("queue_continuation", "null"))
                        .jsonArray
                        .map { it.jsonPrimitive.content }
                }
                .getOrNull()
        queue.restore(priorityIds, continuationIds)
        audio.setVolume(state.value.volume)
        scope.launch {
            audio.state.collect { value ->
                if (value.outputRevision != observedOutputRevision) {
                    observedOutputRevision = value.outputRevision
                    refreshAudioDevices()
                }
                if (!sourceAttached) return@collect
                mutable.update {
                    it.copy(
                        playback =
                            it.playback.copy(
                                positionMs = value.positionMs,
                                durationMs =
                                    if (value.durationMs > 0) value.durationMs
                                    else it.current?.duration?.times(1000L) ?: 0,
                                playing = value.playing,
                                seekable = value.seekable,
                                playbackLoading = value.buffering && wantPlay,
                            )
                    )
                }
                if (value.seekable)
                    pendingSeek?.let { target ->
                        pendingSeek = null
                        audio.seek(target)
                    }
                if (value.playing && state.value.status == "Подключаем запись…")
                    mutable.update { it.copy(status = "Сейчас играет") }
                if (value.playing && !logged) {
                    state.value.current?.let { library.recordPlay(it) }
                    logged = true
                    mutable.update {
                        it.copy(libraryState = it.libraryState.copy(history = library.history()))
                    }
                }
                if (!value.ended && value.playing) endHandled = false
                if (value.ended && !endHandled) {
                    endHandled = true
                    if (state.value.repeatMode == RepeatMode.ONE) {
                        audio.seek(0)
                        audio.resume()
                    } else next()
                }
                if (value.error != null) {
                    state.value.current?.let(source::invalidate)
                    sourceAttached = false
                    wantPlay = false
                    mutable.update {
                        it.copy(
                            status = value.error,
                            playback =
                                it.playback.copy(
                                    playbackError = value.error,
                                    playing = false,
                                    seekable = false,
                                    loading = false,
                                    playbackLoading = false,
                                ),
                        )
                    }
                    toast(value.error)
                }
            }
        }
    }

    private fun refreshLocalTracks() {
        localLibraryJob?.cancel()
        localLibraryJob =
            scope.launch {
                try {
                    val tracks = withContext(ioDispatcher) { source.localTracks() }
                    if (state.value.view == LibraryView.LOCAL)
                        mutable.update {
                            it.copy(libraryState = it.libraryState.copy(visibleTracks = tracks))
                        }
                } catch (e: CancellationException) {
                    throw e
                } catch (_: Exception) {
                    toast("Не удалось прочитать локальную библиотеку")
                }
            }
    }

    override fun importLocalFiles(paths: List<String>) {
        if (paths.isEmpty() || state.value.localImporting) return
        showView(LibraryView.LOCAL)
        mutable.update { it.copy(libraryState = it.libraryState.copy(localImporting = true)) }
        localImportJob =
            scope.launch {
                try {
                    val result = withContext(ioDispatcher) { source.importLocalFiles(paths) }
                    refreshLocalTracks()
                    toast(
                        "Добавлено: ${result.imported}, обновлено: ${result.updated}, пропущено: ${result.skipped}"
                    )
                } catch (e: CancellationException) {
                    throw e
                } catch (_: Exception) {
                    toast("Не удалось импортировать аудиофайлы")
                } finally {
                    mutable.update {
                        it.copy(libraryState = it.libraryState.copy(localImporting = false))
                    }
                }
            }
    }

    private fun toast(text: String) {
        toastJob?.cancel()
        mutable.update { it.copy(toast = text) }
        toastJob =
            scope.launch {
                delay(2800)
                mutable.update { it.copy(toast = "") }
            }
    }

    private fun contextKey() = state.value.view.key + ":" + state.value.playlistId

    private fun applyNavigation(target: Navigation, push: Boolean) {
        preferences[contextKey()] = state.value.localFilter to state.value.localOrder
        if (push && navigation.getOrNull(navigationIndex) != target) {
            while (navigation.lastIndex > navigationIndex) navigation.removeAt(navigation.lastIndex)
            navigation.add(target)
            navigationIndex = navigation.lastIndex
        }
        val prefs =
            preferences[target.view.key + ":" + target.playlistId] ?: Pair("", LocalOrder.CUSTOM)
        mutable.update {
            it.copy(
                navigationState =
                    it.navigationState.copy(
                        view = target.view,
                        playlistId = target.playlistId,
                        localFilter = prefs.first,
                        localOrder = prefs.second,
                        selectedIds = emptySet(),
                        canGoBack = navigationIndex > 0,
                        canGoForward = navigationIndex < navigation.lastIndex,
                    ),
                libraryState =
                    it.libraryState.copy(
                        visibleTracks =
                            when (target.view) {
                                LibraryView.LIKES -> it.likes
                                LibraryView.HISTORY -> it.history
                                LibraryView.SEARCH -> searchResults
                                LibraryView.PLAYLIST ->
                                    target.playlistId?.let(library::playlistTracks).orEmpty()
                                else -> emptyList()
                            }
                    ),
            )
        }
        selectionAnchor = null
        if (target.view == LibraryView.LOCAL) refreshLocalTracks()
        if (target.view == LibraryView.RESONANCE && state.value.suggestions.isEmpty())
            recommendations()
    }

    override fun navigateBack() {
        if (navigationIndex > 0) {
            navigationIndex--
            applyNavigation(navigation[navigationIndex], false)
        }
    }

    override fun navigateForward() {
        if (navigationIndex < navigation.lastIndex) {
            navigationIndex++
            applyNavigation(navigation[navigationIndex], false)
        }
    }

    override fun setLocalFilter(value: String) {
        mutable.update {
            it.copy(
                navigationState =
                    it.navigationState.copy(localFilter = value, selectedIds = emptySet())
            )
        }
        selectionAnchor = null
    }

    override fun setLocalOrder(value: LocalOrder) {
        mutable.update {
            it.copy(
                navigationState =
                    it.navigationState.copy(localOrder = value, selectedIds = emptySet())
            )
        }
        selectionAnchor = null
    }

    override fun selectTrack(id: String, control: Boolean, shift: Boolean) {
        val ids = displayedTracks(state.value).map { it.id }
        if (id !in ids) return
        val anchor = ids.indexOf(selectionAnchor)
        val at = ids.indexOf(id)
        val chosen =
            if (shift && anchor >= 0) ids.subList(minOf(anchor, at), maxOf(anchor, at) + 1).toSet()
            else setOf(id)
        mutable.update {
            it.copy(
                navigationState =
                    it.navigationState.copy(
                        selectedIds =
                            when {
                                shift && control -> it.selectedIds + chosen
                                shift -> chosen
                                control ->
                                    if (id in it.selectedIds) it.selectedIds - id
                                    else it.selectedIds + id
                                else -> chosen
                            }
                    )
            )
        }
        if (!shift) selectionAnchor = id
    }

    override fun selectAll() {
        mutable.update {
            it.copy(
                navigationState =
                    it.navigationState.copy(
                        selectedIds = displayedTracks(it).map { t -> t.id }.toSet()
                    )
            )
        }
    }

    override fun clearSelection() {
        mutable.update {
            it.copy(navigationState = it.navigationState.copy(selectedIds = emptySet()))
        }
        selectionAnchor = null
    }

    override fun removeSelected() {
        val s = state.value
        val ids = s.selectedIds
        when (s.view) {
            LibraryView.LIKES -> s.likes.filter { it.id in ids }.forEach { library.like(it, false) }
            LibraryView.PLAYLIST ->
                s.playlistId?.let { p -> ids.forEach { library.removeFromPlaylist(p, it) } }
            else -> return
        }
        refreshCollections()
        if (s.view == LibraryView.PLAYLIST)
            mutable.update {
                it.copy(
                    libraryState =
                        it.libraryState.copy(visibleTracks = library.playlistTracks(s.playlistId!!))
                )
            }
        clearSelection()
        toast("Удалено из подборки: ${ids.size}")
    }

    override fun enqueueMany(tracks: List<Track>) {
        val added = queue.enqueue(tracks)
        publishQueue()
        save()
        toast(if (added == 0) "Эти записи уже в очереди" else "В очереди добавлено: $added")
        prepareNext()
    }

    private fun publishQueue() {
        mutable.update {
            it.copy(queueState = it.queueState.copy(queue = queue.tracks, queueIndex = queue.index))
        }
    }

    override fun reorderQueue(ids: List<String>) {
        queue.reorder(ids)
        publishQueue()
        save()
        prepareNext()
    }

    override fun reorderPlaylist(ids: List<String>) {
        val s = state.value
        val id = s.playlistId ?: return
        if (s.localFilter.isNotBlank() || s.localOrder != LocalOrder.CUSTOM) return
        library.reorderPlaylist(id, ids)
        mutable.update {
            it.copy(libraryState = it.libraryState.copy(visibleTracks = library.playlistTracks(id)))
        }
        refreshCollections()
    }

    override fun createPlaylistFrom(name: String, tracks: List<Track>): Long {
        val id = library.createPlaylist(name)
        if (tracks.isNotEmpty()) library.addToPlaylist(id, tracks)
        refreshCollections()
        toast("Плейлист создан")
        return id
    }

    override fun duplicatePlaylist(id: Long) {
        library.duplicatePlaylist(id)
        refreshCollections()
        toast("Копия плейлиста создана")
    }

    private fun playbackReference(track: Track): Track {
        val s = state.value
        return s.playbackReference?.takeIf { it.id == track.id || s.current?.id == track.id }
            ?: track
    }

    override fun findVersions(track: Track) {
        val reference = playbackReference(track)
        versionJob?.cancel()
        val generation = ++versionGeneration
        val preferred = library.preferred(reference)
        val saved =
            if (preferred.id != reference.id)
                listOf(
                    RecordingVersion(
                        preferred,
                        "Сохранённая запись",
                        "Ранее выбранная тобой загрузка. Содержание и доступность могут измениться.",
                    )
                )
            else emptyList()
        mutable.update {
            it.copy(
                versionsState =
                    it.versionsState.copy(
                        versionReference = reference,
                        versions = saved,
                        versionsLoading = true,
                        versionError = "",
                    )
            )
        }
        versionJob =
            scope.launch {
                try {
                    val versions = withContext(ioDispatcher) { source.alternatives(reference) }
                    if (generation == versionGeneration)
                        mutable.update {
                            it.copy(
                                versionsState =
                                    it.versionsState.copy(
                                        versions =
                                            (saved + versions).distinctBy { v -> v.track.id },
                                        versionsLoading = false,
                                    )
                            )
                        }
                } catch (e: CancellationException) {
                    throw e
                } catch (e: Exception) {
                    if (generation == versionGeneration)
                        mutable.update {
                            it.copy(
                                versionsState =
                                    it.versionsState.copy(
                                        versionsLoading = false,
                                        versionError =
                                            "Не удалось проверить другие записи. Повтори запрос.",
                                    )
                            )
                        }
                }
            }
    }

    override fun closeVersions() {
        versionJob?.cancel()
        versionGeneration++
        mutable.update {
            it.copy(
                versionsState =
                    it.versionsState.copy(versionReference = null, versionsLoading = false)
            )
        }
    }

    override fun chooseVersion(original: Track, replacement: Track) {
        val reference = playbackReference(original)
        library.setPreferred(reference, replacement)
        closeVersions()
        play(reference)
    }

    override fun resetVersion(original: Track) {
        val reference = playbackReference(original)
        library.setPreferred(reference, null)
        closeVersions()
        play(reference)
    }

    private fun loadLyrics(track: Track, force: Boolean = false) {
        lyricsJob?.cancel()
        val generation = playGeneration
        mutable.update { it.copy(lyricsState = it.lyricsState.copy(lyricsLoading = true)) }
        lyricsJob =
            scope.launch {
                try {
                    val packet = withContext(ioDispatcher) { source.lyricsPacket(track, force) }
                    if (generation != playGeneration) return@launch
                    mutable.update {
                        it.copy(
                            lyricsState =
                                it.lyricsState.copy(
                                    lyrics = packet.lines,
                                    lyricsPacket = packet,
                                    lyricsLoading = false,
                                    approximateWords = packet.approximateWords,
                                )
                        )
                    }
                    if (packet.state == "synced" && packet.approximateWords) {
                        val richer =
                            withContext(ioDispatcher) { source.enrichLyrics(track, packet) }
                        if (generation == playGeneration)
                            mutable.update {
                                it.copy(
                                    lyricsState =
                                        it.lyricsState.copy(
                                            lyrics = richer.lines,
                                            lyricsPacket = richer,
                                            approximateWords = richer.approximateWords,
                                        )
                                )
                            }
                    }
                } catch (e: CancellationException) {
                    throw e
                } catch (_: Exception) {
                    if (generation == playGeneration)
                        mutable.update {
                            it.copy(
                                lyricsState =
                                    it.lyricsState.copy(
                                        lyricsLoading = false,
                                        lyricsPacket =
                                            LyricsPacket(
                                                message =
                                                    "Не удалось получить текст. Можно повторить запрос."
                                            ),
                                    )
                            )
                        }
                }
            }
    }

    override fun reloadLyrics() {
        state.value.current?.let { loadLyrics(it, true) }
    }

    override fun importLyrics(text: String, format: String) {
        val track = state.value.current ?: return
        val generation = playGeneration
        lyricsJob?.cancel()
        lyricsJob =
            scope.launch {
                try {
                    val packet =
                        withContext(ioDispatcher) { source.importLyrics(track, text, format) }
                    if (generation == playGeneration)
                        mutable.update {
                            it.copy(
                                lyricsState =
                                    it.lyricsState.copy(
                                        lyrics = packet.lines,
                                        lyricsPacket = packet,
                                        approximateWords = packet.approximateWords,
                                        lyricsLoading = false,
                                    )
                            )
                        }
                } catch (e: CancellationException) {
                    throw e
                } catch (_: Exception) {
                    if (generation == playGeneration) {
                        mutable.update {
                            it.copy(lyricsState = it.lyricsState.copy(lyricsLoading = false))
                        }
                        toast("Не удалось прочитать файл текста")
                    }
                }
            }
    }

    override fun setReducedMotion(value: Boolean) {
        library.setSetting("reduced_motion", if (value) "on" else "off")
        mutable.update { it.copy(navigationState = it.navigationState.copy(reducedMotion = value)) }
    }

    override fun setSearchOrder(value: SearchOrder) {
        mutable.update { it.copy(searchState = it.searchState.copy(searchOrder = value)) }
        if (state.value.query.isNotBlank()) startSearch(state.value.query, 40, false)
    }

    override fun loadMore() {
        val s = state.value
        if (!s.searchLoading && s.canLoadMore)
            startSearch(s.query, (s.searchLimit + 40).coerceAtMost(120), false)
    }

    private fun prepareNext() {
        val s = state.value
        val candidate = queue.peekNext(s.shuffle, s.repeatMode)
        val effective =
            candidate?.let(library::preferred)
                ?: run {
                    prefetchJob?.cancel()
                    prefetchedId = null
                    return
                }
        if (effective.id == prefetchedId) return
        prefetchedId = effective.id
        prefetchJob?.cancel()
        prefetchJob =
            scope.launch {
                try {
                    withContext(ioDispatcher) { source.prefetch(effective) }
                } catch (e: CancellationException) {
                    throw e
                } catch (_: Exception) {
                    prefetchedId = null
                }
            }
    }

    private fun save() {
        val s = state.value
        library.saveQueue(s.queue, s.queueIndex, s.current)
        library.setSetting(
            "playback_reference",
            s.playbackReference?.let { Json.encodeToJsonElement(it).toString() } ?: "",
        )
        library.setSetting(
            "queue_next_ids",
            JsonArray(queue.priorityIds.map(::JsonPrimitive)).toString(),
        )
        library.setSetting(
            "queue_continuation",
            queue.continuationIds?.let { JsonArray(it.map(::JsonPrimitive)) }?.toString() ?: "null",
        )
    }

    private fun refreshCollections() {
        mutable.update {
            it.copy(
                libraryState =
                    it.libraryState.copy(
                        likes = library.likes(),
                        history = library.history(),
                        playlists = library.playlists(),
                    )
            )
        }
    }

    override fun search(query: String) {
        val input = query.trim()
        if (input.isNotEmpty()) startSearch(input, 40, true)
    }

    private fun startSearch(input: String, limit: Int, navigate: Boolean) {
        if (input.length > 500) {
            toast("Поисковый запрос слишком длинный")
            return
        }
        searchJob?.cancel()
        val generation = ++searchGeneration
        if (navigate) applyNavigation(Navigation(LibraryView.SEARCH), true)
        val order = state.value.searchOrder
        val expanding = input == state.value.query && limit > state.value.searchLimit
        if (!expanding) searchResults = emptyList()
        mutable.update {
            it.copy(
                status = "Ищем музыку…",
                searchState =
                    it.searchState.copy(
                        query = input,
                        searchLoading = true,
                        searchLimit = if (expanding) it.searchLimit else 40,
                        canLoadMore = if (expanding) it.canLoadMore else false,
                    ),
                libraryState =
                    it.libraryState.copy(
                        visibleTracks =
                            if (!expanding && it.view == LibraryView.SEARCH) emptyList()
                            else it.visibleTracks
                    ),
            )
        }
        searchJob =
            scope.launch {
                try {
                    val results =
                        withContext(ioDispatcher) { source.searchSorted(input, limit, order) }
                    if (generation == searchGeneration) {
                        searchResults = results
                        mutable.update {
                            it.copy(
                                status =
                                    if (results.isEmpty()) "Ничего не найдено"
                                    else "Найдено: ${results.size}",
                                libraryState =
                                    it.libraryState.copy(
                                        visibleTracks =
                                            if (it.view == LibraryView.SEARCH) results
                                            else it.visibleTracks
                                    ),
                                searchState =
                                    it.searchState.copy(
                                        searchLoading = false,
                                        searchLimit = limit,
                                        canLoadMore = results.size >= limit && limit < 120,
                                    ),
                            )
                        }
                    }
                } catch (e: CancellationException) {
                    throw e
                } catch (e: Exception) {
                    if (generation == searchGeneration)
                        mutable.update {
                            it.copy(
                                status =
                                    "Не удалось выполнить поиск. Проверь соединение и повтори запрос.",
                                searchState = it.searchState.copy(searchLoading = false),
                            )
                        }
                }
            }
    }

    override fun playSuggestion(suggestion: Suggestion) {
        suggestionJob?.cancel()
        val generation = ++suggestionGeneration
        mutable.update {
            it.copy(
                status = "Ищем запись для рекомендации…",
                recommendationState =
                    it.recommendationState.copy(resolvingSuggestionId = suggestion.catalogId),
            )
        }
        suggestionJob =
            scope.launch {
                try {
                    val track = withContext(ioDispatcher) { source.resolveSuggestion(suggestion) }
                    if (generation == suggestionGeneration) {
                        suggestionJob = null
                        play(track)
                    }
                } catch (e: CancellationException) {
                    throw e
                } catch (_: Exception) {
                    if (generation == suggestionGeneration) {
                        mutable.update {
                            it.copy(
                                status = "Подходящая запись не найдена",
                                recommendationState =
                                    it.recommendationState.copy(resolvingSuggestionId = null),
                            )
                        }
                        toast("Подходящая запись не найдена")
                    }
                }
            }
    }

    override fun refreshRecommendations() {
        recommendations()
    }

    private fun recommendations() {
        recommendationJob?.cancel()
        val seeds = state.value.likes
        if (seeds.isEmpty()) {
            mutable.update {
                it.copy(
                    status = "Поставь лайки любимым трекам",
                    recommendationState = it.recommendationState.copy(suggestions = emptyList()),
                )
            }
            return
        }
        mutable.update {
            it.copy(
                status = "Подбираем музыку…",
                recommendationState = it.recommendationState.copy(recommendationsLoading = true),
            )
        }
        recommendationJob =
            scope.launch {
                try {
                    val items =
                        withContext(ioDispatcher) { source.recommend(seeds, state.value.history) }
                    mutable.update {
                        it.copy(
                            status =
                                if (items.isEmpty()) "В музыкальном каталоге недостаточно данных"
                                else "Рекомендации готовы",
                            recommendationState =
                                it.recommendationState.copy(
                                    suggestions = items,
                                    recommendationsLoading = false,
                                ),
                        )
                    }
                } catch (e: CancellationException) {
                    throw e
                } catch (e: Exception) {
                    mutable.update {
                        it.copy(
                            status = "Рекомендации пока недоступны",
                            recommendationState =
                                it.recommendationState.copy(recommendationsLoading = false),
                        )
                    }
                }
            }
    }

    override fun showView(view: LibraryView) {
        applyNavigation(Navigation(view), true)
    }

    override fun openPlaylist(id: Long) {
        applyNavigation(Navigation(LibraryView.PLAYLIST, id), true)
    }

    override fun play(track: Track) {
        suggestionGeneration++
        suggestionJob?.cancel()
        suggestionJob = null
        playJob?.cancel()
        lyricsJob?.cancel()
        val generation = ++playGeneration
        logged = false
        endHandled = false
        sourceAttached = false
        wantPlay = true
        pendingSeek = null
        val selected = library.preferred(track)
        val s = state.value
        val context =
            if (s.view == LibraryView.PLAYLIST || s.view == LibraryView.LIKES) displayedTracks(s)
            else s.queue
        queue.begin(track, context, recordHistory = !preserveTraversal)
        mutable.update {
            it.copy(
                status = "Подключаем запись…",
                playback =
                    it.playback.copy(
                        playbackReference = track,
                        playbackError = null,
                        current = selected,
                        loading = true,
                        playbackLoading = true,
                        playing = false,
                        seekable = false,
                        positionMs = 0,
                        durationMs = selected.duration * 1000L,
                    ),
                lyricsState =
                    it.lyricsState.copy(
                        lyricsLoading = false,
                        lyrics = emptyList(),
                        lyricsPacket = LyricsPacket(),
                    ),
                recommendationState = it.recommendationState.copy(resolvingSuggestionId = null),
                queueState = it.queueState.copy(queue = queue.tracks, queueIndex = queue.index),
            )
        }
        save()
        audio.pause()
        playJob =
            scope.launch {
                try {
                    val stream = withContext(ioDispatcher) { source.resolve(selected) }
                    if (generation != playGeneration) return@launch
                    audio.open(stream.copy(autoPlay = wantPlay))
                    if (generation == playGeneration) {
                        sourceAttached = true
                        mutable.update {
                            it.copy(
                                status = "Подключаем запись…",
                                playback =
                                    it.playback.copy(loading = false, playbackLoading = false),
                            )
                        }
                        loadLyrics(selected)
                        prepareNext()
                    }
                } catch (e: CancellationException) {
                    throw e
                } catch (e: Exception) {
                    if (generation == playGeneration)
                        mutable.update {
                            it.copy(
                                status = "Запись недоступна. Повтори попытку.",
                                playback =
                                    it.playback.copy(
                                        playbackError = "Запись недоступна. Повтори попытку.",
                                        loading = false,
                                        playbackLoading = false,
                                        playing = false,
                                    ),
                            )
                        }
                }
            }
    }

    override fun enqueue(track: Track) {
        enqueueMany(listOf(track))
    }

    override fun playNext(track: Track) {
        if (state.value.current?.id == library.preferred(track).id) return
        queue.enqueueNext(track)
        publishQueue()
        save()
        prepareNext()
    }

    private fun playQueued(index: Int, record: Boolean = true) {
        if (index !in state.value.queue.indices) return
        val track = state.value.queue[index]
        val previousView = state.value.view
        // Queue navigation must never replace the queue with an unrelated visible list.
        preserveTraversal = !record
        try {
            mutable.update {
                it.copy(navigationState = it.navigationState.copy(view = LibraryView.QUEUE))
            }
            play(track)
        } finally {
            preserveTraversal = false
            mutable.update {
                it.copy(navigationState = it.navigationState.copy(view = previousView))
            }
        }
    }

    override fun playQueueTrack(id: String) {
        playQueued(state.value.queue.indexOfFirst { it.id == id })
    }

    override fun playQueue() {
        if (state.value.queue.isNotEmpty()) playQueued(0)
    }

    override fun playAll() {
        val tracks = displayedTracks(state.value)
        if (tracks.isEmpty()) return
        queue.reset(tracks)
        publishQueue()
        playQueued(0)
    }

    override fun removeFromQueue(id: String) {
        queue.remove(id)
        publishQueue()
        save()
        prepareNext()
    }

    override fun moveInQueue(id: String, offset: Int) {
        queue.move(id, offset)
        publishQueue()
        save()
        prepareNext()
    }

    override fun refreshAudioDevices() {
        val devices = audio.devices()
        var selected = state.value.audioDevice
        if (devices.isNotEmpty() && devices.none { it.id == selected }) {
            selected = "auto"
            runCatching { audio.selectDevice(selected) }
            library.setSetting("mpv_audio_device", selected)
        }
        mutable.update {
            it.copy(playback = it.playback.copy(audioDevices = devices, audioDevice = selected))
        }
    }

    override fun selectAudioDevice(id: String) {
        runCatching { audio.selectDevice(id) }
            .onSuccess {
                library.setSetting("mpv_audio_device", id)
                mutable.update { it.copy(playback = it.playback.copy(audioDevice = id)) }
            }
            .onFailure { mutable.update { it.copy(status = "Не удалось переключить аудиовыход") } }
    }

    override fun editPlaylist(id: Long, name: String, description: String) {
        library.editPlaylist(id, name, description)
        refreshCollections()
    }

    override fun deletePlaylist(id: Long) {
        val wasCurrent = state.value.playlistId == id
        library.deletePlaylist(id)
        refreshCollections()
        val position = navigation.take(navigationIndex + 1).count { it.playlistId != id } - 1
        navigation.removeAll { it.playlistId == id }
        if (navigation.isEmpty()) navigation.add(Navigation(LibraryView.HOME))
        navigationIndex = position.coerceIn(0, navigation.lastIndex)
        if (wasCurrent) showView(LibraryView.PLAYLISTS)
        else
            mutable.update {
                it.copy(
                    navigationState =
                        it.navigationState.copy(
                            canGoBack = navigationIndex > 0,
                            canGoForward = navigationIndex < navigation.lastIndex,
                        )
                )
            }
        preferences.remove("playlist:$id")
    }

    override fun removeFromPlaylist(id: Long, trackId: String) {
        library.removeFromPlaylist(id, trackId)
        refreshCollections()
        if (state.value.playlistId == id) openPlaylist(id)
    }

    override fun next() {
        val s = state.value
        queue.next(s.shuffle, s.repeatMode)?.let { playQueued(it.index, it.recordHistory) }
    }

    override fun previous() {
        if (state.value.positionMs > 3000) {
            seek(0)
            return
        }
        queue.previous(state.value.shuffle)?.let { playQueued(it.index, it.recordHistory) }
    }

    fun pausePlayback() {
        wantPlay = false
        audio.pause()
    }

    fun resumePlayback() {
        wantPlay = true
        val current = state.value
        if (current.playbackLoading) {
            if (sourceAttached) audio.resume()
        } else if (current.current == null) {
            if (current.queue.isNotEmpty()) playQueued(0)
        } else if (!sourceAttached) {
            play(current.queue.getOrNull(current.queueIndex) ?: requireNotNull(current.current))
        } else {
            if (audio.state.value.ended) audio.seek(0)
            audio.resume()
        }
    }

    override fun toggle() {
        val s = state.value
        if (s.playbackLoading) {
            wantPlay = !wantPlay
            if (sourceAttached) {
                if (wantPlay) audio.resume() else audio.pause()
            }
            return
        }
        val current = s.current
        if (current == null) {
            if (s.queue.isNotEmpty()) playQueued(0)
        } else if (!sourceAttached)
            play(s.queue.getOrNull(s.queueIndex) ?: requireNotNull(s.current))
        else if (audio.state.value.ended) {
            wantPlay = true
            audio.seek(0)
            audio.resume()
        } else {
            wantPlay = !audio.state.value.playing
            audio.toggle()
        }
    }

    override fun seek(positionMs: Long) {
        val s = state.value
        val target = positionMs.coerceIn(0, s.durationMs.coerceAtLeast(0))
        if (!sourceAttached) {
            if (s.current != null) {
                if (!s.playbackLoading)
                    play(s.queue.getOrNull(s.queueIndex) ?: requireNotNull(s.current))
                pendingSeek = target
            }
            return
        }
        if (s.seekable) audio.seek(target) else pendingSeek = target
    }

    override fun setVolume(volume: Float) {
        val value = volume.coerceIn(0f, 1f)
        audio.setVolume(value)
        mutable.update { it.copy(playback = it.playback.copy(volume = value)) }
        volumeJob?.cancel()
        volumeJob =
            scope.launch {
                delay(250)
                withContext(ioDispatcher) { library.setSetting("volume", value.toString()) }
            }
    }

    override fun toggleLike(track: Track) {
        library.like(track, state.value.likes.none { it.id == track.id })
        recommendationJob?.cancel()
        mutable.update {
            it.copy(
                recommendationState =
                    it.recommendationState.copy(
                        suggestions = emptyList(),
                        recommendationsLoading = false,
                    )
            )
        }
        refreshCollections()
        if (state.value.view == LibraryView.LIKES) showView(LibraryView.LIKES)
        if (state.value.view == LibraryView.RESONANCE) recommendations()
    }

    override fun clearQueue() {
        prefetchJob?.cancel()
        prefetchedId = null
        queue.reset()
        publishQueue()
        save()
    }

    override fun createPlaylist(name: String) {
        library.createPlaylist(name)
        refreshCollections()
    }

    override fun addToPlaylist(id: Long, tracks: List<Track>) {
        library.addToPlaylist(id, tracks)
        refreshCollections()
        toast("Плейлист обновлён")
    }

    override fun toggleShuffle() {
        mutable.update { it.copy(queueState = it.queueState.copy(shuffle = !it.shuffle)) }
        queue.shuffleChanged()
        library.setSetting("shuffle", if (state.value.shuffle) "on" else "off")
        prepareNext()
    }

    override fun cycleRepeat() {
        mutable.update {
            it.copy(queueState = it.queueState.copy(repeatMode = it.repeatMode.next()))
        }
        library.setSetting("repeat_mode", state.value.repeatMode.key)
        prepareNext()
    }

    override fun openNowPlaying(open: Boolean) {
        mutable.update { it.copy(playback = it.playback.copy(expanded = open)) }
        val s = state.value
        if (
            open &&
                s.current != null &&
                !s.lyricsLoading &&
                s.lyricsPacket.lines.isEmpty() &&
                s.lyricsPacket.plainText.isBlank()
        )
            s.current?.let { loadLyrics(it) }
    }

    override fun setLyricsFocus(focus: Boolean) {
        mutable.update { it.copy(playback = it.playback.copy(lyricsFocus = focus)) }
    }

    override fun toggleQueue() {
        mutable.update { it.copy(queueState = it.queueState.copy(queueVisible = !it.queueVisible)) }
    }

    fun close() {
        save()
        library.setSetting("volume", state.value.volume.toString())
        scope.cancel()
        audio.close()
        source.close()
        library.close()
    }
}
