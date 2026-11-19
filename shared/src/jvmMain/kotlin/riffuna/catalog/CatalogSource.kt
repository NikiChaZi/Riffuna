package riffuna.catalog

import kotlinx.serialization.json.*
import riffuna.core.Track
import riffuna.core.isLocalFile

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
    fun append(next: ArtistTracksPage) =
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

data class ArtistLookup(val candidates: List<CatalogEntry>, val direct: CatalogEntry?)

suspend fun CatalogSource.findTrackArtists(track: Track): ArtistLookup {
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

interface CatalogSource {
    suspend fun searchCatalog(query: String, kind: CatalogKind): List<CatalogEntry>

    suspend fun catalogPage(entry: CatalogEntry): CatalogPage

    suspend fun artistTracks(entry: CatalogEntry, cursor: String? = null): ArtistTracksPage

    suspend fun trackArtists(track: Track): List<CatalogEntry>
}

private fun JsonObject.catalogText(key: String): String =
    get(key)?.jsonPrimitive?.contentOrNull.orEmpty()

private fun JsonObject.catalogRows(key: String): List<JsonObject> =
    get(key)?.jsonArray.orEmpty().map { it.jsonObject }

private fun JsonObject.catalogEntry(defaultKind: CatalogKind): CatalogEntry? {
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

class JsonCatalogSource(private val request: suspend (JsonObject) -> JsonObject) : CatalogSource {
    override suspend fun searchCatalog(query: String, kind: CatalogKind): List<CatalogEntry> {
        val text = query.trim()
        if (text.isBlank() || text.length > 500 || text.contains("://")) return emptyList()
        return request(
                buildJsonObject {
                    put("action", "catalog_search")
                    put("query", text)
                    put("kind", if (kind == CatalogKind.ARTIST) "artist" else "album")
                }
            )
            .catalogRows("entries")
            .mapNotNull { it.catalogEntry(kind) }
    }

    override suspend fun trackArtists(track: Track): List<CatalogEntry> {
        if (track.isLocalFile) return emptyList()
        return request(
                buildJsonObject {
                    put("action", "catalog_track_artists")
                    put("id", track.id)
                }
            )
            .catalogRows("entries")
            .mapNotNull { it.catalogEntry(CatalogKind.ARTIST) }
    }

    override suspend fun artistTracks(entry: CatalogEntry, cursor: String?): ArtistTracksPage {
        require(entry.kind == CatalogKind.ARTIST)
        val result =
            request(
                buildJsonObject {
                    put("action", "catalog_artist_tracks")
                    put("id", entry.id)
                    if (cursor != null) put("cursor", cursor)
                }
            )
        check(result["retry"]?.jsonPrimitive?.booleanOrNull != true) {
            "Could not load the next page"
        }
        return ArtistTracksPage(
            tracks = result.catalogRows("tracks").mapNotNull(MusicRules::track),
            cursor = result.catalogText("cursor").ifBlank { null },
            partial = result["partial"]?.jsonPrimitive?.booleanOrNull == true,
            expired = result["expired"]?.jsonPrimitive?.booleanOrNull == true,
        )
    }

    override suspend fun catalogPage(entry: CatalogEntry): CatalogPage {
        val result =
            request(
                buildJsonObject {
                    put(
                        "action",
                        if (entry.kind == CatalogKind.ARTIST) "catalog_artist" else "catalog_album",
                    )
                    put("id", entry.id)
                }
            )
        return CatalogPage(
            entry.copy(
                title = result.catalogText("title").ifBlank { entry.title },
                thumbnail = result.catalogText("thumbnail").ifBlank { entry.thumbnail },
            ),
            result.catalogRows("tracks").mapNotNull(MusicRules::track),
            result.catalogRows("releases").mapNotNull { it.catalogEntry(CatalogKind.ALBUM) },
            (result["artist"] as? JsonObject)?.catalogEntry(CatalogKind.ARTIST),
        )
    }
}
