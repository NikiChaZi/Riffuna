package riffuna.desktop

import java.net.*
import java.nio.file.*
import java.security.MessageDigest
import kotlinx.serialization.json.*

/** Public artist tags, cached with the same format as the previous application. */
class ArtistTags(private val directory: Path) {
    private var lastRequest = 0L

    @Synchronized
    fun fetch(artist: String): List<String> {
        val now = System.currentTimeMillis() / 1000
        val key =
            MessageDigest.getInstance("SHA-256")
                .digest(MusicText.normalized(artist).toByteArray())
                .joinToString("") { "%02x".format(it) }
        val file = directory.resolve("$key.json")
        runCatching {
            val saved = Json.parseToJsonElement(Files.readString(file)).jsonObject
            val tags = saved["tags"]!!.jsonArray.map { it.jsonPrimitive.content }
            if (
                saved["artist"]?.jsonPrimitive?.content == artist &&
                    now - saved["at"]!!.jsonPrimitive.double <
                        (if (tags.isEmpty()) 21600 else 2592000)
            )
                return tags
        }
        val url =
            "https://www.last.fm/music/" +
                URLEncoder.encode(artist, Charsets.UTF_8).replace("+", "%20") +
                "/+tags"
        val tags =
            runCatching {
                    val wait = 1000 - (System.nanoTime() - lastRequest) / 1_000_000
                    if (wait > 0) Thread.sleep(wait)
                    lastRequest = System.nanoTime()
                    val connection = DesktopNetwork.open(url)
                    try {
                        connection.connectTimeout = 3000
                        connection.readTimeout = 6000
                        connection.setRequestProperty(
                            "User-Agent",
                            "Riffuna/0.2.0 (music metadata)",
                        )
                        check(connection.responseCode == 200)
                        val target = connection.url.toURI()
                        check(
                            target.host in setOf("last.fm", "www.last.fm") &&
                                target.rawPath == URI(url).rawPath
                        )
                        val data = connection.inputStream.use { it.readNBytes(1_000_001) }
                        check(data.size <= 1_000_000)
                        val html = String(data, Charsets.UTF_8)
                        Regex(
                                """<a\b[^>]*href=["']/tag/[^"']*["'][^>]*>(.*?)</a>""",
                                setOf(RegexOption.IGNORE_CASE, RegexOption.DOT_MATCHES_ALL),
                            )
                            .findAll(html)
                            .map {
                                Regex("<[^>]*>")
                                    .replace(it.groupValues[1], "")
                                    .trim()
                                    .replace("&amp;", "&")
                                    .replace("&#39;", "'")
                                    .replace("&quot;", "\"")
                            }
                            .filter { it.isNotBlank() }
                            .distinct()
                            .take(40)
                            .toList()
                    } finally {
                        connection.disconnect()
                    }
                }
                .getOrElse {
                    return emptyList()
                }
        runCatching {
            Files.createDirectories(directory)
            Files.writeString(
                file,
                buildJsonObject {
                        put("artist", artist)
                        put("at", now)
                        put("source", "Last.fm artist tags")
                        put("source_url", url)
                        put("tags", JsonArray(tags.map(::JsonPrimitive)))
                    }
                    .toString(),
            )
        }
        return tags
    }
}
