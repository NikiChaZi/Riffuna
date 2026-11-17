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

data class CatalogPage(
    val entry: CatalogEntry,
    val tracks: List<Track>,
    val releases: List<CatalogEntry>,
    val artist: CatalogEntry?,
)

interface DesktopCatalogSource {
    suspend fun searchCatalog(query: String, kind: CatalogKind): List<CatalogEntry>

    suspend fun catalogPage(entry: CatalogEntry): CatalogPage
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
