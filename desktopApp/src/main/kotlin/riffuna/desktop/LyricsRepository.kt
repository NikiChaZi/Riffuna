package riffuna.desktop

import java.net.URLEncoder
import java.nio.file.*
import java.security.MessageDigest
import javax.xml.parsers.DocumentBuilderFactory
import kotlinx.serialization.json.*
import org.w3c.dom.Element
import riffuna.core.*

/** Recording-specific LRC/TTML and LRCLIB; no Python and no guessed audio clocks. */
class LyricsRepository(private val directory: Path) {
    private val max = 1_048_576

    private fun parsePacket(row: JsonObject) =
        LyricsPacket(
                row["state"]?.jsonPrimitive?.content ?: "not_found",
                row["lines"]?.jsonArray.orEmpty().map { value ->
                    val line = value.jsonObject
                    LyricLine(
                        line["start_ms"]!!.jsonPrimitive.long,
                        line["end_ms"]?.jsonPrimitive?.longOrNull,
                        line["text"]!!.jsonPrimitive.content,
                        line["words"]?.jsonArray.orEmpty().map { v ->
                            val w = v.jsonObject
                            LyricWord(
                                w["start_ms"]!!.jsonPrimitive.long,
                                w["end_ms"]!!.jsonPrimitive.long,
                                w["text"]!!.jsonPrimitive.content,
                            )
                        },
                    )
                },
                row["plain_text"]?.jsonPrimitive?.content ?: "",
                row["source"]?.jsonPrimitive?.content ?: "",
                row["source_url"]?.jsonPrimitive?.content ?: "",
                row["timing_source"]?.jsonPrimitive?.content ?: "none",
                row["message"]?.jsonPrimitive?.content ?: "",
            )
            .let { it.copy(approximateWords = it.lines.none { line -> line.words.isNotEmpty() }) }

    private fun packetJson(packet: LyricsPacket) = buildJsonObject {
        put("state", packet.state)
        put("plain_text", packet.plainText)
        put("source", packet.source)
        put("source_url", packet.sourceUrl)
        put("timing_source", packet.timingSource)
        put("message", packet.message)
        put(
            "lines",
            JsonArray(
                packet.lines.map { line ->
                    buildJsonObject {
                        put("start_ms", line.startMs)
                        put("text", line.text)
                        line.endMs?.let { put("end_ms", it) }
                        put(
                            "words",
                            JsonArray(
                                line.words.map { word ->
                                    buildJsonObject {
                                        put("start_ms", word.startMs)
                                        put("end_ms", word.endMs)
                                        put("text", word.text)
                                    }
                                }
                            ),
                        )
                    }
                }
            ),
        )
    }

    private fun signature(track: Track): String {
        val values =
            listOf(
                JsonPrimitive(track.id),
                JsonPrimitive(track.title),
                JsonPrimitive(track.artist),
                JsonPrimitive(track.duration),
            )
        return MessageDigest.getInstance("SHA-256")
            .digest(values.joinToString(", ", "[", "]").toByteArray())
            .joinToString("") { "%02x".format(it) }
    }

