package riffuna.android

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue
import riffuna.catalog.ArtistTracksPage
import riffuna.catalog.CatalogEntry
import riffuna.catalog.CatalogKind
import riffuna.core.Track

class AndroidCatalogNavigationTest {
    private val artist = CatalogEntry("artist", "Artist", CatalogKind.ARTIST)
    private val album = CatalogEntry("album", "Album", CatalogKind.ALBUM)
    private val track = Track("track", "Track", "Artist")

    @Test
    fun directArtistResolutionReplacesLookupAndReleaseReturnsToArtist() {
        val navigation = AndroidCatalogNavigation()
        val lookup = AndroidCatalogDestination.ArtistForTrack(track)
        val artistDetail = AndroidCatalogDestination.Detail(artist)
        navigation.open(lookup, fromPlayer = true)
        navigation.resolve(lookup, artist)
        navigation.open(AndroidCatalogDestination.Detail(album))

        assertFalse(navigation.back())
        assertEquals(artistDetail, navigation.current)
        assertTrue(navigation.back())
        assertNull(navigation.current)
    }

    @Test
    fun artistSongContinuationSurvivesNestedNavigationOnly() {
        val navigation = AndroidCatalogNavigation()
        val songs = AndroidCatalogDestination.Detail(artist, songs = true)
        val page = ArtistTracksPage(listOf(track), cursor = "more")
        navigation.open(AndroidCatalogDestination.Detail(artist))
        navigation.open(songs)
        navigation.saveSongs(artist, page)
        navigation.open(AndroidCatalogDestination.Detail(album))

        navigation.back()
        assertEquals(songs, navigation.current)
        assertEquals(page, navigation.songsFor(artist))
        navigation.clear()
        assertNull(navigation.songsFor(artist))
        assertNull(navigation.current)
    }
}
