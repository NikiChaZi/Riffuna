package riffuna.desktop

import riffuna.catalog.findTrackArtists as findSharedTrackArtists
import riffuna.core.Track

typealias DesktopCatalogSource = riffuna.catalog.CatalogSource

typealias CatalogKind = riffuna.catalog.CatalogKind

typealias CatalogEntry = riffuna.catalog.CatalogEntry

typealias CatalogPage = riffuna.catalog.CatalogPage

typealias ArtistTracksPage = riffuna.catalog.ArtistTracksPage

internal suspend fun DesktopCatalogSource.findTrackArtists(track: Track) =
    findSharedTrackArtists(track)