    fun load(track: Track, force: Boolean = false): LyricsPacket {
        for (extension in listOf("ttml", "lrc")) {
            val local = directory.resolve("${track.id}.$extension")
            if (Files.isRegularFile(local)) return imported(Files.readString(local), extension)
        }
        val file = directory.resolve("${track.id}.json")
        val now = System.currentTimeMillis() / 1000
        val saved =
            runCatching {
                    require(Files.size(file) <= max)
                    val record = Json.parseToJsonElement(Files.readString(file)).jsonObject
                    require(record["signature"]?.jsonPrimitive?.content == signature(track))
                    record
                }
                .getOrNull()
        saved?.let { record ->
            val payload = parsePacket(record["payload"]!!.jsonObject)
            if (
                !force &&
                    (record["provider_revision"]?.jsonPrimitive?.intOrNull ?: 0) >= 4 &&
                    (record["expires"]?.jsonPrimitive?.doubleOrNull ?: 0.0) > now
            )
                return payload
        }
        val value =
            try {
                fetch(track)
            } catch (e: Exception) {
                saved?.let { record ->
                    val previous = parsePacket(record["payload"]!!.jsonObject)
                    if (previous.state in setOf("synced", "plain", "instrumental"))
                        return previous.copy(
                            message = "Сохранённый текст: сервис временно недоступен"
                        )
                }
                return LyricsPacket(message = "Не удалось загрузить текст. Можно повторить запрос.")
            }
        runCatching {
            Files.createDirectories(directory)
            val record = buildJsonObject {
                put("signature", signature(track))
                put("expires", now + if (value.state == "not_found") 3600 else 30 * 86400)
                put("provider_revision", 4)
                put(
                    "payload",
                    buildJsonObject {
                        put("recording_id", track.id)
                        packetJson(value).forEach { (key, item) -> put(key, item) }
                    },
                )
            }
            val temporary = file.resolveSibling(file.fileName.toString() + ".part")
            Files.writeString(temporary, record.toString())
            Files.move(temporary, file, StandardCopyOption.REPLACE_EXISTING)
        }
        return value
    }

    fun import(track: Track, text: String, format: String): LyricsPacket {
        val extension = if (format.lowercase() in setOf("xml", "ttml")) "ttml" else "lrc"
        val value = imported(text, extension)
        Files.createDirectories(directory)
        Files.writeString(directory.resolve("${track.id}.$extension"), text.removePrefix("\uFEFF"))
        Files.deleteIfExists(
            directory.resolve("${track.id}." + if (extension == "lrc") "ttml" else "lrc")
        )
        return value
    }

    private fun imported(text: String, format: String): LyricsPacket {
        require(text.toByteArray().size <= max)
        val lines = if (format == "ttml") parseTtml(text) else LyricTiming.parseLrc(text)
        require(lines.isNotEmpty() && lines.any { it.text.isNotBlank() })
        return LyricsPacket(
            "synced",
            lines,
            lines.joinToString("\n") { it.text },
            "local",
            timingSource = "local_$format",
            approximateWords = lines.none { it.words.isNotEmpty() },
        )
    }

    private fun request(endpoint: String, params: Map<String, String>): JsonElement? {
        val url =
            endpoint +
                "?" +
                params.entries.joinToString("&") {
                    URLEncoder.encode(it.key, Charsets.UTF_8) +
                        "=" +
                        URLEncoder.encode(it.value, Charsets.UTF_8)
                }
        val wordsProvider = endpoint.contains("betterlyrics.org")
        repeat(if (wordsProvider) 1 else 2) { attempt ->
            val connection = DesktopNetwork.open(url)
            try {
                if (wordsProvider) {
                    connection.connectTimeout = 2000
                    connection.readTimeout = 3500
                }
                connection.setRequestProperty("Accept", "application/json")
                val status = connection.responseCode
                if (status == 404) return null
                if (status in setOf(429, 500, 502, 503, 504) && attempt == 0 && !wordsProvider) {
                    Thread.sleep(300)
                    return@repeat
                }
                check(status == 200)
                require(connection.contentType?.contains("json") == true)
                val bytes = connection.inputStream.use { it.readNBytes(max + 1) }
                require(bytes.size <= max)
                return Json.parseToJsonElement(String(bytes, Charsets.UTF_8))
            } finally {
                connection.disconnect()
            }
        }
        return null
    }

    private fun artistKey(value: String): String {
        val table =
            mapOf(
                'а' to "a",
                'б' to "b",
                'в' to "v",
                'г' to "g",
                'д' to "d",
                'е' to "e",
                'ж' to "zh",
                'з' to "z",
                'и' to "i",
                'й' to "y",
                'к' to "k",
                'л' to "l",
                'м' to "m",
                'н' to "n",
                'о' to "o",
                'п' to "p",
                'р' to "r",
                'с' to "s",
                'т' to "t",
                'у' to "u",
                'ф' to "f",
                'х' to "kh",
                'ц' to "ts",
                'ч' to "ch",
                'ш' to "sh",
                'щ' to "shch",
                'ъ' to "",
                'ы' to "y",
                'ь' to "",
                'э' to "e",
                'ю' to "yu",
                'я' to "ya",
            )
        return MusicRules.artist(value).map { table[it] ?: it.toString() }.joinToString("")
    }

