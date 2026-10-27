package riffuna.desktop

import kotlinx.serialization.json.*
import riffuna.core.*

/** Strict music gates and recording identity; titles alone never classify an upload. */
object MusicRules {
    val excluded =
        Regex(
            """(?U)\b(?:live|concert\w*|концерт\w*|клип\w*|clip|music\s+video|official\s+video|reaction\w*|reacts?|reacting|реакци\w*|реагиру\w*|смотрит|смотрим|смотрят|разбор\w*|обзор\w*|review\w*|analysis|tutorial\w*|lesson\w*|урок\w*|cartoon\w*|episode\w*|мульт\w*|эпизод\w*|серии|серия|sfm|amv|gmv|gameplay|trailer|cutscene|visualizer|выступлен\w*|исполнени\w*|festival|фестивал\w*|summer\s+sound|\d{1,2}[./]\d{1,2}[./](?:20)?\d{2}|vkfest|loop(?:ed)?|repeat|зациклен\w*|петл\w*|\d+\s*(?:hours?|hrs?|час\w*|h))\b""",
            RegexOption.IGNORE_CASE,
        )
    val musicalVersion =
        Regex(
            """\b(?:ost|soundtrack|extended|remix|mashup|slowed|sped\s*up|speed\s*up|official\s+audio|audio|аудио|саундтрек|ремикс|мэшап|мешап)\b""",
            RegexOption.IGNORE_CASE,
        )
    private val noise =
        setOf(
            "official",
            "audio",
            "song",
            "music",
            "трек",
            "песня",
            "of",
            "the",
            "and",
            "feat",
            "ft",
        )
    private val patterns =
        listOf(
                "ULTRA SLOWED" to "\\b(?:ultra\\s+slowed|ultraslowed)\\b",
                "SUPER SLOWED" to "\\b(?:super\\s+slowed|superslowed)\\b",
                "SLOWED" to "\\b(?:slowed|slow\\s*\\+|замедлен\\w*)\\b",
                "SPED UP" to "\\b(?:sped\\s*up|speed\\s*up|nightcore|ускорен\\w*)\\b",
                "MASHUP" to "\\b(?:mash\\s*up|м[эе]шап)\\b",
                "REMIX" to "\\b(?:remix|ремикс|bootleg)\\b",
                "INSTRUMENTAL" to "\\b(?:instrumental|инструментал\\w*|караоке|karaoke)\\b",
                "EXTENDED" to "\\b(?:extended|расширенная\\s+версия)\\b",
                "REMASTER" to "\\b(?:remaster(?:ed)?|ремастер\\w*)\\b",
                "ACOUSTIC" to "\\b(?:acoustic|акустическ\\w*)\\b",
            )
            .map { it.first to Regex("(?U)" + it.second, RegexOption.IGNORE_CASE) }

    fun normal(value: String) = MusicModel.normal(value)

    fun artist(value: String) =
        normal(Regex("\\s*[-–—]\\s*topic\\s*$", RegexOption.IGNORE_CASE).replace(value, ""))

    fun words(value: String) =
        normal(value)
            .split(' ')
            .filter(String::isNotBlank)
            .map {
                when (it) {
                    "мэшап",
                    "мешап" -> "mashup"
                    "ремикс" -> "remix"
                    "speed" -> "sped"
                    else -> it
                }
            }
            .map {
                if (
                    it.all { c -> c.code < 128 } &&
                        it.length > 3 &&
                        it.endsWith('s') &&
                        !listOf("ss", "us", "is").any(it::endsWith)
                )
                    it.dropLast(1)
                else it
            }
            .filter { it !in noise }

    private fun similarity(a: String, b: String): Double =
        if (a == b) 1.0
        else if (minOf(a.length, b.length) < 4 || kotlin.math.abs(a.length - b.length) > 2) 0.0
        else TextMatch.ratio(a, b).takeIf { it >= .78 } ?: 0.0

    fun score(query: String, title: String, performer: String): Double {
        val required = words(query)
        if (required.isEmpty()) return 0.0
        val tw = words(title)
        val aw = words(performer)
        val available = tw + aw
        if (available.isEmpty()) return -1.0
        val scores = required.map { q -> available.maxOf { similarity(q, it) } }
        if (scores.any { it == 0.0 }) return -1.0
        if (required.size > 1) {
            val pairs = required.zipWithNext()
            val ordered =
                listOf(tw + aw, aw + tw).any { sequence ->
                    sequence.indices.any { i ->
                        (i + 1 until minOf(sequence.size, i + 4)).any { j ->
                            pairs.any { (left, right) ->
                                similarity(left, sequence[i]) > 0 &&
                                    similarity(right, sequence[j]) > 0
                            }
                        }
                    }
                }
            if (!ordered) return -1.0
        }
        var score = 100 * scores.average()
        if (tw == required) score += 40
        if (aw == required) score += 30
        if ((tw + aw).windowed(required.size).any { it == required }) score += 20
        val artistMatches = required.filter { q -> aw.any { similarity(q, it) > 0 } }
        if (artistMatches.isNotEmpty() && required.filter { it !in artistMatches } == tw)
            score += 80
        if (profile(title).isNotEmpty() && profile(query).isEmpty()) score -= 10
        return score
    }

    fun profile(title: String): List<String> {
        val result =
            patterns.filter { it.second.containsMatchIn(title) }.map { it.first }.toMutableList()
        if (result.any { it in setOf("ULTRA SLOWED", "SUPER SLOWED") }) result.remove("SLOWED")
        return result
    }

