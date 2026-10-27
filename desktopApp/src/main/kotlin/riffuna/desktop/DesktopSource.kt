package riffuna.desktop

import java.nio.file.Files
import java.nio.file.Path
import java.time.Instant
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.*
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.json.*
import riffuna.core.*

class DesktopSource(private val home: Path, private val data: Path) : MusicSource {
    private class SourceFailure(val code: String, detail: String = "") :
        IllegalStateException("Source request failed: $code $detail")

    private val json = Json { ignoreUnknownKeys = true }
    private val streams = linkedMapOf<String, Pair<Long, AudioSource>>()
    private val transport = AudioTransport(data.resolve("audio-cache"))
    private val lyricsRepository = LyricsRepository(data.resolve("lyrics"))
    private val model = lazy {
        MusicModel(home.resolve("music-model"), ArtistTags(data.resolve("artist-tags"))::fetch)
    }

    private inner class Worker {
        private val mutex = kotlinx.coroutines.sync.Mutex()
        @Volatile private var process: Process? = null

        fun alive() = process?.isAlive == true

        private var writer: java.io.BufferedWriter? = null
        private var reader: java.io.BufferedReader? = null

        suspend fun execute(body: JsonObject): JsonObject {
            mutex.lock()
            try {
                return withContext(Dispatchers.IO) {
                    var active = process
                    if (active == null || !active.isAlive) {
                        val executable = home.resolve("vendor/node/node.exe")
                        val script = home.resolve("source-runtime/index.mjs")
                        check(Files.isRegularFile(executable) && Files.isRegularFile(script)) {
                            "YouTube component missing"
                        }
                        Files.createDirectories(data)
                        val builder =
                            ProcessBuilder(
                                    executable.toString(),
                                    "--no-warnings",
                                    script.toString(),
                                    data.resolve("youtube-js").toString(),
                                )
                                .directory(data.toFile())
                                .redirectError(
                                    if (System.getenv("RIFFUNA_SOURCE_TRACE") == "1")
                                        ProcessBuilder.Redirect.appendTo(
                                            data.resolve("source-trace.log").toFile()
                                        )
                                    else ProcessBuilder.Redirect.DISCARD
                                )
                        builder.environment().remove("NODE_USE_ENV_PROXY")
                        DesktopNetwork.proxyUrl()
                            .takeIf { it.isNotBlank() }
                            ?.let { proxy ->
                                builder.environment()["HTTPS_PROXY"] = proxy
                                builder.environment()["HTTP_PROXY"] = proxy
                            }
                        active = builder.start()
                        process = active
                        writer = active.outputStream.bufferedWriter(Charsets.UTF_8)
                        reader = active.inputStream.bufferedReader(Charsets.UTF_8)
                    }
                    val completed = java.util.concurrent.atomic.AtomicBoolean(false)
                    val cancellationGuard =
                        launch(Dispatchers.Default, start = CoroutineStart.UNDISPATCHED) {
                            try {
                                awaitCancellation()
                            } finally {
                                if (!completed.get()) active.destroyForcibly()
                            }
                        }
                    val timeout =
                        watchdog.schedule({ active.destroyForcibly() }, 65, TimeUnit.SECONDS)
                    try {
                        writer!!.write(body.toString())
                        writer!!.newLine()
                        writer!!.flush()
                        val text =
                            reader!!.readLine() ?: throw java.io.EOFException("Source closed")
                        check(text.length <= 16 * 1024 * 1024) { "Source response too large" }
                        val result = json.parseToJsonElement(text).jsonObject
                        if (result["ok"]?.jsonPrimitive?.booleanOrNull != true) {
                            val code =
                                result["error"]?.jsonPrimitive?.content?.takeIf {
                                    it.matches(Regex("[A-Za-z]{1,60}"))
                                } ?: "UnknownError"
                            val detail =
                                listOf("error_type", "cause_code")
                                    .mapNotNull { key ->
                                        result[key]?.jsonPrimitive?.content?.takeIf {
                                            it.matches(Regex("[A-Za-z_]{1,60}"))
                                        }
                                    }
                                    .joinToString("/")
                            throw SourceFailure(code, detail)
                        }
                        result["result"]!!.jsonObject
                    } catch (e: Exception) {
                        close()
                        currentCoroutineContext().ensureActive()
                        throw e
                    } finally {
                        completed.set(true)
                        cancellationGuard.cancel()
                        timeout.cancel(false)
                    }
                }
            } finally {
                mutex.unlock()
            }
        }

        fun close() {
            process?.destroyForcibly()
            runCatching { writer?.close() }
            process = null
            writer = null
            reader = null
        }
    }