    private fun fetch(track: Track): LyricsPacket {
        val title = MusicRules.songTitle(track.title, track.artist)
        val artist =
            Regex("\\s*[-–—]\\s*topic$", RegexOption.IGNORE_CASE).replace(track.artist, "").trim()
        val records = mutableListOf<JsonObject>()
        var reachable = false
        val exact =
            runCatching {
                    request(
                            "https://lrclib.net/api/get",
                            mapOf(
                                "track_name" to title,
                                "artist_name" to artist,
                                "duration" to track.duration.toString(),
                            ),
                        )
                        .also { reachable = true }
                }
                .getOrNull()
        if (exact is JsonObject) records.add(exact)
        var matched = match(track, title, artist, records)
        if (matched?.state == "instrumental" || matched?.let { covered(it, track) } == true)
            return matched!!
        for (params in
            listOf(
                mapOf("track_name" to title, "artist_name" to artist),
                mapOf("track_name" to title),
            )) {
            val result =
                runCatching {
                        request("https://lrclib.net/api/search", params).also { reachable = true }
                    }
                    .getOrNull()
            if (result is JsonArray)
                records.addAll(result.take(100).mapNotNull { it as? JsonObject })
            matched = match(track, title, artist, records)
            if (matched?.state == "instrumental" || matched?.let { covered(it, track) } == true)
                return matched!!
        }
        if (!reachable) error("Lyrics provider unavailable")
        return matched ?: LyricsPacket(source = "LRCLIB")
    }

    private data class Candidate(
        val row: JsonObject,
        val delta: Double,
        val title: Double,
        val artist: Double,
        val lines: List<LyricLine>,
        val coverage: Boolean,
    )

