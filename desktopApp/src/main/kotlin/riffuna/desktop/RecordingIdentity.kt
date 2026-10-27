package riffuna.desktop

import riffuna.core.Track

/** Canonical recording identity plus a frozen reader for previously persisted Qt keys. */
internal object RecordingIdentity {
    val annotations = Regex("""\(([^()]*)\)|\[([^\[\]]*)\]""")
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
            annotations.replace(title) { m ->
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
            if (MusicRules.artist(pieces[0]) == MusicRules.artist(performer)) result = pieces[1]
            else if (MusicRules.artist(pieces[1]) == MusicRules.artist(performer))
                result = pieces[0]
        }
        return result.trim()
    }

    fun key(track: Track): String =
        "recording:${MusicRules.artist(track.artist)}::${MusicText.normalized(songTitle(track.title, track.artist))}"

    // Do not replace this with the current key: older versions retained underscores and
    // removed declarations differently. It is used only as a fallback when reading settings.
    fun legacyKey(track: Track): String {
        val artist =
            Regex("\\s*[-–—]\\s*topic\\s*$", RegexOption.IGNORE_CASE)
                .replace(track.artist, "")
                .trim()
        var title =
            Regex("^" + Regex.escape(artist) + "\\s+[-–—]\\s+", RegexOption.IGNORE_CASE)
                .replace(track.title, "")
        title =
            Regex("""\(([^()]*)\)|\[([^\[\]]*)\]""").replace(title) { match ->
                val declaration = match.groupValues[1].ifEmpty { match.groupValues[2] }
                val annotation =
                    Regex("\\b(?:19|20)\\d{2}\\b").replace(declaration, "").trim().lowercase()
                if (
                    annotation in
                        setOf(
                            "official audio",
                            "audio",
                            "official",
                            "lyrics",
                            "lyric",
                            "hd",
                            "hq",
                            "4k",
                            "аудио",
                            "официальное аудио",
                            "uncensored",
                            "uncut",
                            "explicit",
                            "без цензуры",
                            "original",
                            "original version",
                            "оригинал",
                            "оригинальная версия",
                            "clean",
                            "clean version",
                            "censored",
                        )
                )
                    " "
                else match.value
            }
        title =
            Regex(
                    "(?:\\s*[-–—|:]\\s*|\\s+)(?:official audio|официальное аудио|uncensored|uncut|explicit|без цензуры|original version|original|оригинальная версия|оригинал|clean version|clean|censored)\\s*$",
                    RegexOption.IGNORE_CASE,
                )
                .replace(title, "")
        return "recording:" +
            MusicText.legacyNormalized(artist) +
            "::" +
            MusicText.legacyNormalized(title)
    }
}