    private val searchWorker = Worker()
    private val audioWorker = Worker()
    private val prefetchWorker = Worker()
    private val rangeWorker = Worker()
    private val backgroundScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val warming = java.util.concurrent.atomic.AtomicBoolean(false)

    private fun warmPlayback() {
        if (!warming.compareAndSet(false, true)) return
        backgroundScope.launch {
            runCatching {
                    audioWorker.execute(buildJsonObject { put("action", "prepare_playback") })
                }
                .onFailure { warming.set(false) }
        }
    }

    private val rangeLock = kotlinx.coroutines.sync.Mutex()
    private var rangeReady = false

    private suspend fun prepareRangeBridge() =
        rangeLock.withLock {
            if (rangeReady && rangeWorker.alive()) return@withLock
            val result = rangeWorker.execute(buildJsonObject { put("action", "range_bridge") })
            transport.useRangeBridge(result["uri"]!!.jsonPrimitive.content)
            rangeReady = true
        }

    internal suspend fun verifyTransport() {
        prepareRangeBridge()
    }

    suspend fun request(body: JsonObject): JsonObject {
        val worker =
            when (body["action"]?.jsonPrimitive?.content) {
                "resolve" -> audioWorker
                else -> searchWorker
            }
        for (attempt in 0..1) try {
            return worker.execute(body)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            val temporary =
                e is java.io.IOException ||
                    (e is SourceFailure &&
                        e.code in
                            setOf(
                                "SourceError",
                                "ConnectionError",
                                "Timeout",
                                "TimeoutError",
                                "ReadTimeout",
                                "ConnectTimeout",
                                "ProxyError",
                            ))
            if (attempt == 1 || !temporary) throw e
            delay(700)
        }
        error("Source retry exhausted")
    }

    override fun close() {
        backgroundScope.cancel()
        if (model.isInitialized()) model.value.close()
        transport.close()
        searchWorker.close()
        audioWorker.close()
        prefetchWorker.close()
        rangeWorker.close()
    }

    override suspend fun search(query: String, limit: Int): List<Track> =
        searchSorted(query, limit, SearchOrder.RELEVANCE)

    override suspend fun searchSorted(query: String, limit: Int, order: SearchOrder): List<Track> {
        val input = query.trim()
        if (input.isEmpty() || limit <= 0) return emptyList()
        require(input.length <= 500)
        warmPlayback()
        if (input.startsWith("http://") || input.startsWith("https://")) {
            val uri = java.net.URI(input)
            require(
                uri.host?.lowercase() in
                    setOf(
                        "youtu.be",
                        "www.youtu.be",
                        "youtube.com",
                        "www.youtube.com",
                        "music.youtube.com",
                        "m.youtube.com",
                    )
            )
            val id =
                if (uri.host!!.endsWith("youtu.be")) uri.path.trim('/')
                else
                    uri.rawQuery
                        .orEmpty()
                        .split('&')
                        .firstOrNull { it.startsWith("v=") }
                        ?.substringAfter('=') ?: uri.path.split('/').last()
            val row =
                request(
                    buildJsonObject {
                        put("action", "metadata")
                        put("id", id)
                    }
                )
            return listOf(
                MusicRules.catalog(row, "")
                    ?: error("Ссылка не ведёт к студийной музыкальной записи")
            )
        }
        val relevance = SearchRelevance(input)
        val text = if (input.all { it in '\u0400'..'\u052f' }) "\"$input\"" else input
        val result =
            request(
                buildJsonObject {
                    put("action", "search")
                    put("query", text)
                    put("limit", maxOf(80, limit * 2).coerceAtMost(180))
                }
            )
        val tracks =
            result["tracks"]
                ?.jsonArray
                .orEmpty()
                .mapNotNull { MusicRules.catalog(it.jsonObject, "") }
                .filter { relevance.score(it) >= 0 }
                .distinctBy { it.id }
                .toMutableList()
        if (relevance.needsUploadFallback(tracks)) {
            val found =
                runCatching {
                        request(
                            buildJsonObject {
                                put("action", "videos")
                                put("query", input)
                            }
                        )
                    }
                    .getOrNull()
            val uploads =
                found
                    ?.get("tracks")
                    ?.jsonArray
                    .orEmpty()
                    .mapNotNull { MusicRules.track(it.jsonObject) }
                    .filter {
                        it.duration in 1..1200 &&
                            !MusicRules.excluded.containsMatchIn(it.title) &&
                            relevance.score(it) >= 0
                    }
                    .take(6)
            for (upload in uploads) {
                val info =
                    runCatching {
                            request(
                                buildJsonObject {
                                    put("action", "metadata")
                                    put("id", upload.id)
                                }
                            )
                        }
                        .getOrNull() ?: continue
                val type = info["musicType"]?.jsonPrimitive?.content.orEmpty()
                val category = info["category"]?.jsonPrimitive?.content.orEmpty()
                val officialAudio =
                    Regex(
                            "\\b(?:official\\s+audio|audio\\s+only|audio|аудио)\\b",
                            RegexOption.IGNORE_CASE,
                        )
                        .containsMatchIn(upload.title)
                if (
                    info["live"]?.jsonPrimitive?.booleanOrNull != true &&
                        (type == "MUSIC_VIDEO_TYPE_ATV" ||
                            (category.equals("Music", true) &&
                                (type == "MUSIC_VIDEO_TYPE_UGC" ||
                                    (type == "MUSIC_VIDEO_TYPE_OMV" && officialAudio))))
                ) {
                    val split = upload.title.split(Regex("\\s+[-–—]\\s+"), 2)
                    val corrected =
                        if (
                            split.size == 2 &&
                                MusicRules.words(split[0]).size <= 5 &&
                                !MusicRules.musicalVersion.containsMatchIn(split[0]) &&
                                relevance.score(upload.copy(title = split[1], artist = split[0])) >=
                                    0
                        )
                            upload.copy(title = split[1], artist = split[0])
                        else upload
                    tracks.add(
                        corrected.copy(viewCount = info["viewCount"]?.jsonPrimitive?.longOrNull)
                    )
                }
            }
        }
        val unique = tracks.distinctBy { it.id }
        if (order == SearchOrder.VIEWS) {
            val known =
                request(
                        buildJsonObject {
                            put("action", "metadata_batch")
                            put("ids", JsonArray(unique.take(80).map { JsonPrimitive(it.id) }))
                        }
                    )["tracks"]
                    ?.jsonArray
                    .orEmpty()
                    .associate { v ->
                        val row = v.jsonObject
                        row["id"]!!.jsonPrimitive.content to
                            row["viewCount"]?.jsonPrimitive?.longOrNull
                    }
            val counted = unique.map { it.copy(viewCount = known[it.id] ?: it.viewCount) }
            if (counted.isNotEmpty() && counted.none { it.viewCount != null })
                error("Не удалось получить просмотры")
            return counted
                .sortedWith(
                    compareByDescending<Track> { it.viewCount != null }
                        .thenByDescending { it.viewCount }
                )
                .take(limit)
        }
        return unique.sortedByDescending { relevance.score(it) }.take(limit)
    }

