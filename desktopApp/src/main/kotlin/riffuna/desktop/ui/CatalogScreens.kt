package riffuna.desktop.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.LibraryMusic
import androidx.compose.material.icons.outlined.Person
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.CancellationException
import riffuna.core.AppState
import riffuna.core.LibraryView
import riffuna.core.RiffunaController
import riffuna.core.Track
import riffuna.core.isCurrentTrack
import riffuna.desktop.CatalogEntry
import riffuna.desktop.CatalogKind
import riffuna.desktop.CatalogPage
import riffuna.desktop.DesktopCatalogSource

internal enum class CatalogSearchTab(val label: String, val kind: CatalogKind? = null) {
    TRACKS("Треки"),
    ARTISTS("Исполнители", CatalogKind.ARTIST),
    RELEASES("Альбомы и синглы", CatalogKind.ALBUM),
}

internal class CatalogNavigation {
    var tab by mutableStateOf(CatalogSearchTab.TRACKS)
        private set

    var current by mutableStateOf<CatalogEntry?>(null)
        private set

    private val back = mutableStateListOf<CatalogEntry?>()
    private val forward = mutableStateListOf<CatalogEntry?>()
    val canGoBack: Boolean
        get() = back.isNotEmpty()

    val canGoForward: Boolean
        get() = forward.isNotEmpty()

    fun open(entry: CatalogEntry) {
        if (current?.id == entry.id) return
        back.add(current)
        current = entry
        forward.clear()
    }

    fun goBack() {
        if (!canGoBack) return
        forward.add(current)
        current = back.removeAt(back.lastIndex)
    }

    fun goForward() {
        if (!canGoForward) return
        back.add(current)
        current = forward.removeAt(forward.lastIndex)
    }

    fun selectTab(selected: CatalogSearchTab) {
        if (tab == selected) return
        tab = selected
        forward.clear()
    }

    fun reset() {
        current = null
        tab = CatalogSearchTab.TRACKS
        back.clear()
        forward.clear()
    }
}

@Composable
internal fun CatalogHost(
    source: DesktopCatalogSource?,
    navigation: CatalogNavigation,
    controller: RiffunaController,
    state: AppState,
    onPlaylist: (List<Track>) -> Unit,
    onOpenTrack: (Track) -> Unit,
    fallback: @Composable () -> Unit,
) {
    if (
        source == null ||
            state.view != LibraryView.SEARCH ||
            state.query.isBlank() ||
            state.query.contains("://")
    ) {
        fallback()
        return
    }
    val entry = navigation.current
    if (entry != null) {
        CatalogPageScreen(
            source,
            entry,
            controller,
            state,
            navigation::open,
            onPlaylist,
            onOpenTrack,
        )
        return
    }
    Column(Modifier.fillMaxSize()) {
        CatalogSearchTabs(navigation.tab, navigation::selectTab)
        Box(Modifier.weight(1f)) {
            val kind = navigation.tab.kind
            if (kind == null) fallback()
            else CatalogResults(source, state.query, kind, navigation::open)
        }
    }
}

@Composable
internal fun CatalogSearchTabs(selected: CatalogSearchTab, onTab: (CatalogSearchTab) -> Unit) {
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        CatalogSearchTab.entries.forEach { tab ->
            FilterChip(
                selected = selected == tab,
                onClick = { onTab(tab) },
                label = { Text(tab.label) },
            )
        }
    }
}

@Composable
private fun <T> CatalogLoad(onLoad: suspend () -> T, content: @Composable (T) -> Unit) {
    var attempt by remember { mutableIntStateOf(0) }
    val result by
        produceState<Result<T>?>(null, attempt) {
            value = null
            value =
                try {
                    Result.success(onLoad())
                } catch (cancelled: CancellationException) {
                    throw cancelled
                } catch (failure: Exception) {
                    Result.failure(failure)
                }
        }
    val response = result
    when {
        response == null ->
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator(Modifier.size(28.dp))
            }
        response.isFailure ->
            EmptyState(
                Icons.Outlined.LibraryMusic,
                "Каталог недоступен",
                "Проверь подключение и попробуй ещё раз.",
                "Повторить",
                { attempt++ },
            )
        else -> content(response.getOrThrow())
    }
}

@Composable
internal fun CatalogResults(
    source: DesktopCatalogSource,
    query: String,
    kind: CatalogKind,
    onOpen: (CatalogEntry) -> Unit,
) {
    key(query, kind) {
        CatalogLoad({ source.searchCatalog(query, kind) }) { entries ->
            if (entries.isEmpty()) {
                EmptyState(
                    if (kind == CatalogKind.ARTIST) Icons.Outlined.Person
                    else Icons.Outlined.LibraryMusic,
                    "Ничего не найдено",
                    "Попробуй уточнить название или имя исполнителя.",
                )
            } else {
                LazyColumn(
                    Modifier.fillMaxSize(),
                    verticalArrangement = Arrangement.spacedBy(4.dp),
                    contentPadding = PaddingValues(vertical = 12.dp),
                ) {
                    items(entries, key = { it.id }) { entry ->
                        CatalogEntryRow(entry, onOpen = { onOpen(entry) })
                    }
                }
            }
        }
    }
}

