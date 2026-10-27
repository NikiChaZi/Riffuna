package riffuna.android

import java.text.Normalizer
import kotlinx.coroutines.Dispatchers
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
                normalized(track.title) &&
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
    }

    suspend fun load(track: Track, force: Boolean): LyricsPacket =
        withContext(Dispatchers.IO) {
            val key = "lyrics:" + track.id + ":" + track.duration
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
                        .addQueryParameter("track_name", track.title)
                        .addQueryParameter("artist_name", track.artist)
                        .addQueryParameter("duration", track.duration.toString())
                        .build()
                fun fetch(url: okhttp3.HttpUrl): JsonElement? =
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
                var row = fetch(exact)?.jsonObject?.takeIf { matches(it, track) }
                if (row == null) {
                    val search =
                        "https://lrclib.net/api/search"
                            .toHttpUrl()
                            .newBuilder()
                            .addQueryParameter("track_name", track.title)
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
            } catch (_: Exception) {
                LyricsPacket(
                    message = "Не удалось загрузить текст. Проверь соединение и повтори поиск"
                )
            }
        }
}
