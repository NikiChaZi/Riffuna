package riffuna.desktop

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import riffuna.core.Track

enum class CatalogKind(val label: String) {
    ARTIST("Исполнитель"),
    ALBUM("Альбом"),
    SINGLE("Сингл / EP"),
}

data class CatalogEntry(
    val id: String,
    val title: String,
    val kind: CatalogKind,
    val thumbnail: String = "",
    val artistName: String = "",
    val year: String = "",
)

data class ArtistTracksPage(
    val tracks: List<Track>,
    val cursor: String? = null,
    val partial: Boolean = false,
    val expired: Boolean = false,
) {
    internal fun append(next: ArtistTracksPage) =
        when {
            next.expired -> copy(cursor = null, expired = true)
            expired -> next
            else ->
                next.copy(
                    tracks = (tracks + next.tracks).distinctBy(Track::id),
                    partial = partial || next.partial,
                )
        }
}

internal data class ArtistLookup(val candidates: List<CatalogEntry>, val direct: CatalogEntry?)

internal suspend fun DesktopCatalogSource.findTrackArtists(track: Track): ArtistLookup {
    val linked = trackArtists(track)
    if (linked.isNotEmpty()) return ArtistLookup(linked, linked.singleOrNull())

    val names = track.artist.split(", ").map(String::trim).filter(String::isNotBlank).distinct()
    val results = names.map { name -> name to searchCatalog(name, CatalogKind.ARTIST) }
    val candidates =
        results
            .flatMap { (name, entries) ->
                entries
                    .filter { MusicRules.artist(it.title) == MusicRules.artist(name) }
                    .ifEmpty { entries.take(5) }
            }
            .distinctBy { it.id }
    val direct =
        if (names.size == 1)
            candidates.singleOrNull()?.takeIf {
                MusicRules.artist(it.title) == MusicRules.artist(names.single())
            }
        else null
    return ArtistLookup(candidates, direct)
}

data class CatalogPage(
    val entry: CatalogEntry,
    val tracks: List<Track>,
    val releases: List<CatalogEntry>,
    val artist: CatalogEntry?,
)

interface DesktopCatalogSource {
    suspend fun searchCatalog(query: String, kind: CatalogKind): List<CatalogEntry>

    suspend fun catalogPage(entry: CatalogEntry): CatalogPage

    suspend fun artistTracks(entry: CatalogEntry, cursor: String? = null): ArtistTracksPage

    suspend fun trackArtists(track: Track): List<CatalogEntry>
}

internal fun JsonObject.catalogText(key: String): String =
    get(key)?.jsonPrimitive?.contentOrNull.orEmpty()

internal fun JsonObject.catalogRows(key: String): List<JsonObject> =
    get(key)?.jsonArray.orEmpty().map { it.jsonObject }

internal fun JsonObject.catalogEntry(defaultKind: CatalogKind): CatalogEntry? {
    val id = catalogText("id")
    val title = catalogText("title")
    if (id.isBlank() || title.isBlank()) return null
    val kind =
        when {
            defaultKind == CatalogKind.ARTIST -> CatalogKind.ARTIST
            catalogText("type") == "single" -> CatalogKind.SINGLE
            else -> CatalogKind.ALBUM
        }
    return CatalogEntry(
        id = id,
        title = title,
        kind = kind,
        thumbnail = catalogText("thumbnail"),
        artistName = catalogText("artist"),
        year = catalogText("year"),
    )
}
