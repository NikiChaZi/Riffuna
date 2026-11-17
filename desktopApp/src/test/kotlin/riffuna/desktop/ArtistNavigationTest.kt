package riffuna.desktop

import kotlin.test.*
import kotlinx.coroutines.runBlocking
import riffuna.core.Track
import riffuna.desktop.ui.ArtistSection
import riffuna.desktop.ui.CatalogNavigation

class ArtistNavigationTest {
    private val dora = CatalogEntry("UCL_z8FNXNugU2FSeChJfdWQ", "Дора", CatalogKind.ARTIST)
    private val other = CatalogEntry("other", "Дора", CatalogKind.ARTIST)
    private val guest = CatalogEntry("guest", "riserayss", CatalogKind.ARTIST)
    private val track = Track("KyJSV3BtymM", "Понарошку", "Дора")

    @Test
    fun linkedArtistWinsOverHomonymsAndSearchOnlyResolvesAUniqueExactMatch() = runBlocking {
        val source = StubCatalog(listOf(dora), listOf(other, dora))
        assertEquals(dora, source.findTrackArtists(track).direct)
        assertEquals(0, source.searches)

        val ambiguous = StubCatalog(emptyList(), listOf(other, dora))
        assertNull(ambiguous.findTrackArtists(track).direct)
        assertEquals(listOf(other, dora), ambiguous.findTrackArtists(track).candidates)

        val collaboration = StubCatalog(listOf(guest, dora), emptyList())
        val selection = collaboration.findTrackArtists(track.copy(artist = "Дора, riserayss"))
        assertNull(selection.direct)
        assertEquals(listOf(guest, dora), selection.candidates)

        val unrelated = StubCatalog(emptyList(), listOf(guest))
        assertNull(unrelated.findTrackArtists(track).direct)
    }

    @Test
    fun navigatingThroughAnAlbumRestoresArtistSectionAndLoadedTracks() {
        val navigation = CatalogNavigation()
        val album = CatalogEntry("release", "LOVESONGS", CatalogKind.ALBUM)
        navigation.open(dora, ArtistSection.SONGS)
        val first = ArtistTracksPage((1..6).map { track.copy(id = "$" + it) }, "next")
        val page = ArtistTracksPage(listOf(first.tracks.last(), track))
        val merged = first.append(page)
        assertEquals(7, merged.tracks.size)
        assertNull(merged.cursor)
        navigation.saveSongs(dora, merged)
        navigation.open(dora, ArtistSection.ALBUMS)
        navigation.open(album)
        navigation.goBack()
        assertEquals(ArtistSection.ALBUMS, navigation.current?.section)
        navigation.goBack()
        assertEquals(ArtistSection.SONGS, navigation.current?.section)
        assertEquals(track, navigation.songsFor(dora)?.tracks?.last())
        navigation.goBack()
        assertNull(navigation.current)
    }

    private class StubCatalog(
        private val linked: List<CatalogEntry>,
        private val candidates: List<CatalogEntry>,
    ) : DesktopCatalogSource {
        var searches = 0
            private set

        override suspend fun searchCatalog(query: String, kind: CatalogKind): List<CatalogEntry> {
            searches++
            return candidates
        }

        override suspend fun trackArtists(track: Track) = linked

        override suspend fun catalogPage(entry: CatalogEntry): CatalogPage = error("Not used")

        override suspend fun artistTracks(entry: CatalogEntry, cursor: String?): ArtistTracksPage =
            error("Not used")
    }
}
