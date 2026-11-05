package riffuna.catalog

/** Studio catalog metadata is stronger evidence than an ambiguous word in a song name. */
object CatalogPresentation {
    private val unambiguousNoise =
        unicodeRegex(
            listOf(
                    "премьер[аы]\\s+клип\\w*",
                    "клип\\w*",
                    "official\\s+(?:music\\s+)?video",
                    "music\\s+video",
                    "разбор\\w*(?:\\s+трек\\w*)?",
                    "обзор\\w*",
                    "реакци\\w*",
                    "реагиру\\w*",
                    "смотрит|смотрим|смотрят",
                    "cartoon\\w*|episode\\w*|мульт\\w*|эпизод\\w*|gameplay|cutscene|trailer",
                    "концерт\\w*|выступлен\\w*|фестивал\\w*|vkfest",
                    "\\d+\\s*(?:hours?|hrs?|час\\w*|h)",
                )
                .joinToString("|", "\\b(?:", ")\\b")
        )
    private val qualifiedEdition =
        unicodeRegex(
            """(?i)(?:[\[(|:–—-]\s*)(?:live(?:\s+(?:at|from|in)\b[^\])|]*)?|concert[^\])|]*|loop(?:ed)?|(?:on\s+)?repeat|review|reaction|tutorial|official\s+clip)\s*(?:[\])|]|$)"""
        )
    private val liveSuffix = unicodeRegex("""(?i)\s+live\s*$""")
    private val liveVenue = unicodeRegex("""(?i)\blive\s+(?:at|from)\b""")
    private val concertAlbum =
        unicodeRegex("""(?i)(?:^live$|\blive\s+(?:at|from|in)\b|\bin\s+concert\b|\bконцерт\w*\b)""")

    fun excludes(title: String, album: String = ""): Boolean =
        unambiguousNoise.containsMatchIn(title) ||
            qualifiedEdition.containsMatchIn(title) ||
            liveSuffix.containsMatchIn(title) ||
            liveVenue.containsMatchIn(title) ||
            concertAlbum.containsMatchIn(album.trim())
}