    internal fun match(
        track: Track,
        title: String,
        artist: String,
        records: List<JsonObject>,
    ): LyricsPacket? {
        val candidates =
            records
                .mapNotNull { row ->
                    val name =
                        row["trackName"]?.jsonPrimitive?.contentOrNull ?: return@mapNotNull null
                    val performer =
                        row["artistName"]?.jsonPrimitive?.contentOrNull ?: return@mapNotNull null
                    if (MusicRules.profile(title) != MusicRules.profile(name))
                        return@mapNotNull null
                    var candidateTitle = MusicRules.songTitle(name, performer)
                    val stripped =
                        Regex(
                                "\\s*[\\[(](?:paused|playing|приостановлено)[\\])]\\s*$",
                                RegexOption.IGNORE_CASE,
                            )
                            .replace(candidateTitle, "")
                            .trim()
                    if (
                        stripped != candidateTitle &&
                            MusicRules.normal(stripped) == MusicRules.normal(title)
                    ) {
                        fun words(item: JsonObject) =
                            MusicRules.normal(
                                    item["plainLyrics"]?.jsonPrimitive?.contentOrNull
                                        ?: LyricTiming.parseLrc(
                                                item["syncedLyrics"]?.jsonPrimitive?.contentOrNull
                                                    ?: ""
                                            )
                                            .joinToString(" ") { it.text }
                                )
                                .take(8000)
                        val rowWords = words(row)
                        if (
                            rowWords.isNotBlank() &&
                                records.any { record ->
                                    MusicRules.normal(
                                        record["trackName"]?.jsonPrimitive?.contentOrNull.orEmpty()
                                    ) == MusicRules.normal(title) &&
                                        artistKey(
                                            record["artistName"]
                                                ?.jsonPrimitive
                                                ?.contentOrNull
                                                .orEmpty()
                                        ) == artistKey(artist) &&
                                        TextMatch.ratio(rowWords, words(record)) >= .95
                                }
                        )
                            candidateTitle = stripped
                    }
                    val titleScore =
                        TextMatch.ratio(MusicRules.normal(title), MusicRules.normal(candidateTitle))
                    val artistScore =
                        if (artistKey(performer) == artistKey(artist)) 1.0
                        else
                            TextMatch.ratio(MusicRules.artist(performer), MusicRules.artist(artist))
                    if (titleScore < .9 || artistScore < .8) return@mapNotNull null
                    val duration =
                        row["duration"]?.jsonPrimitive?.doubleOrNull ?: return@mapNotNull null
                    val lines =
                        runCatching {
                                LyricTiming.parseLrc(
                                    row["syncedLyrics"]?.jsonPrimitive?.contentOrNull ?: ""
                                )
                            }
                            .getOrDefault(emptyList())
                    val meaningful = lines.filter { line -> line.text.any(Char::isLetter) }
                    val valid =
                        meaningful.map { it.startMs }.distinct().size >= 2 &&
                            (meaningful.maxOfOrNull { it.startMs } ?: 0) <=
                                track.duration * 1000 + 2000
                    if (
                        !valid &&
                            row["plainLyrics"]?.jsonPrimitive?.contentOrNull.isNullOrBlank() &&
                            row["instrumental"]?.jsonPrimitive?.booleanOrNull != true
                    )
                        return@mapNotNull null
                    Candidate(
                        row,
                        kotlin.math.abs(duration - track.duration),
                        titleScore,
                        artistScore,
                        if (valid) lines else emptyList(),
                        (meaningful.maxOfOrNull { it.startMs } ?: 0) >= track.duration * 800L,
                    )
                }
                .sortedWith(
                    compareBy<Candidate> { it.delta > 2 }
                        .thenByDescending { it.title + it.artist }
                        .thenBy { it.lines.isEmpty() }
                        .thenByDescending { it.coverage }
                        .thenBy { it.delta }
                        .thenByDescending { it.lines.size }
                )
        val best = candidates.firstOrNull() ?: return null
        val row = best.row
        val url =
            row["id"]?.jsonPrimitive?.longOrNull?.let { "https://lrclib.net/api/get/$it" }
                ?: "https://lrclib.net/"
        if (row["instrumental"]?.jsonPrimitive?.booleanOrNull == true && best.delta <= 2)
            return LyricsPacket("instrumental", source = "LRCLIB", sourceUrl = url)
        val plain =
            row["plainLyrics"]?.jsonPrimitive?.contentOrNull?.takeIf { it.isNotBlank() }
                ?: best.lines.joinToString("\n") { it.text }
        if (best.delta <= 2 && best.lines.isNotEmpty())
            return LyricsPacket(
                "synced",
                best.lines,
                plain,
                "LRCLIB",
                url,
                "provider_lrc",
                approximateWords = best.lines.none { it.words.isNotEmpty() },
            )
        return if (plain.isNotBlank())
            LyricsPacket(
                "plain",
                plainText = plain,
                source = "LRCLIB",
                sourceUrl = url,
                message = "Текст без точной синхронизации с этой записью",
            )
        else null
    }

    private fun covered(packet: LyricsPacket, track: Track) =
        packet.state == "synced" &&
            (packet.lines.filter { it.text.any(Char::isLetter) }.maxOfOrNull { it.startMs } ?: 0) in
                track.duration * 800L..track.duration * 1000L + 2000

