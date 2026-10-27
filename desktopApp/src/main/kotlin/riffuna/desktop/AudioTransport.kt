package riffuna.desktop

import com.sun.net.httpserver.HttpExchange
import com.sun.net.httpserver.HttpServer
import java.io.ByteArrayOutputStream
import java.net.*
import java.net.http.*
import java.nio.ByteBuffer
import java.nio.file.*
import java.security.MessageDigest
import java.time.Duration
import java.util.UUID
import java.util.concurrent.*
import kotlinx.serialization.json.*
import riffuna.core.AudioSource

/** Local mpv transport. Remote URLs never leave this process or appear in logs. */
class AudioTransport(private val directory: Path) : AutoCloseable {
    private val io =
        Executors.newCachedThreadPool { r ->
            Thread(r, "riffuna-audio-http").apply { isDaemon = true }
        }
    private val server =
        HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0).apply {
            executor = io
            createContext("/") { exchange -> serve(exchange) }
            start()
        }
    private val clients = ConcurrentHashMap<String, HttpClient>()

    private fun client(proxy: String) =
        clients.computeIfAbsent(proxy) { value ->
            val selector =
                if (value.isBlank()) HttpClient.Builder.NO_PROXY
                else
                    URI(value).let {
                        ProxySelector.of(
                            InetSocketAddress(it.host, if (it.port > 0) it.port else 80)
                        )
                    }
            HttpClient.newBuilder()
                .proxy(selector)
                .executor(io)
                .connectTimeout(Duration.ofSeconds(5))
                .followRedirects(HttpClient.Redirect.NORMAL)
                .version(HttpClient.Version.HTTP_1_1)
                .build()
        }

    private class BoundedBody(private val limit: Int) : HttpResponse.BodySubscriber<ByteArray> {
        private val result = CompletableFuture<ByteArray>()
        private val output = ByteArrayOutputStream()
        private var subscription: Flow.Subscription? = null

        override fun getBody(): CompletionStage<ByteArray> = result

        override fun onSubscribe(value: Flow.Subscription) {
            if (subscription != null) {
                value.cancel()
                return
            }
            subscription = value
            value.request(Long.MAX_VALUE)
        }

        override fun onNext(items: List<ByteBuffer>) {
            if (result.isDone) return
            try {
                for (item in items) {
                    check(output.size().toLong() + item.remaining() <= limit) {
                        "Audio response too large"
                    }
                    val bytes = ByteArray(item.remaining())
                    item.get(bytes)
                    output.write(bytes)
                }
            } catch (error: Exception) {
                subscription?.cancel()
                result.completeExceptionally(error)
            }
        }

        override fun onError(error: Throwable) {
            result.completeExceptionally(error)
        }

        override fun onComplete() {
            result.complete(output.toByteArray())
        }
    }

    private val bindings = linkedMapOf<String, Buffer>()
    private val verifiedCache = VerifiedAudioCache()
    private var activeToken: String? = null
    @Volatile private var rangeBridge = ""

    fun useRangeBridge(value: String) {
        val uri = URI(value)
        require(
            uri.scheme == "http" && uri.host == "127.0.0.1" && uri.port > 0 && uri.path.length > 30
        )
        rangeBridge = value
    }

    private val blockSize = 128 * 1024
    private val memoryLimit = 24L * 1024 * 1024
    private val diskLimit = 1024L * 1024 * 1024
    @Volatile private var closed = false

    private fun key(id: String) =
        MessageDigest.getInstance("SHA-256").digest(id.toByteArray(Charsets.UTF_8)).joinToString(
            ""
        ) {
            "%02x".format(it)
        }

    fun cached(id: String): Path? =
        runCatching {
                val name = key(id)
                val info =
                    Json.parseToJsonElement(Files.readString(directory.resolve("$name.json")))
                        .jsonObject
                val extension = info["extension"]!!.jsonPrimitive.content
                check(extension in setOf(".m4a", ".webm", ".mp3", ".ogg", ".flac"))
                val path = directory.resolve(name + extension)
                val size = Files.size(path)
                check(size in 1..diskLimit && size == info["size"]!!.jsonPrimitive.long)
                check(verifiedCache.verify(path, size, info["sha256"]!!.jsonPrimitive.content))
                path
            }
            .getOrNull()

    @Synchronized
    fun releaseCurrent() {
        activeToken = null
    }

    @Synchronized
    fun invalidate(id: String) {
        val keys = bindings.filterValues { it.id == id }.keys.toList()
        keys.forEach { key ->
            bindings.remove(key)?.cancel()
            if (activeToken == key) activeToken = null
        }
    }

    @Synchronized
    fun bind(id: String, source: AudioSource, current: Boolean = true): AudioSource {
        check(!closed)
        val uri = URI(source.uri)
        require(uri.scheme == "https" || (uri.scheme == "http" && uri.host == "127.0.0.1"))
        bindings.entries
            .firstOrNull { it.value.id == id && it.value.source == source }
            ?.let {
                if (current) activeToken = it.key
                return local(it.key)
            }
        val token = "/" + UUID.randomUUID().toString()
        val buffer = Buffer(id, source)
        bindings[token] = buffer
        if (current) activeToken = token
        while (bindings.size > 3) {
            val oldest = bindings.keys.first { it != activeToken }
            bindings.remove(oldest)?.cancel()
        }
        io.submit {
            runCatching {
                buffer.block(0)
                if (buffer.total <= memoryLimit) {
                    for (index in 1..((buffer.total - 1) / blockSize).toInt()) {
                        if (buffer.cancelled || closed) break
                        buffer.block(index)
                    }
                    buffer.persist()
                } else if (buffer.total <= diskLimit) buffer.persistStreaming()
            }
        }
        return local(token)
    }

    private fun local(path: String) = AudioSource("http://127.0.0.1:${server.address.port}$path")

    private inner class Buffer(val id: String, val source: AudioSource) {
        @Volatile var total = 0L
        @Volatile var type = "audio/mp4"
        @Volatile
        var cancelled = false
            private set

        private val requests = ConcurrentHashMap.newKeySet<CompletableFuture<*>>()

        fun cancel() {
            cancelled = true
            requests.forEach { it.cancel(true) }
        }

        private val blocks = ConcurrentHashMap<Int, CompletableFuture<ByteArray>>()

        fun block(index: Int): ByteArray {
            check(!cancelled && !closed)
            val future = CompletableFuture<ByteArray>()
            val previous = blocks.putIfAbsent(index, future)
            if (previous != null) return previous.get(15, TimeUnit.SECONDS)
            try {
                val start = index.toLong() * blockSize
                val end =
                    if (total > 0) minOf(total - 1, start + blockSize - 1)
                    else start + blockSize - 1
                check(end >= start)
                val bridge = rangeBridge
                val builder =
                    HttpRequest.newBuilder(URI(bridge.ifBlank { source.uri }))
                        .timeout(Duration.ofSeconds(8))
                if (bridge.isBlank()) {
                    val replaced =
                        setOf(
                            "range",
                            "accept-encoding",
                            "connection",
                            "content-length",
                            "host",
                            "expect",
                            "upgrade",
                        )
                    source.headers
                        .filterKeys { it.lowercase() !in replaced }
                        .forEach { (key, value) -> builder.header(key, value) }
                    builder
                        .header("Accept-Encoding", "identity")
                        .header("Range", "bytes=$start-$end")
                        .GET()
                } else {
                    val payload = buildJsonObject {
                        put("uri", source.uri)
                        put("range", "bytes=$start-$end")
                        put("proxy", source.proxy)
                        put(
                            "headers",
                            JsonObject(source.headers.mapValues { JsonPrimitive(it.value) }),
                        )
                    }
                    builder
                        .header("Content-Type", "application/json")
                        .POST(HttpRequest.BodyPublishers.ofString(payload.toString()))
                }
                val pending =
                    client(if (bridge.isBlank()) source.proxy else "")
                        .sendAsync(
                            builder.build(),
                            HttpResponse.BodyHandler<ByteArray> { info ->
                                val limit =
                                    if (info.statusCode() == 200) memoryLimit.toInt() else blockSize
                                check(
                                    info.headers().firstValueAsLong("Content-Length").orElse(0) <=
                                        limit
                                ) {
                                    "Audio response too large"
                                }
                                BoundedBody(limit)
                            },
                        )
                requests.add(pending)
                val bytes =
                    try {
                        check(!cancelled && !closed)
                        val response = pending.get(10, TimeUnit.SECONDS)
                        val status = response.statusCode()
                        if (status == 206) {
                            val match =
                                Regex("bytes (\\d+)-(\\d+)/(\\d+)")
                                    .matchEntire(
                                        response.headers().firstValue("Content-Range").orElse("")
                                    ) ?: error("Invalid audio range")
                            val size = match.groupValues[3].toLong()
                            check(
                                match.groupValues[1].toLong() == start &&
                                    match.groupValues[2].toLong() == minOf(end, size - 1)
                            )
                            check(total == 0L || total == size)
                            total = size
                        } else {
                            check(status == 200 && start == 0L)
                            total = response.headers().firstValueAsLong("Content-Length").orElse(-1)
                            check(total in 1..memoryLimit)
                        }
                        type =
                            response
                                .headers()
                                .firstValue("Content-Type")
                                .orElse("audio/mp4")
                                .substringBefore(';')
                        val expected =
                            if (status == 200) total.toInt()
                            else minOf(blockSize.toLong(), total - start).toInt()
                        val payload = response.body()
                        check(payload.size == expected) { "Incomplete audio range" }
                        if (status == 200 && payload.size > blockSize) {
                            var at = blockSize
                            var blockIndex = 1
                            while (at < payload.size) {
                                blocks.putIfAbsent(
                                    blockIndex++,
                                    CompletableFuture.completedFuture(
                                        payload.copyOfRange(at, minOf(at + blockSize, payload.size))
                                    ),
                                )
                                at += blockSize
                            }
                            payload.copyOfRange(0, blockSize)
                        } else payload
                    } finally {
                        requests.remove(pending)
                        if (!pending.isDone) pending.cancel(true)
                    }
                future.complete(bytes)
                // Large files are served on demand, without keeping their full body in RAM.
                if (total > memoryLimit && index > 0) blocks.remove(index, future)
                return bytes
            } catch (e: Exception) {
                future.completeExceptionally(e)
                blocks.remove(index, future)
                throw e
            }
        }

        @Synchronized
        fun persist() {
            if (cancelled || closed || total <= 0 || total > memoryLimit) return
            val count = ((total - 1) / blockSize + 1).toInt()
            if (
                (0 until count).any {
                    blocks[it]?.isDone != true || blocks[it]?.isCompletedExceptionally == true
                }
            )
                return
            val data = ByteArray(total.toInt())
            var offset = 0
            for (index in 0 until count) {
                val bytes = blocks[index]!!.get()
                bytes.copyInto(data, offset)
                offset += bytes.size
            }
            if (offset != data.size) return
            store { out ->
                out.write(data)
                data.size.toLong()
            }
        }

        @Synchronized
        fun persistStreaming() {
            if (cancelled || closed || total <= memoryLimit || total > diskLimit) return
            store { out ->
                var written = 0L
                for (index in 0..((total - 1) / blockSize).toInt()) {
                    check(!cancelled && !closed)
                    val bytes = block(index)
                    out.write(bytes)
                    written += bytes.size
                }
                written
            }
        }

        private fun store(write: (java.io.OutputStream) -> Long) {
            Files.createDirectories(directory)
            val extension =
                when {
                    "webm" in type -> ".webm"
                    "mpeg" in type -> ".mp3"
                    "ogg" in type -> ".ogg"
                    "flac" in type -> ".flac"
                    else -> ".m4a"
                }
            val name = key(id)
            val temporary = directory.resolve("$name.${UUID.randomUUID()}.part")
            try {
                val checksum = MessageDigest.getInstance("SHA-256")
                val written =
                    java.security
                        .DigestOutputStream(Files.newOutputStream(temporary), checksum)
                        .use(write)
                check(!cancelled && !closed && written == total)
                Files.move(
                    temporary,
                    directory.resolve(name + extension),
                    StandardCopyOption.REPLACE_EXISTING,
                )
                val hash = checksum.digest().joinToString("") { "%02x".format(it) }
                val metadata = buildJsonObject {
                    put("size", written)
                    put("sha256", hash)
                    put("extension", extension)
                    put("content_type", type)
                }
                Files.writeString(temporary, metadata.toString())
                Files.move(
                    temporary,
                    directory.resolve("$name.json"),
                    StandardCopyOption.REPLACE_EXISTING,
                )
                trim()
            } finally {
                Files.deleteIfExists(temporary)
            }
        }
    }

    @Synchronized
    private fun trim() {
        val files =
            Files.list(directory)
                .use { stream ->
                    stream
                        .filter {
                            it.fileName.toString().substringAfterLast('.', "") in
                                setOf("m4a", "webm", "mp3", "ogg", "flac")
                        }
                        .toList()
                }
                .sortedBy { Files.getLastModifiedTime(it).toMillis() }
        var size = files.sumOf { Files.size(it) }
        for (file in files) {
            if (size <= diskLimit) break
            val bytes = Files.size(file)
            Files.deleteIfExists(file)
            Files.deleteIfExists(
                file.resolveSibling(file.fileName.toString().substringBeforeLast('.') + ".json")
            )
            size -= bytes
        }
    }

    private fun serve(exchange: HttpExchange) {
        try {
            val buffer = synchronized(this) { bindings[exchange.requestURI.rawPath] }
            if (
                buffer == null ||
                    buffer.cancelled ||
                    exchange.requestMethod !in setOf("GET", "HEAD")
            ) {
                exchange.sendResponseHeaders(404, -1)
                return
            }
            buffer.block(0)
            val range = exchange.requestHeaders.getFirst("Range")
            val bounds = byteRange(range, buffer.total)
            if (range != null && bounds == null) {
                exchange.responseHeaders.set("Content-Range", "bytes */${buffer.total}")
                exchange.sendResponseHeaders(416, -1)
                return
            }
            val (start, end) = bounds ?: Pair(0L, buffer.total - 1)
            if (start >= buffer.total || end < start) {
                exchange.responseHeaders.set("Content-Range", "bytes */${buffer.total}")
                exchange.sendResponseHeaders(416, -1)
                return
            }
            exchange.responseHeaders.set("Content-Type", buffer.type)
            exchange.responseHeaders.set("Accept-Ranges", "bytes")
            exchange.responseHeaders.set("Cache-Control", "no-store")
            exchange.responseHeaders.set("Content-Length", (end - start + 1).toString())
            if (bounds != null)
                exchange.responseHeaders.set("Content-Range", "bytes $start-$end/${buffer.total}")
            exchange.sendResponseHeaders(
                if (bounds == null) 200 else 206,
                if (exchange.requestMethod == "HEAD") -1 else end - start + 1,
            )
            if (exchange.requestMethod != "HEAD")
                exchange.responseBody.use { out ->
                    var position = start
                    while (position <= end && !buffer.cancelled && !closed) {
                        val index = (position / blockSize).toInt()
                        val block = buffer.block(index)
                        val within = (position % blockSize).toInt()
                        val length =
                            minOf(
                                block.size - within,
                                (end - position + 1).coerceAtMost(Int.MAX_VALUE.toLong()).toInt(),
                            )
                        check(length > 0)
                        out.write(block, within, length)
                        position += length
                    }
                }
        } catch (_: Exception) {
            runCatching { exchange.sendResponseHeaders(502, -1) }
        } finally {
            exchange.close()
        }
    }

    override fun close() {
        synchronized(this) {
            if (closed) return
            closed = true
            bindings.values.forEach { it.cancel() }
            bindings.clear()
            activeToken = null
        }
        server.stop(0)
        clients.values.forEach { it.shutdownNow() }
        clients.clear()
        io.shutdownNow()
    }

    companion object {
        fun byteRange(value: String?, total: Long): Pair<Long, Long>? {
            val match =
                Regex("bytes=(\\d*)-(\\d*)").matchEntire(value ?: return null) ?: return null
            return runCatching {
                    val left = match.groupValues[1]
                    val right = match.groupValues[2]
                    require(left.isNotEmpty() || right.isNotEmpty())
                    if (left.isEmpty()) {
                        val length = right.toLong()
                        require(length > 0)
                        Pair(maxOf(0, total - length), total - 1)
                    } else
                        Pair(
                            left.toLong(),
                            if (right.isEmpty()) total - 1 else minOf(total - 1, right.toLong()),
                        )
                }
                .getOrNull()
        }
    }
}