@Composable
private fun CatalogEntryRow(entry: CatalogEntry, onOpen: () -> Unit) {
    Surface(
        modifier = Modifier.fillMaxWidth().clickable(onClick = onOpen),
        shape = RoundedCornerShape(10.dp),
        color = RiffunaColors.Raised,
    ) {
        Row(
            Modifier.padding(horizontal = 12.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Artwork(entry.thumbnail, Modifier.size(48.dp), entry.title, 6.dp)
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(
                    entry.title,
                    style = MaterialTheme.typography.titleSmall,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                val detail = listOf(entry.kind.label, entry.artistName, entry.year)
                Text(
                    detail.filter(String::isNotBlank).joinToString(" · "),
                    color = RiffunaColors.Secondary,
                    style = MaterialTheme.typography.bodySmall,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
    }
}

@Composable
internal fun CatalogPageScreen(
    source: DesktopCatalogSource,
    entry: CatalogEntry,
    controller: RiffunaController,
    state: AppState,
    onCatalogOpen: (CatalogEntry) -> Unit,
    onPlaylist: (List<Track>) -> Unit,
    onOpenTrack: (Track) -> Unit,
) {
    key(entry.id) {
        CatalogLoad({ source.catalogPage(entry) }) { page ->
            CatalogPageContent(page, controller, state, onCatalogOpen, onPlaylist, onOpenTrack)
        }
    }
}

@Composable
private fun CatalogPageContent(
    page: CatalogPage,
    controller: RiffunaController,
    state: AppState,
    onCatalogOpen: (CatalogEntry) -> Unit,
    onPlaylist: (List<Track>) -> Unit,
    onOpenTrack: (Track) -> Unit,
) {
    val entry = page.entry
    var selectedId by remember(entry.id) { mutableStateOf<String?>(null) }
    LazyColumn(
        Modifier.fillMaxSize(),
        verticalArrangement = Arrangement.spacedBy(4.dp),
        contentPadding = PaddingValues(bottom = 18.dp),
    ) {
        item("header") {
            Row(
                Modifier.padding(top = 8.dp, bottom = 20.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(20.dp),
            ) {
                Artwork(entry.thumbnail, Modifier.size(126.dp), entry.title, 12.dp)
                Column(verticalArrangement = Arrangement.spacedBy(7.dp)) {
                    Text(entry.kind.label, color = RiffunaColors.Secondary)
                    Text(entry.title, style = MaterialTheme.typography.headlineMedium)
                    val artist = page.artist
                    if (artist != null && artist.id != entry.id) {
                        Text(
                            artist.title,
                            Modifier.clickable { onCatalogOpen(artist) },
                            color = RiffunaColors.Coral,
                        )
                    } else if (entry.artistName.isNotBlank()) {
                        Text(entry.artistName, color = RiffunaColors.Secondary)
                    }
                    if (entry.year.isNotBlank()) Text(entry.year, color = RiffunaColors.Secondary)
                    if (page.tracks.isNotEmpty())
                        Button(onClick = { controller.playContext(page.tracks) }) {
                            Text("Слушать")
                        }
                }
            }
        }
        if (page.tracks.isNotEmpty()) {
            item("tracks-heading") {
                SectionTitle(if (entry.kind == CatalogKind.ARTIST) "Популярные треки" else "Треки")
            }
            itemsIndexed(page.tracks, key = { _, track -> "track-" + track.id }) { index, track ->
                TrackRow(
                    track,
                    index,
                    isCurrentTrack(state, track),
                    state.playing,
                    state.likes.any { it.id == track.id },
                    selectedId == track.id,
                    onPlay = { controller.playContext(page.tracks, index) },
                    onSelect = { _, _ -> selectedId = track.id },
                    onLike = { controller.toggleLike(track) },
                    onQueue = { controller.enqueue(track) },
                    onNext = { controller.playNext(track) },
                    onPlaylist = { onPlaylist(listOf(track)) },
                    onVersions = { controller.findVersions(track) },
                    onArtist = {
                        val artist = page.artist
                        when {
                            artist != null -> onCatalogOpen(artist)
                            entry.kind == CatalogKind.ARTIST -> Unit
                            else -> controller.search(track.artist)
                        }
                    },
                    onOpen = { onOpenTrack(track) },
                )
            }
        }
        if (page.releases.isNotEmpty()) {
            val groups = page.releases.groupBy { it.kind }
            for ((kind, heading) in
                listOf(CatalogKind.ALBUM to "Альбомы", CatalogKind.SINGLE to "Синглы и EP")) {
                val releases = groups[kind].orEmpty()
                if (releases.isEmpty()) continue
                item("releases-" + kind.name) { SectionTitle(heading) }
                items(releases, key = { "release-" + it.id }) { release ->
                    CatalogEntryRow(release, onOpen = { onCatalogOpen(release) })
                }
            }
        }
        if (page.tracks.isEmpty() && page.releases.isEmpty()) {
            item("empty") {
                EmptyState(
                    Icons.Outlined.LibraryMusic,
                    "Здесь пока нет записей",
                    "Проверь результаты поиска по названию или исполнителю.",
                )
            }
        }
    }
}
