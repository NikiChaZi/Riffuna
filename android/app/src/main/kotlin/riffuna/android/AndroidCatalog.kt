package riffuna.android

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.outlined.Album
import androidx.compose.material.icons.outlined.Person
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import coil3.compose.AsyncImage
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch
import riffuna.catalog.*
import riffuna.core.Track

internal enum class AndroidCatalogTab(val label: String, val kind: CatalogKind? = null) {
    TRACKS("Треки"),
    ARTISTS("Исполнители", CatalogKind.ARTIST),
    RELEASES("Релизы", CatalogKind.ALBUM),
}

internal sealed interface AndroidCatalogDestination {
    data class ArtistForTrack(val track: Track) : AndroidCatalogDestination

    data class Detail(val entry: CatalogEntry, val songs: Boolean = false) :
        AndroidCatalogDestination
}

internal class AndroidCatalogNavigation {
    private data class Frame(val destination: AndroidCatalogDestination, val fromPlayer: Boolean)

    private val stack = mutableStateListOf<Frame>()
    private val songs = mutableStateMapOf<String, ArtistTracksPage>()

    val current: AndroidCatalogDestination?
        get() = stack.lastOrNull()?.destination

    fun open(destination: AndroidCatalogDestination, fromPlayer: Boolean = false) {
        if (current != destination || fromPlayer) stack.add(Frame(destination, fromPlayer))
    }

    fun resolve(lookup: AndroidCatalogDestination.ArtistForTrack, entry: CatalogEntry) {
        val frame = stack.lastOrNull() ?: return
        if (frame.destination == lookup) {
            stack[stack.lastIndex] =
                frame.copy(destination = AndroidCatalogDestination.Detail(entry))
        }
    }

    fun back(): Boolean {
        val frame = stack.removeLastOrNull()
        if (stack.isEmpty()) songs.clear()
        return frame?.fromPlayer == true
    }

    fun clear() {
        stack.clear()
        songs.clear()
    }

    fun songsFor(entry: CatalogEntry) = songs[entry.id]