    private val annotation = Regex("""\(([^()]*)\)|\[([^\[\]]*)\]""")
    private val declarations =
        Regex(
            """^(?:official\s+audio|audio|official|lyrics?|hd|hq|4k|аудио|официальное\s+аудио|uncensored|uncut|explicit|без\s+цензуры|нецензурная\s+версия|original(?:\s+version)?|оригинал(?:ьная\s+версия)?|clean(?:\s+version)?|censored|цензурированная\s+версия)$""",
            RegexOption.IGNORE_CASE,
        )
    private val suffix =
        Regex(
            """(?:\s*[-–—|:]\s*|\s+)(?:official\s+audio|официальное\s+аудио|uncensored|uncut|explicit|без\s+цензуры|original\s+version|original|оригинальная\s+версия|оригинал|clean\s+version|clean|censored)\s*$""",
            RegexOption.IGNORE_CASE,
        )

    fun withoutDeclarations(title: String): String {
        var result =
            annotation.replace(title) { m ->
                val text = m.groupValues[1].ifEmpty { m.groupValues[2] }
                if (
                    declarations.matches(
                        Regex("\\b(?:19|20)\\d{2}\\b")
                            .replace(text, "")
                            .trim(' ', ',', '–', '—', '-', '|')
                    )
                )
                    " "
                else m.value
            }
        while (true) {
            val shortened = suffix.replace(result, "").trim()
            if (shortened.isEmpty() || shortened == result) return result.trim()
            result = shortened
        }
    }

    fun songTitle(title: String, performer: String): String {
        var result = withoutDeclarations(title)
        val pieces = result.split(Regex("\\s+[-–—|]\\s+"), 2)
        if (pieces.size == 2) {
            if (artist(pieces[0]) == artist(performer)) result = pieces[1]
            else if (artist(pieces[1]) == artist(performer)) result = pieces[0]
        }
        return result.trim()
    }

    fun composition(title: String): String {
        var result =
            annotation.replace(withoutDeclarations(title)) { m ->
                val text = m.groupValues[1].ifEmpty { m.groupValues[2] }
                if (profile(text).isNotEmpty() || Regex("\\s*(?:19|20)\\d{2}\\s*").matches(text))
                    " "
                else m.value
            }
        patterns.forEach { result = it.second.replace(result, " ") }
        return normal(result)
    }

    fun versionMatches(reference: Track, candidate: Track): Boolean {
        if (
            reference.duration !in 1..1200 ||
                candidate.duration !in 1..1200 ||
                excluded.containsMatchIn(reference.title) ||
                excluded.containsMatchIn(candidate.title)
        )
            return false
        val expected = artist(reference.artist)
        if (expected in setOf("", "youtube", "unknown", "неизвестный исполнитель")) return false
        var title = songTitle(candidate.title, candidate.artist)
        val credited =
            artist(candidate.artist).split(' ').windowed(expected.split(' ').size).any {
                it.joinToString(" ") == expected
            }
        if (!credited) {
            val split = candidate.title.split(Regex("\\s+[-–—]\\s+"), 2)
            if (split.size != 2) return false
            title =
                when {
                    artist(withoutDeclarations(split[0])) == expected -> split[1]
                    artist(withoutDeclarations(split[1])) == expected -> split[0]
                    else -> return false
                }
        }
        val a = composition(songTitle(reference.title, reference.artist))
        val b = composition(title)
        if (
            a != b &&
                (minOf(a.length, b.length) < 6 ||
                    a.split(' ').size != b.split(' ').size ||
                    TextMatch.ratio(a, b) < .94)
        )
            return false
        val pa = profile(reference.title)
        val pb = profile(title)
        val ratio = candidate.duration.toDouble() / reference.duration
        return if (pa == pb)
            kotlin.math.abs(candidate.duration - reference.duration) <=
                maxOf(6.0, minOf(20.0, reference.duration * .08))
        else
            when {
                (pa + pb).any {
                    it in setOf("SLOWED", "SUPER SLOWED", "ULTRA SLOWED", "SPED UP")
                } -> ratio in .5..2.0
                (pa + pb).any { it in setOf("REMIX", "MASHUP", "EXTENDED") } -> ratio in .65..1.75
                else -> ratio in .85..1.15
            }
    }

    fun workKey(track: Track) =
        "recording:${artist(track.artist)}::${normal(songTitle(track.title,track.artist))}"

    fun track(row: JsonObject): Track? =
        runCatching {
                val id = row["id"]!!.jsonPrimitive.content
                require(Regex("[\\w-]{11}").matches(id))
                Track(
                    id,
                    row["title"]!!.jsonPrimitive.content,
                    row["artist"]?.jsonPrimitive?.content ?: "YouTube",
                    row["duration"]?.jsonPrimitive?.doubleOrNull?.toInt() ?: 0,
                    row["thumbnail"]?.jsonPrimitive?.content ?: "",
                    version = profile(row["title"]!!.jsonPrimitive.content).joinToString(" · "),
                    viewCount = row["viewCount"]?.jsonPrimitive?.longOrNull,
                    published = row["published"]?.jsonPrimitive?.contentOrNull ?: "",
                )
            }
            .getOrNull()

    fun catalog(row: JsonObject, query: String): Track? {
        if (
            row["musicType"]?.jsonPrimitive?.content != "MUSIC_VIDEO_TYPE_ATV" ||
                row["live"]?.jsonPrimitive?.booleanOrNull == true ||
                row["available"]?.jsonPrimitive?.booleanOrNull == false
        )
            return null
        val track = track(row) ?: return null
        return track.takeIf {
            it.duration in 1..1200 &&
                !excluded.containsMatchIn(
                    it.title + " " + (row["album"]?.jsonPrimitive?.content ?: "")
                ) &&
                score(query, it.title, it.artist) >= 0
        }
    }
}