    override fun invalidate(track: Track) {
        synchronized(streams) { streams.remove(track.id) }
        transport.invalidate(track.id)
    }

    override suspend fun resolve(track: Track): AudioSource {
        withContext(Dispatchers.IO) { transport.cached(track.id) }
            ?.let {
                transport.releaseCurrent()
                return AudioSource(it.toUri().toString())
            }
        prepareRangeBridge()
        val now = Instant.now().epochSecond
        synchronized(streams) {
            streams[track.id]
                ?.takeIf { it.first > now }
                ?.let {
                    return transport.bind(
                        track.id,
                        it.second.copy(proxy = DesktopNetwork.proxyUrl()),
                    )
                }
        }
        val result =
            request(
                buildJsonObject {
                    put("action", "resolve")
                    put("track", json.encodeToJsonElement(track))
                }
            )
        val value =
            AudioSource(
                result["uri"]!!.jsonPrimitive.content,
                result["headers"]
                    ?.jsonObject
                    ?.mapValues { it.value.jsonPrimitive.content }
                    .orEmpty(),
                DesktopNetwork.proxyUrl(),
            )
        synchronized(streams) {
            streams[track.id] = (now + 240) to value
            while (streams.size > 32) streams.remove(streams.keys.first())
        }
        return transport.bind(track.id, value)
    }

    override suspend fun lyrics(track: Track) = lyricsPacket(track).lines

    override suspend fun lyricsPacket(track: Track, force: Boolean) =
        withContext(Dispatchers.IO) { lyricsRepository.load(track, force) }

    override suspend fun enrichLyrics(track: Track, base: LyricsPacket) =
        withContext(Dispatchers.IO) { lyricsRepository.enrich(track, base) }

    override suspend fun importLyrics(track: Track, text: String, format: String) =
        withContext(Dispatchers.IO) { lyricsRepository.import(track, text, format) }

    override suspend fun prefetch(track: Track) {
        if (withContext(Dispatchers.IO) { transport.cached(track.id) } != null) return
        prepareRangeBridge()
        val value =
            prefetchWorker.execute(
                buildJsonObject {
                    put("action", "resolve")
                    put("track", json.encodeToJsonElement(track))
                }
            )
        val stream =
            AudioSource(
                value["uri"]!!.jsonPrimitive.content,
                value["headers"]
                    ?.jsonObject
                    ?.mapValues { it.value.jsonPrimitive.content }
                    .orEmpty(),
                DesktopNetwork.proxyUrl(),
            )
        synchronized(streams) {
            streams[track.id] = (Instant.now().epochSecond + 240) to stream
            while (streams.size > 32) streams.remove(streams.keys.first())
        }
        transport.bind(track.id, stream, current = false)
    }

