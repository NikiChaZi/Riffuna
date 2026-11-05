package riffuna.android

import java.text.Normalizer
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.withContext
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.*
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.OkHttpClient
import okhttp3.Request
import riffuna.core.*

internal class AndroidLyrics(private val http: OkHttpClient, private val library: AndroidLibrary) {
    companion object {
        internal fun normalized(value: String): String =
            Normalizer.normalize(value, Normalizer.Form.NFKC)
                .lowercase(java.util.Locale.ROOT)
                .replace(Regex("[^\\p{L}\\p{N}]+"), " ")
                .trim()

        internal fun matches(row: JsonObject, track: Track): Boolean =
            normalized(row["trackName"]?.jsonPrimitive?.content.orEmpty()) ==
                normalized(AndroidRecordingRules.songTitle(track.title, track.artist)) &&
                normalized(row["artistName"]?.jsonPrimitive?.content.orEmpty()) ==
                    normalized(track.artist) &&
                track.duration > 0 &&
                kotlin.math.abs(
                    (row["duration"]?.jsonPrimitive?.doubleOrNull ?: -1000.0) - track.duration
                ) <= 2.0

        internal fun packet(row: JsonObject): LyricsPacket {
            if (row["instrumental"]?.jsonPrimitive?.booleanOrNull == true)
                return LyricsPacket(
                    state = "instrumental",
                    source = "LRCLIB",
                    message = "Инструментальная запись",
                )
            val synced =
                row["syncedLyrics"]?.takeIf { it != JsonNull }?.jsonPrimitive?.content.orEmpty()
            val lines = runCatching { LyricTiming.parseLrc(synced) }.getOrDefault(emptyList())
            val plain =
                row["plainLyrics"]?.takeIf { it != JsonNull }?.jsonPrimitive?.content.orEmpty()
            return LyricsPacket(
                state =
                    if (lines.isNotEmpty()) "synced"
                    else if (plain.isNotBlank()) "plain" else "not_found",
                lines = lines,
                plainText = plain,
                source = "LRCLIB",
                sourceUrl = "https://lrclib.net",
                timingSource = if (lines.isNotEmpty()) "provider_lrc" else "none",
                approximateWords = lines.none { it.words.isNotEmpty() },
            )
        }

        internal fun compatible(track: Track, base: LyricsPacket, lines: List<LyricLine>): Boolean {
            if (lines.isEmpty() || lines.none { it.words.isNotEmpty() } || track.duration <= 0)
                return false
            val expected =
                normalized(base.plainText.ifBlank { base.lines.joinToString(" ") { it.text } })
            val actual = normalized(lines.joinToString(" ") { it.text })
            if (
                expected.isBlank() ||
                    expected.length > 8000 ||
                    actual.length > 8000 ||
                    TextMatch.ratio(expected, actual) < .94
            )
                return false
            val words = lines.flatMap { it.words }
            if (
                words.any {
                    it.startMs < 0 ||
                        it.endMs <= it.startMs ||
                        it.endMs > track.duration * 1000L + 2000
                }
            )
                return false
            val starts = base.lines.associate { normalized(it.text) to it.startMs }
            val differences =
                lines.mapNotNull { line ->
                    starts[normalized(line.text)]?.let { kotlin.math.abs(it - line.startMs) }
                }
            return differences.size >= minOf(2, lines.size) &&
                differences.count { it <= 2200 }.toDouble() / differences.size >= .85
        }
    }

