package riffuna.desktop

import riffuna.core.Track

/** Scores are request-local and keyed by the fields actually used for matching. */
internal class SearchRelevance(
    private val query: String,
    private val calculate: (String, String, String) -> Double = MusicRules::score,
) {
    private val scores = mutableMapOf<Pair<String, String>, Double>()

    fun score(track: Track): Double =
        scores.getOrPut(track.title to track.artist) { calculate(query, track.title, track.artist) }

    fun needsUploadFallback(tracks: List<Track>): Boolean {
        if (MusicRules.words(query).size < 2) return false
        val weakMatch = (tracks.maxOfOrNull(::score) ?: -1.0) < 175
        val requestsProcessing = MusicRules.musicalVersion.containsMatchIn(query)
        val sparseCatalog = tracks.size < 5
        val nonCyrillicQuery = query.none { it in '\u0400'..'\u052f' }
        return requestsProcessing || (weakMatch && (sparseCatalog || nonCyrillicQuery))
    }
}