    override suspend fun alternatives(track: Track): List<RecordingVersion> {
        val base = track.artist + " " + MusicRules.songTitle(track.title, track.artist)
        val found = mutableListOf<Track>()
        val evidence = mutableMapOf<String, String>()
        for (query in
            listOf(base, base + " uncensored", base + " без цензуры", base + " original")) {
            runCatching { searchSorted(query, 36, SearchOrder.RELEVANCE) }
                .getOrNull()
                ?.let(found::addAll)
        }
        val raw =
            runCatching {
                    request(
                        buildJsonObject {
                            put("action", "videos")
                            put("query", base)
                        }
                    )
                }
                .getOrNull()
        val uploads =
            raw?.get("tracks")
                ?.jsonArray
                .orEmpty()
                .mapNotNull { MusicRules.track(it.jsonObject) }
                .filter {
                    it.id != track.id &&
                        !MusicRules.excluded.containsMatchIn(it.artist) &&
                        MusicRules.versionMatches(track, it)
                }
                .take(4)
        for (upload in uploads) {
            val info =
                runCatching {
                        request(
                            buildJsonObject {
                                put("action", "metadata")
                                put("id", upload.id)
                            }
                        )
                    }
                    .getOrNull() ?: continue
            val confirmed = MusicRules.track(info) ?: continue
            if (
                info["available"]?.jsonPrimitive?.booleanOrNull != true ||
                    info["live"]?.jsonPrimitive?.booleanOrNull == true ||
                    info["category"]?.jsonPrimitive?.content !in setOf("Music", "People & Blogs") ||
                    !MusicRules.versionMatches(track, confirmed)
            )
                continue
            val observed = runCatching { StoryboardCheck.inspect(info) }.getOrNull() ?: continue
            found.add(confirmed)
            evidence[confirmed.id] = observed
        }
        return found
            .distinctBy { it.id }
            .filter { it.id != track.id && MusicRules.versionMatches(track, it) }
            .sortedWith(
                compareByDescending<Track> {
                        MusicRules.profile(it.title) == MusicRules.profile(track.title)
                    }
                    .thenBy { kotlin.math.abs(it.duration - track.duration) }
            )
            .take(12)
            .map { candidate ->
                val claim =
                    Regex(
                            "(?:\\(|\\[|[-–—:]\\s*)(?:uncensored|uncut|explicit|без\\s+цензуры)",
                            RegexOption.IGNORE_CASE,
                        )
                        .containsMatchIn(candidate.title)
                val labels =
                    MusicRules.profile(candidate.title) +
                        (if (claim) listOf("«Без цензуры» — заявлено") else emptyList())
                val note =
                    "Совпадают название и исполнитель; длительность ${candidate.duration} с (разница ${kotlin.math.abs(candidate.duration-track.duration)} с). " +
                        evidence[candidate.id].orEmpty() +
                        " Содержание и отсутствие цензуры не проверены."
                val title = MusicRules.songTitle(candidate.title, track.artist)
                RecordingVersion(
                    candidate.copy(title = title, artist = track.artist),
                    labels.joinToString(" · ").ifBlank { "Другая загрузка" },
                    note,
                )
            }
    }

    override suspend fun recommend(seeds: List<Track>, excluded: List<Track>): List<Suggestion> =
        withContext(Dispatchers.IO) { model.value.recommend(seeds, excluded) }

    companion object {
        private val watchdog =
            java.util.concurrent.Executors.newSingleThreadScheduledExecutor { task ->
                Thread(task, "riffuna-source-timeout").apply { isDaemon = true }
            }
    }

    override suspend fun resolveSuggestion(suggestion: Suggestion): Track {
        return searchSorted(suggestion.artist + " " + suggestion.title, 12, SearchOrder.RELEVANCE)
            .filter {
                MusicRules.artist(it.artist) == MusicRules.artist(suggestion.artist) &&
                    MusicRules.profile(it.title) == MusicRules.profile(suggestion.title) &&
                    TextMatch.ratio(
                        MusicRules.normal(MusicRules.songTitle(it.title, it.artist)),
                        MusicRules.normal(suggestion.title),
                    ) >= .9
            }
            .maxByOrNull { MusicRules.score(suggestion.title, it.title, it.artist) }
            ?: error("Подходящая музыкальная запись не найдена")
    }
}
