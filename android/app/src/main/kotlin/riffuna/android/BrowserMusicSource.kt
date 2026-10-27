package riffuna.android

import android.annotation.SuppressLint
import android.content.Context
import android.net.Uri
import android.util.Base64
import android.webkit.*
import androidx.webkit.WebViewAssetLoader
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicInteger
import kotlinx.coroutines.*
import kotlinx.serialization.json.*
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import riffuna.core.*

/**
 * Executes bundled JS, never remote pages. The native bridge cannot access files or arbitrary
 * hosts.
 */
@SuppressLint("SetJavaScriptEnabled")
class BrowserMusicSource(
    private val context: Context,
    private val http: OkHttpClient,
    private val library: AndroidLibrary,
) : MusicSource {
    private val ready = CompletableDeferred<Unit>()
    private val requests = ConcurrentHashMap<Int, CompletableDeferred<JsonObject>>()
    private val ids = AtomicInteger()
    private val web = WebView(context)
    private val loader =
        WebViewAssetLoader.Builder()
            .setDomain("www.youtube.com")
            .addPathHandler("/assets/", WebViewAssetLoader.AssetsPathHandler(context))
            .build()

    init {
        web.settings.javaScriptEnabled = true
        web.settings.userAgentString =
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36(KHTML, like Gecko)"
        web.settings.allowFileAccess = false
        web.settings.allowContentAccess = false
        web.settings.domStorageEnabled = false
        web.settings.mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
        web.addJavascriptInterface(Bridge(), "Native")
        web.webChromeClient =
            object : WebChromeClient() {
                override fun onConsoleMessage(message: ConsoleMessage): Boolean {
                    if (
                        message.messageLevel() == ConsoleMessage.MessageLevel.ERROR &&
                            !ready.isCompleted
                    )
                        ready.completeExceptionally(
                            IllegalStateException("Не удалось запустить встроенный JS-движок")
                        )
                    return true
                }
            }
        web.webViewClient =
            object : WebViewClient() {
                override fun shouldInterceptRequest(
                    view: WebView,
                    request: WebResourceRequest,
                ): WebResourceResponse =
                    loader.shouldInterceptRequest(request.url)
                        ?: WebResourceResponse(
                            "text/plain",
                            "utf-8",
                            403,
                            "Blocked",
                            emptyMap(),
                            java.io.ByteArrayInputStream(byteArrayOf()),
                        )

                override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest) =
                    request.url.toString() != "about:blank"

                override fun onRenderProcessGone(
                    view: WebView,
                    detail: RenderProcessGoneDetail,
                ): Boolean {
                    val error =
                        IllegalStateException("JS-движок остановлен. Перезапусти приложение")
                    ready.completeExceptionally(error)
                    requests.values.forEach { it.completeExceptionally(error) }
                    return true
                }
            }
        web.loadUrl("https://www.youtube.com/assets/source/index.html")
    }

    inner class Bridge {
        @JavascriptInterface
        fun issue(action: String, type: String) {
            android.util.Log.w(
                "RiffunaSource",
                "JS action=" +
                    action.take(16).replace(Regex("[^a-z]"), "") +
                    " type=" +
                    type.take(50).replace(Regex("[^A-Za-z]"), ""),
            )
        }

        @JavascriptInterface
        fun ready() {
            ready.complete(Unit)
        }

        @JavascriptInterface
        fun complete(id: Int, response: String) {
            runCatching { Json.parseToJsonElement(response).jsonObject }
                .fold({ requests[id]?.complete(it) }, { requests[id]?.completeExceptionally(it) })
        }

        @JavascriptInterface
        fun http(payload: String): String =
            try {
                require(payload.length <= 262144)
                val row = Json.parseToJsonElement(payload).jsonObject
                val uri = Uri.parse(row.getValue("url").jsonPrimitive.content)
                require(SourceTransportPolicy.allowed(uri.toString()))
                val method = row.getValue("method").jsonPrimitive.content
                require(method in setOf("GET", "HEAD", "POST"))
                val builder = Request.Builder().url(uri.toString())
                row["headers"]?.jsonObject?.forEach { (key, value) ->
                    if (
                        key.lowercase() !in
                            setOf("host", "cookie", "authorization", "connection", "content-length")
                    )
                        builder.header(key, value.jsonPrimitive.content)
                }
                val body = row["body"]?.jsonPrimitive?.content.orEmpty()
                builder.method(
                    method,
                    if (method == "POST")
                        body.toRequestBody(
                            (row["headers"]
                                    ?.jsonObject
                                    ?.entries
                                    ?.firstOrNull { it.key.equals("Content-Type", true) }
                                    ?.value
                                    ?.jsonPrimitive
                                    ?.content ?: "application/json")
                                .toMediaType()
                        )
                    else null,
                )
                http.newCall(builder.build()).execute().use { response ->
                    android.util.Log.i(
                        "RiffunaSource",
                        "HTTPS status=" +
                            response.code +
                            " kind=" +
                            (if (uri.host.orEmpty().endsWith(".googlevideo.com")) "audio"
                            else if (uri.path.orEmpty().endsWith("base.js")) "player" else "api"),
                    )
                    val bytes =
                        response.body?.byteStream()?.use { stream ->
                            val output = java.io.ByteArrayOutputStream()
                            val buffer = ByteArray(16384)
                            while (true) {
                                val count = stream.read(buffer)
                                if (count < 0) break
                                require(output.size() + count <= 12 * 1024 * 1024)
                                output.write(buffer, 0, count)
                            }
                            output.toByteArray()
                        } ?: byteArrayOf()
                    buildJsonObject {
                            put("status", response.code)
                            put("body", Base64.encodeToString(bytes, Base64.NO_WRAP))
                            put(
                                "headers",
                                buildJsonObject {
                                    response.headers
                                        .names()
                                        .filter {
                                            it.lowercase() !in
                                                setOf(
                                                    "content-encoding",
                                                    "content-length",
                                                    "set-cookie",
                                                )
                                        }
                                        .forEach { put(it, response.header(it).orEmpty()) }
                                },
                            )
                        }
                        .toString()
                }
            } catch (error: Exception) {
                android.util.Log.w("RiffunaSource", "HTTPS failure=" + error.javaClass.simpleName)
                "{\"error\":true}"
            }
    }

    private suspend fun request(action: String, values: Map<String, JsonElement>): JsonObject =
        withTimeout(120000) {
            ready.await()
            val id = ids.incrementAndGet()
            val result = CompletableDeferred<JsonObject>()
            requests[id] = result
            try {
                val payload = JsonObject(values + ("action" to JsonPrimitive(action)))
                withContext(Dispatchers.Main) {
                    web.evaluateJavascript("globalThis.riffunaRequest($id,$payload)", null)
                }
                val response = result.await()
                check(response["ok"]?.jsonPrimitive?.booleanOrNull == true) {
                    "Источник временно недоступен. Проверь VPN и повтори попытку"
                }
                response.getValue("data").jsonObject
            } finally {
                requests.remove(id)
            }
        }

    override suspend fun search(query: String, limit: Int): List<Track> {
        val rows =
            request(
                    "search",
                    mapOf("query" to JsonPrimitive(query), "limit" to JsonPrimitive(limit)),
                )["tracks"]
                ?.jsonArray
                .orEmpty()
        return rows
            .map { value ->
                val r = value.jsonObject
                Track(
                    r.getValue("id").jsonPrimitive.content,
                    r.getValue("title").jsonPrimitive.content,
                    r["artist"]?.jsonPrimitive?.content ?: "YouTube",
                    r["duration"]?.jsonPrimitive?.intOrNull ?: 0,
                    r["thumbnail"]?.jsonPrimitive?.content.orEmpty(),
                )
            }
            .filter {
                !Regex(
                        "(?:\\(|\\[|[-–—]\\s*)(?:live|концерт|клип|reaction|разбор|1 час)\\b",
                        RegexOption.IGNORE_CASE,
                    )
                    .containsMatchIn(it.title)
            }
            .distinctBy { it.id }
    }

    private val resolved = ConcurrentHashMap<String, Pair<Long, AudioSource>>()

    override fun invalidate(track: Track) {
        resolved.remove(track.id)
    }

    override suspend fun prefetch(track: Track) {
        if (!track.isLocalFile) resolve(track)
    }

    override suspend fun resolve(track: Track): AudioSource {
        if (track.isLocalFile)
            return AudioSource(
                library.setting("local-uri:" + track.id, "").ifBlank {
                    error("Локальный файл недоступен")
                }
            )
        val now = System.currentTimeMillis()
        resolved[track.id]
            ?.takeIf { it.first > now }
            ?.let {
                return it.second
            }
        val r = request("resolve", mapOf("id" to JsonPrimitive(track.id)))
        val audio =
            AudioSource(
                r.getValue("uri").jsonPrimitive.content,
                r["headers"]?.jsonObject.orEmpty().mapValues { it.value.jsonPrimitive.content },
            )
        require(SourceTransportPolicy.allowed(audio.uri, audioOnly = true))
        val expiry =
            Uri.parse(audio.uri)
                .getQueryParameter("expire")
                ?.toLongOrNull()
                ?.times(1000)
                ?.minus(60000) ?: now + 300000
        resolved[track.id] = minOf(expiry, now + 900000) to audio
        if (resolved.size > 32)
            resolved.keys.firstOrNull { it != track.id }?.let { resolved.remove(it) }
        return audio
    }

    private val lyrics = AndroidLyrics(http, library)

    override suspend fun lyricsPacket(track: Track, force: Boolean) = lyrics.load(track, force)

    override suspend fun localTracks(): List<Track> =
        runCatching { Json.decodeFromString<List<Track>>(library.setting("local-files", "[]")) }
            .getOrDefault(emptyList())

    override suspend fun importLocalFiles(paths: List<String>): LocalImportResult {
        val existing = localTracks().associateBy { it.id }.toMutableMap()
        var added = 0
        var updated = 0
        var skipped = 0
        for (path in paths) {
            currentCoroutineContext().ensureActive()
            try {
                val uri = Uri.parse(path)
                require(uri.scheme == "content")
                val id =
                    "local-" +
                        java.security.MessageDigest.getInstance("SHA-256")
                            .digest(path.toByteArray())
                            .joinToString("") { "%02x".format(it) }
                val metadata = android.media.MediaMetadataRetriever()
                val track =
                    try {
                        metadata.setDataSource(context, uri)
                        val name =
                            context.contentResolver
                                .query(
                                    uri,
                                    arrayOf(android.provider.OpenableColumns.DISPLAY_NAME),
                                    null,
                                    null,
                                    null,
                                )
                                ?.use { if (it.moveToFirst()) it.getString(0) else null }
                                ?: "Аудиозапись"
                        Track(
                            id,
                            metadata.extractMetadata(
                                android.media.MediaMetadataRetriever.METADATA_KEY_TITLE
                            ) ?: name.substringBeforeLast('.'),
                            metadata.extractMetadata(
                                android.media.MediaMetadataRetriever.METADATA_KEY_ARTIST
                            ) ?: "Неизвестный исполнитель",
                            ((metadata
                                    .extractMetadata(
                                        android.media.MediaMetadataRetriever.METADATA_KEY_DURATION
                                    )
                                    ?.toLongOrNull() ?: 0) / 1000)
                                .toInt(),
                        )
                    } finally {
                        metadata.release()
                    }
                if (existing.put(id, track) == null) added++ else updated++
                library.setSetting("local-uri:" + id, path)
            } catch (e: CancellationException) {
                throw e
            } catch (_: Exception) {
                skipped++
            }
        }
        library.setSetting(
            "local-files",
            Json.encodeToString(
                kotlinx.serialization.builtins.ListSerializer(Track.serializer()),
                existing.values.toList(),
            ),
        )
        return LocalImportResult(added, updated, skipped)
    }

    override fun close() {
        requests.values.forEach { it.cancel() }
        requests.clear()
        web.removeJavascriptInterface("Native")
        web.destroy()
    }
}