    private fun compatible(track: Track, base: LyricsPacket, lines: List<LyricLine>): Boolean {
        if (lines.isEmpty() || lines.none { it.words.isNotEmpty() } || track.duration <= 0)
            return false
        val a =
            MusicRules.normal(base.plainText.ifBlank { base.lines.joinToString(" ") { it.text } })
        val b = MusicRules.normal(lines.joinToString(" ") { it.text })
        if (
            a.isBlank() ||
                a.length > 8000 ||
                b.length > 8000 ||
                TextMatch.ratio(a, b) < .94 ||
                lines.flatMap { it.words }.maxOf { it.endMs } > track.duration * 1000L + 2000
        )
            return false
        val starts = base.lines.associate { MusicRules.normal(it.text) to it.startMs }
        val differences =
            lines.mapNotNull { line ->
                starts[MusicRules.normal(line.text)]?.let { kotlin.math.abs(it - line.startMs) }
            }
        return differences.size >= minOf(2, lines.size) &&
            differences.count { it <= 2200 }.toDouble() / differences.size >= .85
    }

    fun enrich(track: Track, base: LyricsPacket): LyricsPacket {
        if (
            base.state != "synced" ||
                base.lines.any { it.words.isNotEmpty() } ||
                base.source == "local" ||
                MusicRules.profile(track.title).isNotEmpty()
        )
            return base
        val path = directory.resolve("${track.id}.words.json")
        val now = System.currentTimeMillis() / 1000
        val identity = signature(track)
        runCatching {
            require(Files.size(path) <= max)
            val saved = Json.parseToJsonElement(Files.readString(path)).jsonObject
            require(
                saved["signature"]!!.jsonPrimitive.content.startsWith(identity) &&
                    (saved["expires"]!!.jsonPrimitive.double) > now
            )
            val packet = saved["payload"]
            if (packet == null || packet is JsonNull) return base
            val data = packet.jsonObject
            require(data["recording_id"]?.jsonPrimitive?.content == track.id)
            val candidate = parsePacket(data)
            if (compatible(track, base, candidate.lines)) return candidate
        }
        var enriched = base
        val title = MusicRules.songTitle(track.title, track.artist)
        for ((endpoint, field) in listOf("/getLyrics" to "ttml", "/qq/getLyrics" to "lyrics")) {
            val row =
                runCatching {
                        request(
                            "https://api.betterlyrics.org$endpoint",
                            mapOf(
                                "s" to title,
                                "a" to track.artist,
                                "al" to "",
                                "d" to track.duration.toString(),
                            ),
                        )
                            as? JsonObject
                    }
                    .getOrNull() ?: continue
            if ((row["score"]?.jsonPrimitive?.doubleOrNull ?: 1.0) < .9) continue
            val text = row[field]?.jsonPrimitive?.contentOrNull ?: continue
            val lines =
                runCatching { if (field == "ttml") parseTtml(text) else parseQrc(text) }
                    .getOrDefault(emptyList())
            if (compatible(track, base, lines)) {
                enriched =
                    base.copy(
                        lines = lines,
                        timingSource = "provider_words",
                        approximateWords = false,
                    )
                break
            }
        }
        runCatching {
            Files.createDirectories(directory)
            val record = buildJsonObject {
                put("signature", identity)
                put("expires", now + if (enriched.approximateWords) 86400 else 30 * 86400)
                put(
                    "payload",
                    if (enriched.approximateWords) JsonNull
                    else
                        buildJsonObject {
                            put("recording_id", track.id)
                            packetJson(enriched).forEach { (key, value) -> put(key, value) }
                        },
                )
            }
            val temporary = path.resolveSibling(path.fileName.toString() + ".part")
            Files.writeString(temporary, record.toString())
            Files.move(temporary, path, StandardCopyOption.REPLACE_EXISTING)
        }
        return enriched
    }