    suspend fun load(track: Track, force: Boolean): LyricsPacket =
        withContext(Dispatchers.IO) {
            val key = cacheKey(track)
            if (!force)
                runCatching { Json.decodeFromString<LyricsPacket>(library.setting(key, "")) }
                    .getOrNull()
                    ?.let {
                        return@withContext it
                    }
            try {
                val exact =
                    "https://lrclib.net/api/get"
                        .toHttpUrl()
                        .newBuilder()
                        .addQueryParameter(
                            "track_name",
                            AndroidRecordingRules.songTitle(track.title, track.artist),
                        )
                        .addQueryParameter("artist_name", track.artist)
                        .addQueryParameter("duration", track.duration.toString())
                        .build()
                var row = fetch(exact)?.jsonObject?.takeIf { matches(it, track) }
                if (row == null) {
                    val search =
                        "https://lrclib.net/api/search"
                            .toHttpUrl()
                            .newBuilder()
                            .addQueryParameter(
                                "track_name",
                                AndroidRecordingRules.songTitle(track.title, track.artist),
                            )
                            .addQueryParameter("artist_name", track.artist)
                            .build()
                    row =
                        fetch(search)
                            ?.jsonArray
                            ?.map { it.jsonObject }
                            ?.firstOrNull { matches(it, track) }
                }
                val packet =
                    row?.let(::packet)
                        ?: LyricsPacket(message = "Подходящий текст для этой записи не найден")
                if (packet.state != "not_found")
                    library.setSetting(key, Json.encodeToString(packet))
                packet
            } catch (e: CancellationException) {
                throw e
            } catch (_: Exception) {
                LyricsPacket(
                    message = "Не удалось загрузить текст. Проверь соединение и повтори поиск"
                )
            }
        }

    private fun fetch(url: okhttp3.HttpUrl): JsonElement? =
        http
            .newCall(
                Request.Builder()
                    .url(url)
                    .header("User-Agent", "Riffuna/Android (personal music player)")
                    .build()
            )
            .execute()
            .use { r ->
                if (r.code == 404) return@use null
                check(r.isSuccessful)
                val text =
                    r.body?.byteStream()?.use { stream ->
                        val out = java.io.ByteArrayOutputStream()
                        val buffer = ByteArray(8192)
                        while (out.size() <= 1048576) {
                            val n = stream.read(buffer)
                            if (n < 0) break
                            out.write(buffer, 0, n)
                        }
                        out.toByteArray()
                    } ?: byteArrayOf()
                require(text.size <= 1048576)
                Json.parseToJsonElement(text.toString(Charsets.UTF_8))
            }

    private fun cacheKey(track: Track): String =
        "lyrics:v2:${track.id}:${normalized(track.artist)}:${normalized(track.title)}:${track.duration}"

    suspend fun enrich(track: Track, base: LyricsPacket): LyricsPacket =
        withContext(Dispatchers.IO) {
            if (
                base.state != "synced" ||
                    base.lines.any { it.words.isNotEmpty() } ||
                    base.source == "local" ||
                    AndroidRecordingRules.profile(track.title).isNotEmpty()
            )
                return@withContext base
            val key = cacheKey(track) + ":words"
            runCatching { Json.decodeFromString<LyricsPacket>(library.setting(key, "")) }
                .getOrNull()
                ?.let { if (compatible(track, base, it.lines)) return@withContext it }
            for ((endpoint, field) in listOf("/getLyrics" to "ttml", "/qq/getLyrics" to "lyrics")) {
                currentCoroutineContext().ensureActive()
                try {
                    val url =
                        ("https://api.betterlyrics.org" + endpoint)
                            .toHttpUrl()
                            .newBuilder()
                            .addQueryParameter(
                                "s",
                                AndroidRecordingRules.songTitle(track.title, track.artist),
                            )
                            .addQueryParameter("a", track.artist)
                            .addQueryParameter("d", track.duration.toString())
                            .build()
                    val row = fetch(url)?.jsonObject ?: continue
                    if ((row["score"]?.jsonPrimitive?.doubleOrNull ?: 1.0) < .9) continue
                    val text = row[field]?.jsonPrimitive?.contentOrNull ?: continue
                    val lines =
                        if (field == "ttml") AndroidLyricWords.parseTtml(text)
                        else AndroidLyricWords.parseQrc(text)
                    if (compatible(track, base, lines)) {
                        val enriched =
                            base.copy(
                                lines = lines,
                                timingSource = "provider_words",
                                approximateWords = false,
                            )
                        library.setSetting(key, Json.encodeToString(enriched))
                        return@withContext enriched
                    }
                } catch (e: CancellationException) {
                    throw e
                } catch (_: Exception) {}
            }
            base
        }
}
