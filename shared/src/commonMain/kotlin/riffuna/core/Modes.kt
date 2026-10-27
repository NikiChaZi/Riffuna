package riffuna.core

enum class LibraryView(val key: String) {
    HOME("home"),
    LOCAL("local"),
    SEARCH("search"),
    RESONANCE("resonance"),
    LIKES("likes"),
    HISTORY("history"),
    PLAYLISTS("playlists"),
    PLAYLIST("playlist"),
    QUEUE("queue"),
}

enum class RepeatMode(val key: String) {
    OFF("off"),
    ONE("one"),
    ALL("all");

    fun next(): RepeatMode = entries[(ordinal + 1) % entries.size]

    companion object {
        fun fromKey(value: String): RepeatMode = entries.firstOrNull { it.key == value } ?: OFF
    }
}

enum class LocalOrder {
    CUSTOM,
    TITLE,
    ARTIST,
    SHORTEST,
    LONGEST,
}

enum class SearchOrder(val key: String) {
    RELEVANCE("relevance"),
    VIEWS("views"),
}