    fun saveSongs(entry: CatalogEntry, page: ArtistTracksPage) {
        songs[entry.id] = page
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun AndroidCatalogTabs(
    selected: AndroidCatalogTab,
    onSelect: (AndroidCatalogTab) -> Unit,
) {
    PrimaryTabRow(selectedTabIndex = selected.ordinal) {
        AndroidCatalogTab.entries.forEach { tab ->
            Tab(
                selected = tab == selected,
                onClick = { onSelect(tab) },
                text = { Text(tab.label, maxLines = 1) },
            )
        }
    }
}

@Composable
internal fun AndroidCatalogResults(
    source: CatalogSource,
    query: String,
    kind: CatalogKind,
    open: (CatalogEntry) -> Unit,
) {
    if (query.isBlank()) {
        Text("Введи название для поиска", Modifier.padding(vertical = 16.dp))
        return
    }
    key(source, query, kind) {
        CatalogLoad({ source.searchCatalog(query, kind) }) { entries ->
            CatalogEntries(entries, open)
        }
    }
}

@Composable
internal fun AndroidCatalogScreen(
    source: CatalogSource,
    destination: AndroidCatalogDestination,
    navigation: AndroidCatalogNavigation,
    onBack: () -> Unit,
    play: (List<Track>, Int) -> Unit,
    trackRow: @Composable (Track, () -> Unit) -> Unit,
) {
    fun open(entry: CatalogEntry) = navigation.open(AndroidCatalogDestination.Detail(entry))

    Column(Modifier.fillMaxSize()) {
        Row(
            Modifier.fillMaxWidth().padding(vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Outlined.ArrowBack, "Назад") }
            Text(
                when (destination) {
                    is AndroidCatalogDestination.ArtistForTrack -> destination.track.artist
                    is AndroidCatalogDestination.Detail ->
                        if (destination.songs) "Песни · ${destination.entry.title}"
                        else destination.entry.title
                },
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.Bold,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
        }
        key(source, destination) {
            when (destination) {
                is AndroidCatalogDestination.ArtistForTrack ->
                    CatalogLoad({ source.findTrackArtists(destination.track) }) { result ->
                        val direct = result.direct
                        if (direct != null) {
                            LaunchedEffect(direct) { navigation.resolve(destination, direct) }
                        } else CatalogEntries(result.candidates, ::open)
                    }
                is AndroidCatalogDestination.Detail -> {
                    val entry = destination.entry
                    if (destination.songs) {
                        ArtistSongs(source, entry, navigation, play, trackRow)
                    } else {
                        CatalogLoad({ source.catalogPage(entry) }) { page ->
                            val isArtist = entry.kind == CatalogKind.ARTIST
                            LazyColumn(
                                verticalArrangement = Arrangement.spacedBy(6.dp),
                                contentPadding = PaddingValues(bottom = 20.dp),
                            ) {
                                item {
                                    CatalogEntryRow(
                                        page.entry,
                                        onOpen = page.artist?.let { artist -> { open(artist) } },
                                        subtitle = page.artist?.title,
                                    )
                                }
                                if (isArtist) item { CatalogSectionTitle("Популярные песни") }
                                val tracks = if (isArtist) page.tracks.take(5) else page.tracks
                                if (tracks.isNotEmpty())
                                    item {
                                        TextButton(onClick = { play(tracks, 0) }) {
                                            Text("Слушать всё")
                                        }
                                    }
                                itemsIndexed(tracks, key = { _, track -> "track:${track.id}" }) {
                                    index,
                                    track ->
                                    trackRow(track) { play(tracks, index) }
                                }
                                if (isArtist) {
                                    item {
                                        TextButton(
                                            onClick = {
                                                navigation.open(
                                                    AndroidCatalogDestination.Detail(
                                                        entry,
                                                        songs = true,
                                                    )
                                                )
                                            }
                                        ) {
                                            Text("Все песни")
                                        }
                                    }
                                    releaseSection(
                                        page.releases,
                                        CatalogKind.ALBUM,
                                        "Альбомы",
                                        ::open,
                                    )
                                    releaseSection(
                                        page.releases,
                                        CatalogKind.SINGLE,
                                        "Синглы и EP",
                                        ::open,
                                    )
                                } else if (tracks.isEmpty())
                                    item { Text("В этом релизе пока нет доступных треков") }
                            }
                        }
                    }
                }
            }
        }
    }
}

private fun LazyListScope.releaseSection(
    entries: List<CatalogEntry>,
    kind: CatalogKind,
    title: String,
    open: (CatalogEntry) -> Unit,
) {
    val releases = entries.filter { it.kind == kind }
    if (releases.isEmpty()) return
    item { CatalogSectionTitle(title) }
    items(releases, key = { "${kind.name}:${it.id}" }) { entry ->
        CatalogEntryRow(entry, { open(entry) })
    }
}

@Composable
private fun CatalogSectionTitle(text: String) {
    Text(
        text,
        Modifier.padding(top = 12.dp),
        style = MaterialTheme.typography.titleMedium,
        fontWeight = FontWeight.SemiBold,
    )
}

@Composable
private fun ArtistSongs(
    source: CatalogSource,
    entry: CatalogEntry,
    navigation: AndroidCatalogNavigation,
    play: (List<Track>, Int) -> Unit,
    trackRow: @Composable (Track, () -> Unit) -> Unit,
) {
    val existing = navigation.songsFor(entry)
    if (existing == null) {
        CatalogLoad({ source.artistTracks(entry) }) { page ->
            LaunchedEffect(page) { navigation.saveSongs(entry, page) }
        }
        return
    }
    val scope = rememberCoroutineScope()
    var loading by remember { mutableStateOf(false) }
    var failed by remember { mutableStateOf(false) }
    val cursor = existing.cursor
    LazyColumn(contentPadding = PaddingValues(bottom = 20.dp)) {
        if (existing.tracks.isNotEmpty())
            item { TextButton(onClick = { play(existing.tracks, 0) }) { Text("Слушать всё") } }
        itemsIndexed(existing.tracks, key = { _, track -> track.id }) { index, track ->
            trackRow(track) { play(existing.tracks, index) }
        }
        item {
            Column(Modifier.fillMaxWidth().padding(vertical = 8.dp)) {
                if (existing.tracks.isEmpty() && !existing.expired) Text("Песни не найдены")
                if (existing.expired) Text("Список устарел. Обнови его, чтобы продолжить.")
                else if (existing.partial && cursor == null) Text("Источник вернул часть песен")
                if (failed)
                    Text("Не удалось загрузить песни", color = MaterialTheme.colorScheme.error)
                if (loading) LinearProgressIndicator(Modifier.fillMaxWidth())
                if (cursor != null || existing.expired)
                    TextButton(
                        enabled = !loading,
                        onClick = {
                            loading = true
                            failed = false
                            scope.launch {
                                try {
                                    val next = source.artistTracks(entry, cursor)
                                    navigation.saveSongs(
                                        entry,
                                        if (existing.expired) next else existing.append(next),
                                    )
                                } catch (cancelled: CancellationException) {
                                    throw cancelled
                                } catch (_: Exception) {
                                    failed = true
                                } finally {
                                    loading = false
                                }
                            }
                        },
                    ) {
                        Text(
                            when {
                                failed -> "Повторить"
                                existing.expired -> "Обновить"
                                else -> "Показать ещё"
                            }
                        )
                    }
            }
        }
    }
}

@Composable
private fun CatalogEntries(entries: List<CatalogEntry>, open: (CatalogEntry) -> Unit) {
    if (entries.isEmpty()) {
        Text("Ничего не найдено", Modifier.padding(vertical = 16.dp))
    } else {
        LazyColumn(contentPadding = PaddingValues(bottom = 20.dp)) {
            items(entries, key = { "${it.kind}:${it.id}" }) { entry ->
                CatalogEntryRow(entry, { open(entry) })
            }
        }
    }
}

@Composable
private fun CatalogEntryRow(entry: CatalogEntry, onOpen: (() -> Unit)?, subtitle: String? = null) {
    val shape = RoundedCornerShape(if (entry.kind == CatalogKind.ARTIST) 28.dp else 12.dp)
    Row(
        Modifier.fillMaxWidth()
            .clip(RoundedCornerShape(14.dp))
            .then(if (onOpen == null) Modifier else Modifier.clickable(onClick = onOpen))
            .padding(vertical = 8.dp, horizontal = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Surface(
            Modifier.size(56.dp),
            shape = shape,
            color = MaterialTheme.colorScheme.surfaceVariant,
        ) {
            if (entry.thumbnail.isBlank()) {
                Box(contentAlignment = Alignment.Center) {
                    Icon(
                        if (entry.kind == CatalogKind.ARTIST) Icons.Outlined.Person
                        else Icons.Outlined.Album,
                        null,
                    )
                }
            } else {
                AsyncImage(entry.thumbnail, null, contentScale = ContentScale.Crop)
            }
        }
        Column(Modifier.weight(1f)) {
            Text(entry.title, maxLines = 2, overflow = TextOverflow.Ellipsis)
            Text(
                listOf(subtitle ?: entry.artistName, entry.kind.label, entry.year)
                    .filter(String::isNotBlank)
                    .joinToString(" · "),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

@Composable
private fun <T : Any> CatalogLoad(load: suspend () -> T, content: @Composable (T) -> Unit) {
    var attempt by remember { mutableIntStateOf(0) }
    var result by remember { mutableStateOf<T?>(null) }
    var failed by remember { mutableStateOf(false) }
    LaunchedEffect(attempt) {
        failed = false
        try {
            result = load()
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (_: Exception) {
            failed = true
        }
    }
    val loaded = result
    when {
        loaded != null -> content(loaded)
        failed ->
            Column(Modifier.padding(vertical = 16.dp)) {
                Text("Не удалось загрузить каталог", color = MaterialTheme.colorScheme.error)
                TextButton(onClick = { attempt++ }) { Text("Повторить") }
            }
        else -> LinearProgressIndicator(Modifier.fillMaxWidth().padding(vertical = 12.dp))
    }
}