    companion object {
        private fun xml(text: String): Element {
            require(
                text.toByteArray().size <= 1_048_576 &&
                    !Regex("<!\\s*(?:DOCTYPE|ENTITY)", RegexOption.IGNORE_CASE)
                        .containsMatchIn(text)
            )
            val factory = DocumentBuilderFactory.newInstance()
            factory.isNamespaceAware = true
            factory.setFeature("http://apache.org/xml/features/disallow-doctype-decl", true)
            factory.setFeature("http://xml.org/sax/features/external-general-entities", false)
            factory.setFeature("http://xml.org/sax/features/external-parameter-entities", false)
            factory.isXIncludeAware = false
            factory.isExpandEntityReferences = false
            return factory.newDocumentBuilder().parse(text.byteInputStream()).documentElement
        }

        fun parseTtml(text: String): List<LyricLine> {
            val root = xml(text)
            val nodes = root.getElementsByTagNameNS("*", "p")
            val rows = mutableListOf<LyricLine>()
            for (i in 0 until nodes.length) {
                val p = nodes.item(i) as Element
                if (!p.hasAttribute("begin")) continue
                val start = LyricTiming.timestamp(p.getAttribute("begin"))
                val end =
                    p.getAttribute("end").takeIf { it.isNotBlank() }?.let(LyricTiming::timestamp)
                val words = mutableListOf<LyricWord>()
                fun visit(element: Element) {
                    for (a in 0 until element.attributes.length) {
                        val attribute = element.attributes.item(a)
                        if (
                            attribute.localName == "role" &&
                                attribute.nodeValue in setOf("x-bg", "x-translation", "x-roman")
                        )
                            return
                    }
                    val children =
                        (0 until element.childNodes.length)
                            .map { element.childNodes.item(it) }
                            .filterIsInstance<Element>()
                    if (
                        element.localName == "span" &&
                            element.hasAttribute("begin") &&
                            element.hasAttribute("end") &&
                            children.none { it.hasAttribute("begin") }
                    ) {
                        val a = LyricTiming.timestamp(element.getAttribute("begin"))
                        val b = LyricTiming.timestamp(element.getAttribute("end"))
                        val tail =
                            element.nextSibling
                                ?.takeIf { it.nodeType == org.w3c.dom.Node.TEXT_NODE }
                                ?.nodeValue
                                ?.takeIf { '\n' !in it && '\r' !in it }
                                .orEmpty()
                        require(a >= start && b > a && (end == null || b <= end + 100))
                        words.add(LyricWord(a, b, element.textContent + tail))
                        return
                    }
                    children.forEach(::visit)
                }
                visit(p)
                require(words.zipWithNext().all { it.first.startMs <= it.second.startMs })
                val value =
                    if (words.isEmpty()) p.textContent.trim()
                    else words.joinToString("") { it.text }.trim()
                if (value.isNotEmpty())
                    rows.add(LyricLine(start, end ?: words.maxOfOrNull { it.endMs }, value, words))
                require(rows.size <= 10000)
            }
            return rows.sortedBy { it.startMs }
        }

        fun parseQrc(document: String): List<LyricLine> {
            var text = document
            if (text.trimStart().startsWith('<')) {
                val elements = xml(text).getElementsByTagName("*")
                text =
                    (0 until elements.length)
                        .mapNotNull {
                            (elements.item(it) as? Element)?.getAttribute("LyricContent")?.takeIf {
                                it.isNotBlank()
                            }
                        }
                        .firstOrNull() ?: ""
            }
            return text
                .lineSequence()
                .mapNotNull { line ->
                    val header =
                        Regex("^\\[(\\d+),(\\d+)]").find(line.trim()) ?: return@mapNotNull null
                    val raw = line.trim()
                    var cursor = header.range.last + 1
                    val words = mutableListOf<LyricWord>()
                    Regex("\\((\\d+),(\\d+)\\)").findAll(raw, cursor).forEach { stamp ->
                        val value = raw.substring(cursor, stamp.range.first)
                        val start = stamp.groupValues[1].toLong()
                        val duration = stamp.groupValues[2].toLong()
                        if (value.isNotEmpty() && duration > 0)
                            words.add(LyricWord(start, start + duration, value))
                        cursor = stamp.range.last + 1
                    }
                    if (words.isEmpty()) null
                    else
                        LyricLine(
                            header.groupValues[1].toLong(),
                            header.groupValues[1].toLong() + header.groupValues[2].toLong(),
                            words.joinToString("") { it.text }.trim(),
                            words,
                        )
                }
                .take(10000)
                .toList()
        }
    }
}
