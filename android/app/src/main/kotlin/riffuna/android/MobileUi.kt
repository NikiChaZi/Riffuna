package riffuna.android

import androidx.activity.compose.BackHandler
import androidx.compose.animation.*
import androidx.compose.animation.core.*
import androidx.compose.foundation.*
import androidx.compose.foundation.gestures.detectDragGesturesAfterLongPress
import androidx.compose.foundation.gestures.scrollBy
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.*
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.lerp
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.compose.ui.zIndex
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import coil3.compose.AsyncImage
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.isActive
import riffuna.core.*

private val Coral = Color(0xFFFF875F)
private val Graphite = Color(0xFF111613)
private val Panel = Color(0xFF202820)
private val Warm = Color(0xFFF2F0E7)

@Composable
internal fun RiffunaTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme =
            darkColorScheme(
                primary = Coral,
                onPrimary = Graphite,
                background = Graphite,
                surface = Graphite,
                surfaceContainer = Panel,
                surfaceContainerLowest = Color(0xFF0C100E),
                surfaceContainerLow = Color(0xFF1A211A),
                surfaceContainerHigh = Color(0xFF283127),
                surfaceContainerHighest = Color(0xFF303A2F),
                surfaceBright = Color(0xFF303A2F),
                surfaceDim = Graphite,
                surfaceTint = Coral,
                inverseSurface = Warm,
                inverseOnSurface = Graphite,
                outline = Color(0xFF697465),
                outlineVariant = Color(0xFF3C4739),
                onSurface = Warm,
                onBackground = Warm,
                secondary = Color(0xFFB6C5AE),
                onSecondary = Graphite,
                secondaryContainer = Panel,
                onSecondaryContainer = Warm,
                primaryContainer = Color(0xFF443025),
                onPrimaryContainer = Coral,
                tertiary = Color(0xFFB6C5AE),
                onTertiary = Graphite,
                tertiaryContainer = Panel,
                onTertiaryContainer = Warm,
                surfaceVariant = Panel,
                onSurfaceVariant = Color(0xFFAFBAAD),
            ),
        content = content,
    )
}

@Composable
private fun Cover(track: Track?, size: Int, modifier: Modifier = Modifier) {
    val density = androidx.compose.ui.platform.LocalDensity.current
    val pixels = with(density) { size.dp.roundToPx() }
    val url = track?.thumbnail.orEmpty()
    val candidates = remember(url, pixels) { ArtworkRequests.candidates(url, pixels) }
    var candidateIndex by remember(candidates) { mutableIntStateOf(0) }
    val candidate = candidates.getOrNull(candidateIndex)
    Box(
        modifier.size(size.dp).clip(RoundedCornerShape((size / 8).dp)).background(Panel),
        contentAlignment = Alignment.Center,
    ) {
        if (candidate?.startsWith("https://") == true)
            AsyncImage(
                candidate,
                contentDescription = null,
                modifier = Modifier.fillMaxSize(),
                contentScale = ContentScale.Crop,
                filterQuality = androidx.compose.ui.graphics.FilterQuality.High,
                onError = { if (candidateIndex < candidates.lastIndex) candidateIndex++ },
                onSuccess = { state ->
                    val image = state.result.image
                    if (
                        ArtworkRequests.isPlaceholder(candidate, image.width, image.height) &&
                            candidateIndex < candidates.lastIndex
                    )
                        candidateIndex++
                },
            )
        else
            Icon(
                Icons.Outlined.MusicNote,
                null,
                tint = Coral,
                modifier = Modifier.size((size / 2).dp),
            )
    }
}

private fun time(ms: Long): String {
    val s = (ms / 1000).coerceAtLeast(0)
    return "%d:%02d".format(s / 60, s % 60)
}

@Composable
internal fun MobileApp(controller: LocalController, importFiles: () -> Unit) {
    val screen =
        remember(controller) { controller.state.map { it.screenSnapshot() }.distinctUntilChanged() }
    val state by screen.collectAsStateWithLifecycle(AppState())
    var playlistName by remember { mutableStateOf<String?>(null) }
    var playlistTracks by remember { mutableStateOf<List<Track>?>(null) }
    var editingPlaylist by remember { mutableStateOf<PlaylistSummary?>(null) }
    var deletingPlaylist by remember { mutableStateOf<PlaylistSummary?>(null) }
    var settings by remember { mutableStateOf(false) }
    val snackbar = remember { SnackbarHostState() }
    LaunchedEffect(state.toast) { if (state.toast.isNotBlank()) snackbar.showSnackbar(state.toast) }
    BackHandler(state.expanded || state.selectedIds.isNotEmpty() || state.canGoBack) {
        if (state.expanded) controller.openNowPlaying(false)
        else if (state.selectedIds.isNotEmpty()) controller.clearSelection()
        else controller.navigateBack()
    }
    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        bottomBar = {
            Column {
                AnimatedVisibility(
                    visible = state.current != null,
                    enter =
                        if (state.reducedMotion) EnterTransition.None
                        else fadeIn() + expandVertically(),
                    exit =
                        if (state.reducedMotion) ExitTransition.None
                        else fadeOut() + shrinkVertically(),
                ) {
                    MiniPlayer(controller)
                }
                NavigationBar(containerColor = Graphite, tonalElevation = 0.dp) {
                    listOf(
                            Triple(LibraryView.HOME, "Главная", Icons.Outlined.Home),
                            Triple(LibraryView.SEARCH, "Поиск", Icons.Outlined.Search),
                            Triple(
                                LibraryView.PLAYLISTS,
                                "Библиотека",
                                Icons.Outlined.LibraryMusic,
                            ),
                            Triple(
                                LibraryView.QUEUE,
                                "Очередь",
                                Icons.AutoMirrored.Outlined.QueueMusic,
                            ),
                        )
                        .forEach { (view, label, icon) ->
                            NavigationBarItem(
                                selected =
                                    state.view == view ||
                                        (view == LibraryView.PLAYLISTS &&
                                            state.view in
                                                setOf(
                                                    LibraryView.LIKES,
                                                    LibraryView.HISTORY,
                                                    LibraryView.LOCAL,
                                                    LibraryView.PLAYLIST,
                                                )),
                                onClick = { controller.showView(view) },
                                icon = { Icon(icon, null) },
                                label = { Text(label, maxLines = 1) },
                                colors =
                                    NavigationBarItemDefaults.colors(
                                        selectedIconColor = Coral,
                                        selectedTextColor = Warm,
                                        indicatorColor = Panel,
                                        unselectedIconColor =
                                            MaterialTheme.colorScheme.onSurfaceVariant,
                                        unselectedTextColor =
                                            MaterialTheme.colorScheme.onSurfaceVariant,
                                    ),
                            )
                        }
                }
            }
        },
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding).padding(horizontal = 20.dp)) {
            Row(
                Modifier.fillMaxWidth().padding(top = 14.dp, bottom = 16.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    when (state.view) {
                        LibraryView.HOME -> "riffuna"
                        LibraryView.SEARCH -> "Поиск"
                        LibraryView.PLAYLISTS -> "Библиотека"
                        LibraryView.LIKES -> "Любимое"
                        LibraryView.HISTORY -> "Недавно слушал"
                        LibraryView.LOCAL -> "На устройстве"
                        LibraryView.QUEUE -> "Очередь"
                        else -> "Твоя музыка"
                    },
                    fontSize = 28.sp,
                    fontWeight = FontWeight.Bold,
                    letterSpacing = (-1).sp,
                    modifier = Modifier.weight(1f),
                )
                IconButton(onClick = { controller.showView(LibraryView.LOCAL) }) {
                    Icon(Icons.Outlined.FolderOpen, "Локальные файлы")
                }
                IconButton(onClick = { controller.showView(LibraryView.PLAYLISTS) }) {
                    Icon(Icons.Outlined.LibraryMusic, "Плейлисты")
                }
                IconButton(onClick = { settings = true }) { Icon(Icons.Outlined.Tune, "Настройки") }
            }
            when (state.view) {
                LibraryView.HOME ->
                    LazyColumn(verticalArrangement = Arrangement.spacedBy(18.dp)) {
                        item {
                            Text(
                                "Слушать дальше",
                                fontSize = 28.sp,
                                lineHeight = 34.sp,
                                fontWeight = FontWeight.SemiBold,
                            )
                        }
                        item {
                            Row(
                                Modifier.horizontalScroll(rememberScrollState()),
                                horizontalArrangement = Arrangement.spacedBy(10.dp),
                            ) {
                                FilledTonalButton(
                                    onClick = { controller.showView(LibraryView.HISTORY) }
                                ) {
                                    Text("Недавно слушал")
                                }
                                OutlinedButton(onClick = importFiles) { Text("Добавить файлы") }
                            }
                        }
                        if (state.history.isNotEmpty())
                            item {
                                LazyRow(horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                                    items(state.history.take(8), key = { it.id }) { track ->
                                        Column(
                                            Modifier.width(156.dp)
                                                .clip(RoundedCornerShape(22.dp))
                                                .background(Panel)
                                                .clickable { controller.play(track) }
                                                .padding(10.dp)
                                        ) {
                                            Cover(track, 136)
                                            Spacer(Modifier.height(12.dp))
                                            Text(
                                                track.title,
                                                maxLines = 1,
                                                overflow = TextOverflow.Ellipsis,
                                                fontWeight = FontWeight.SemiBold,
                                            )
                                            Text(
                                                track.artist,
                                                maxLines = 1,
                                                overflow = TextOverflow.Ellipsis,
                                                color = Color(0xFFAFBAAD),
                                                fontSize = 12.sp,
                                            )
                                            Spacer(Modifier.height(6.dp))
                                        }
                                    }
                                }
                            }
                        if (state.history.isNotEmpty()) {
                            item {
                                Text(
                                    "Вернуться к музыке",
                                    fontSize = 20.sp,
                                    fontWeight = FontWeight.SemiBold,
                                )
                            }
                            items(state.history.take(12), key = { it.id }) { track ->
                                TrackRow(
                                    track,
                                    state,
                                    controller,
                                    onPlaylist = { playlistTracks = listOf(track) },
                                )
                            }
                        } else
                            item {
                                Card(colors = CardDefaults.cardColors(containerColor = Panel)) {
                                    Column(Modifier.padding(20.dp)) {
                                        Text("Начнём с любимой песни", fontSize = 20.sp)
                                        Spacer(Modifier.height(8.dp))
                                        Text(
                                            "Найди музыку или добавь файлы с телефона. Здесь появится твоя история."
                                        )
                                        Button(
                                            onClick = { controller.showView(LibraryView.SEARCH) }
                                        ) {
                                            Text("Найти музыку")
                                        }
                                    }
                                }
                            }
                        if (state.likes.isNotEmpty()) {
                            item {
                                Text("Любимое", fontSize = 20.sp, fontWeight = FontWeight.SemiBold)
                            }
                            items(state.likes.take(6), key = { "like:" + it.id }) { track ->
                                TrackRow(
                                    track,
                                    state,
                                    controller,
                                    onPlaylist = { playlistTracks = listOf(track) },
                                )
                            }
                        }
                    }
                LibraryView.PLAYLISTS -> {
                    Row(
                        Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        AssistChip(
                            onClick = { controller.showView(LibraryView.LIKES) },
                            label = { Text("Любимое · ${state.likes.size}") },
                            leadingIcon = {
                                Icon(Icons.Outlined.FavoriteBorder, null, Modifier.size(18.dp))
                            },
                        )
                        AssistChip(
                            onClick = { controller.showView(LibraryView.HISTORY) },
                            label = { Text("История") },
                            leadingIcon = {
                                Icon(Icons.Outlined.History, null, Modifier.size(18.dp))
                            },
                        )
                        AssistChip(
                            onClick = { controller.showView(LibraryView.LOCAL) },
                            label = { Text("На устройстве") },
                            leadingIcon = {
                                Icon(Icons.Outlined.FolderOpen, null, Modifier.size(18.dp))
                            },
                        )
                    }
                    Spacer(Modifier.height(12.dp))
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(
                            "Плейлисты",
                            fontSize = 26.sp,
                            fontWeight = FontWeight.Bold,
                            modifier = Modifier.weight(1f),
                        )
                        IconButton(onClick = { playlistName = "" }) {
                            Icon(Icons.Outlined.Add, "Создать плейлист")
                        }
                    }
                    LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        if (state.playlists.isEmpty())
                            item {
                                Column(Modifier.fillMaxWidth().padding(vertical = 36.dp)) {
                                    Icon(
                                        Icons.Outlined.LibraryMusic,
                                        null,
                                        Modifier.size(40.dp),
                                        tint = Coral,
                                    )
                                    Spacer(Modifier.height(12.dp))
                                    Text(
                                        "Собери своё настроение",
                                        fontSize = 22.sp,
                                        fontWeight = FontWeight.SemiBold,
                                    )
                                    Text(
                                        "Создай плейлист и добавляй в него песни через меню трека.",
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    )
                                    Spacer(Modifier.height(12.dp))
                                    FilledTonalButton(onClick = { playlistName = "" }) {
                                        Text("Создать плейлист")
                                    }
                                }
                            }
                        items(state.playlists, key = { it.id }) { p ->
                            var menu by remember { mutableStateOf(false) }
                            ListItem(
                                headlineContent = { Text(p.name) },
                                supportingContent = { Text("${p.trackCount} треков") },
                                leadingContent = {
                                    Cover(
                                        Track("playlist:${p.id}", p.name, thumbnail = p.thumbnail),
                                        56,
                                    )
                                },
                                colors = ListItemDefaults.colors(containerColor = Panel),
                                modifier =
                                    Modifier.clip(RoundedCornerShape(18.dp)).clickable {
                                        controller.openPlaylist(p.id)
                                    },
                                trailingContent = {
                                    Box {
                                        IconButton(onClick = { menu = true }) {
                                            Icon(Icons.Outlined.MoreVert, "Действия с плейлистом")
                                        }
                                        DropdownMenu(menu, { menu = false }) {
                                            DropdownMenuItem(
                                                text = { Text("Изменить") },
                                                onClick = {
                                                    menu = false
                                                    editingPlaylist = p
                                                },
                                            )
                                            DropdownMenuItem(
                                                text = { Text("Сделать копию") },
                                                onClick = {
                                                    menu = false
                                                    controller.duplicatePlaylist(p.id)
                                                },
                                            )
                                            DropdownMenuItem(
                                                text = { Text("Удалить") },
                                                onClick = {
                                                    menu = false
                                                    deletingPlaylist = p
                                                },
                                            )
                                        }
                                    }
                                },
                            )
                        }
                    }
                }
                else -> {
                    if (state.view == LibraryView.SEARCH) {
                        var query by remember { mutableStateOf(state.query) }
                        OutlinedTextField(
                            query,
                            { query = it },
                            modifier = Modifier.fillMaxWidth(),
                            singleLine = true,
                            placeholder = { Text("Трек или исполнитель") },
                            shape = RoundedCornerShape(18.dp),
                            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
                            keyboardActions =
                                KeyboardActions(onSearch = { controller.search(query) }),
                            trailingIcon = {
                                IconButton(onClick = { controller.search(query) }) {
                                    Icon(Icons.Outlined.Search, "Найти")
                                }
                            },
                        )
                        Spacer(Modifier.height(16.dp))
                    }
                    val title =
                        when (state.view) {
                            LibraryView.SEARCH -> "Результаты"
                            LibraryView.LIKES -> "Мне нравится"
                            LibraryView.QUEUE -> "Очередь"
                            LibraryView.LOCAL -> "На устройстве"
                            LibraryView.HISTORY -> "История"
                            LibraryView.PLAYLIST ->
                                state.playlists.firstOrNull { it.id == state.playlistId }?.name
                                    ?: "Плейлист"
                            else -> "Музыка"
                        }
                    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                        Text(
                            title,
                            fontSize = 24.sp,
                            fontWeight = FontWeight.Bold,
                            modifier = Modifier.weight(1f),
                        )
                        if (state.view == LibraryView.LOCAL)
                            IconButton(onClick = importFiles) {
                                Icon(Icons.Outlined.Add, "Добавить аудиофайлы")
                            }
                        if (state.view == LibraryView.PLAYLIST)
                            IconButton(
                                onClick = {
                                    editingPlaylist =
                                        state.playlists.firstOrNull { it.id == state.playlistId }
                                }
                            ) {
                                Icon(Icons.Outlined.Edit, "Изменить плейлист")
                            }
                        if (state.view == LibraryView.QUEUE && state.queue.isNotEmpty())
                            TextButton(onClick = controller::clearQueue) { Text("Очистить") }
                    }
                    val tracks =
                        if (state.view == LibraryView.QUEUE) state.queue else displayedTracks(state)
                    if (tracks.isNotEmpty())
                        Row(
                            Modifier.fillMaxWidth().padding(vertical = 8.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Button(
                                onClick = {
                                    if (state.view == LibraryView.QUEUE) controller.playQueue()
                                    else controller.playAll()
                                }
                            ) {
                                Icon(Icons.Outlined.PlayArrow, null)
                                Text("Слушать всё")
                            }
                            Spacer(Modifier.width(8.dp))
                            Text(
                                "${tracks.size} треков",
                                color = Color(0xFFAFBAAD),
                                modifier = Modifier.weight(1f),
                            )
                            if (state.view != LibraryView.QUEUE) LibrarySort(state, controller)
                        }
                    if (state.selectedIds.isNotEmpty()) {
                        SelectionActions(state, controller) { playlistTracks = it }
                    }
                    if (state.searchLoading || state.localImporting)
                        LinearProgressIndicator(Modifier.fillMaxWidth().padding(vertical = 12.dp))
                    if (
                        (tracks.isNotEmpty() || state.localFilter.isNotBlank()) &&
                            state.view != LibraryView.QUEUE
                    ) {
                        OutlinedTextField(
                            state.localFilter,
                            controller::setLocalFilter,
                            modifier = Modifier.fillMaxWidth().padding(vertical = 8.dp),
                            singleLine = true,
                            placeholder = { Text("Фильтр списка") },
                            leadingIcon = { Icon(Icons.Outlined.FilterList, null) },
                            shape = RoundedCornerShape(16.dp),
                        )
                    }
                    if (tracks.isEmpty() && !state.searchLoading)
                        Box(
                            Modifier.weight(1f).fillMaxWidth(),
                            contentAlignment = Alignment.Center,
                        ) {
                            Text(
                                if (state.view == LibraryView.SEARCH)
                                    "Найди то, что хочется услышать"
                                else "Здесь пока нет музыки",
                                color = Color(0xFFAFBAAD),
                            )
                        }
                    else if (state.view == LibraryView.QUEUE)
                        QueueTracks(state, controller, Modifier.weight(1f)) {
                            playlistTracks = listOf(it)
                        }
                    else
                        key(state.view, state.playlistId) {
                            LazyColumn(
                                Modifier.weight(1f),
                                verticalArrangement = Arrangement.spacedBy(4.dp),
                            ) {
                                items(tracks, key = { it.id }) { track ->
                                    TrackRow(
                                        track,
                                        state,
                                        controller,
                                        onPlaylist = { playlistTracks = listOf(track) },
                                    )
                                }
                                if (state.view == LibraryView.SEARCH && state.canLoadMore)
                                    item {
                                        TextButton(
                                            onClick = controller::loadMore,
                                            modifier = Modifier.fillMaxWidth(),
                                        ) {
                                            Text("Показать ещё")
                                        }
                                    }
                                item { Spacer(Modifier.height(20.dp)) }
                            }
                        }
                }
            }
        }
    }
    if (state.expanded) NowPlaying(controller) { controller.openNowPlaying(false) }
    if (state.versionReference != null) RecordingVersions(state, controller)
    editingPlaylist?.let { playlist ->
        var name by remember(playlist.id) { mutableStateOf(playlist.name) }
        var description by remember(playlist.id) { mutableStateOf(playlist.description) }
        AlertDialog(
            onDismissRequest = { editingPlaylist = null },
            title = { Text("Твой плейлист") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    OutlinedTextField(
                        name,
                        { name = it },
                        label = { Text("Название") },
                        singleLine = true,
                    )
                    OutlinedTextField(
                        description,
                        { description = it },
                        label = { Text("Описание") },
                        maxLines = 4,
                    )
                }
            },
            confirmButton = {
                TextButton(
                    enabled = name.isNotBlank(),
                    onClick = {
                        controller.editPlaylist(playlist.id, name, description)
                        editingPlaylist = null
                    },
                ) {
                    Text("Сохранить")
                }
            },
            dismissButton = { TextButton(onClick = { editingPlaylist = null }) { Text("Отмена") } },
        )
    }
    deletingPlaylist?.let { playlist ->
        AlertDialog(
            onDismissRequest = { deletingPlaylist = null },
            title = { Text("Удалить «${playlist.name}»?") },
            text = { Text("Треки останутся в истории и любимом.") },
            confirmButton = {
                TextButton(
                    onClick = {
                        controller.deletePlaylist(playlist.id)
                        deletingPlaylist = null
                    }
                ) {
                    Text("Удалить")
                }
            },
            dismissButton = { TextButton(onClick = { deletingPlaylist = null }) { Text("Отмена") } },
        )
    }
    if (settings)
        AlertDialog(
            onDismissRequest = { settings = false },
            title = { Text("Riffuna на твоём устройстве") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {
                    Text(
                        "Библиотека хранится на телефоне. Полностью загруженные треки доступны из кэша до 512 МБ. Android может освободить этот кэш при нехватке места."
                    )
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("Уменьшить анимации", Modifier.weight(1f))
                        Switch(state.reducedMotion, controller::setReducedMotion)
                    }
                    Text(
                        "Для YouTube требуется доступ к сервису через сеть телефона. Синхронизации с библиотекой Windows пока нет.",
                        color = Color(0xFFAFBAAD),
                        fontSize = 13.sp,
                    )
                }
            },
            confirmButton = { TextButton(onClick = { settings = false }) { Text("Готово") } },
        )
    if (playlistName != null)
        AlertDialog(
            onDismissRequest = { playlistName = null },
            title = { Text("Новый плейлист") },
            text = {
                OutlinedTextField(
                    playlistName.orEmpty(),
                    { playlistName = it },
                    singleLine = true,
                    label = { Text("Название") },
                )
            },
            confirmButton = {
                TextButton(
                    enabled = !playlistName.isNullOrBlank(),
                    onClick = {
                        controller.createPlaylist(playlistName.orEmpty())
                        playlistName = null
                    },
                ) {
                    Text("Создать")
                }
            },
            dismissButton = { TextButton(onClick = { playlistName = null }) { Text("Отмена") } },
        )
    playlistTracks?.let { selection ->
        AlertDialog(
            onDismissRequest = { playlistTracks = null },
            title = { Text("Добавить в плейлист") },
            text = {
                Column {
                    if (state.playlists.isEmpty()) Text("Сначала создай плейлист в библиотеке")
                    state.playlists.forEach { p ->
                        TextButton(
                            onClick = {
                                controller.addToPlaylist(p.id, selection)
                                controller.clearSelection()
                                playlistTracks = null
                            }
                        ) {
                            Text(p.name)
                        }
                    }
                }
            },
            confirmButton = { TextButton(onClick = { playlistTracks = null }) { Text("Закрыть") } },
        )
    }
}

@Composable
private fun SelectionActions(
    state: AppState,
    c: LocalController,
    onPlaylist: (List<Track>) -> Unit,
) {
    val tracks = if (state.view == LibraryView.QUEUE) state.queue else displayedTracks(state)
    val selectedTracks = tracks.filter { it.id in state.selectedIds }
    Surface(color = Panel, shape = RoundedCornerShape(16.dp)) {
        Row(
            Modifier.fillMaxWidth()
                .horizontalScroll(rememberScrollState())
                .padding(horizontal = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = c::clearSelection) {
                Icon(Icons.Outlined.Close, "Снять выделение")
            }
            Text("${selectedTracks.size}", fontWeight = FontWeight.SemiBold)
            TextButton(onClick = c::selectAll) { Text("Все") }
            IconButton(
                onClick = {
                    selectedTracks
                        .filter { track -> state.likes.none { it.id == track.id } }
                        .forEach(c::toggleLike)
                }
            ) {
                Icon(Icons.Outlined.FavoriteBorder, "Добавить выбранные в любимое")
            }
            IconButton(onClick = { c.enqueueMany(selectedTracks) }) {
                Icon(Icons.Outlined.PlaylistAdd, "Добавить выбранные в очередь")
            }
            IconButton(onClick = { onPlaylist(selectedTracks) }) {
                Icon(Icons.Outlined.LibraryMusic, "Добавить выбранные в плейлист")
            }
            if (state.view in setOf(LibraryView.LIKES, LibraryView.PLAYLIST, LibraryView.QUEUE))
                IconButton(
                    onClick = {
                        if (state.view == LibraryView.QUEUE) {
                            selectedTracks.forEach { c.removeFromQueue(it.id) }
                            c.clearSelection()
                        } else c.removeSelected()
                    }
                ) {
                    Icon(Icons.Outlined.DeleteOutline, "Убрать выбранные")
                }
        }
    }
}

@Composable
private fun QueueTracks(
    state: AppState,
    c: LocalController,
    modifier: Modifier,
    onPlaylist: (Track) -> Unit,
) {
    val list = rememberLazyListState()
    val density = LocalDensity.current
    val edge = with(density) { 56.dp.toPx() }
    var draggedId by remember { mutableStateOf<String?>(null) }
    var dragCenter by remember { mutableFloatStateOf(0f) }
    fun moveAtPointer() {
        val id = draggedId ?: return
        val visible = list.layoutInfo.visibleItemsInfo
        val target =
            visible.minByOrNull { kotlin.math.abs(dragCenter - it.offset - it.size / 2f) } ?: return
        val queue = c.state.value.queue
        val from = queue.indexOfFirst { it.id == id }
        val to = queue.indexOfFirst { it.id == target.key }
        if (from >= 0 && to >= 0 && from != to) {
            val ids = queue.map { it.id }.toMutableList()
            ids.add(to, ids.removeAt(from))
            c.reorderQueue(ids)
        }
    }
    LaunchedEffect(draggedId) {
        if (draggedId == null) return@LaunchedEffect
        while (isActive) {
            val layout = list.layoutInfo
            val top = layout.viewportStartOffset + edge
            val bottom = layout.viewportEndOffset - edge
            val scroll =
                when {
                    dragCenter < top -> -((top - dragCenter) / 4f).coerceIn(2f, 24f)
                    dragCenter > bottom -> ((dragCenter - bottom) / 4f).coerceIn(2f, 24f)
                    else -> 0f
                }
            if (scroll != 0f) {
                list.scrollBy(scroll)
                moveAtPointer()
            }
            delay(16)
        }
    }
    LazyColumn(
        modifier.fillMaxWidth(),
        state = list,
        verticalArrangement = Arrangement.spacedBy(4.dp),
        contentPadding = PaddingValues(bottom = 20.dp),
    ) {
        items(state.queue, key = { it.id }) { track ->
            val dragging = draggedId == track.id
            val handle =
                Modifier.pointerInput(track.id) {
                    detectDragGesturesAfterLongPress(
                        onDragStart = {
                            val item =
                                list.layoutInfo.visibleItemsInfo.firstOrNull { it.key == track.id }
                            if (item != null) {
                                dragCenter = item.offset + item.size / 2f
                                draggedId = track.id
                            }
                        },
                        onDragEnd = { draggedId = null },
                        onDragCancel = { draggedId = null },
                        onDrag = { change, amount ->
                            change.consume()
                            if (draggedId == track.id) {
                                dragCenter += amount.y
                                moveAtPointer()
                            }
                        },
                    )
                }
            TrackRow(
                track,
                state,
                c,
                onPlaylist = { onPlaylist(track) },
                modifier =
                    Modifier.zIndex(if (dragging) 1f else 0f).graphicsLayer {
                        if (dragging) {
                            val item =
                                list.layoutInfo.visibleItemsInfo.firstOrNull { it.key == track.id }
                            translationY =
                                if (item == null) 0f else dragCenter - item.offset - item.size / 2f
                            shadowElevation = 8.dp.toPx()
                        }
                    },
                dragHandle = handle,
            )
        }
    }
}

@Composable
private fun RecordingVersions(state: AppState, c: LocalController) {
    val reference = state.versionReference ?: return
    var chosenId by remember(reference.id) { mutableStateOf<String?>(null) }
    val chosen = state.versions.firstOrNull { it.track.id == chosenId }
    AlertDialog(
        onDismissRequest = c::closeVersions,
        title = { Text("Другие записи") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text(reference.title, fontWeight = FontWeight.SemiBold)
                Text(
                    "Названия загрузок не подтверждают отсутствие цензуры. Выбери подходящую запись на слух.",
                    fontSize = 12.sp,
                )
                if (state.versionsLoading) LinearProgressIndicator(Modifier.fillMaxWidth())
                if (state.versionError.isNotBlank())
                    Text(state.versionError, color = MaterialTheme.colorScheme.error)
                if (state.versions.isEmpty() && !state.versionsLoading)
                    Text("Подходящих записей не найдено")
                LazyColumn(
                    Modifier.heightIn(max = 360.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    items(state.versions, key = { it.track.id }) { version ->
                        Surface(
                            color =
                                if (chosenId == version.track.id)
                                    MaterialTheme.colorScheme.primaryContainer
                                else Panel,
                            shape = RoundedCornerShape(14.dp),
                            modifier =
                                Modifier.fillMaxWidth().clickable { chosenId = version.track.id },
                        ) {
                            Column(
                                Modifier.padding(12.dp),
                                verticalArrangement = Arrangement.spacedBy(6.dp),
                            ) {
                                Text(version.label, color = Coral, fontSize = 12.sp)
                                Text(version.track.title, fontWeight = FontWeight.SemiBold)
                                Text(
                                    version.track.artist +
                                        " · " +
                                        time(version.track.duration * 1000L),
                                    fontSize = 12.sp,
                                )
                                Text(
                                    version.evidence,
                                    fontSize = 12.sp,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                        }
                    }
                }
                TextButton(onClick = { c.resetVersion(reference) }) { Text("Исходная запись") }
            }
        },
        confirmButton = {
            TextButton(
                enabled = chosen != null,
                onClick = { chosen?.let { c.chooseVersion(reference, it.track) } },
            ) {
                Text("Слушать")
            }
        },
        dismissButton = { TextButton(onClick = c::closeVersions) { Text("Закрыть") } },
    )
}

@Composable
private fun LibrarySort(state: AppState, controller: LocalController) {
    var expanded by remember { mutableStateOf(false) }
    Box {
        IconButton(onClick = { expanded = true }) { Icon(Icons.Outlined.Sort, "Сортировка") }
        DropdownMenu(expanded, { expanded = false }) {
            if (state.view == LibraryView.SEARCH) {
                listOf(
                        SearchOrder.RELEVANCE to "По релевантности",
                        SearchOrder.VIEWS to "По просмотрам",
                    )
                    .forEach { (order, label) ->
                        DropdownMenuItem(
                            text = {
                                Text(label, color = if (state.searchOrder == order) Coral else Warm)
                            },
                            onClick = {
                                expanded = false
                                controller.setSearchOrder(order)
                            },
                        )
                    }
            } else
                listOf(
                        LocalOrder.CUSTOM to "Порядок библиотеки",
                        LocalOrder.TITLE to "По названию",
                        LocalOrder.ARTIST to "По исполнителю",
                        LocalOrder.SHORTEST to "Сначала короткие",
                        LocalOrder.LONGEST to "Сначала длинные",
                    )
                    .forEach { (order, label) ->
                        DropdownMenuItem(
                            text = {
                                Text(label, color = if (state.localOrder == order) Coral else Warm)
                            },
                            onClick = {
                                expanded = false
                                controller.setLocalOrder(order)
                            },
                        )
                    }
        }
    }
}

@Composable
@OptIn(ExperimentalFoundationApi::class)
private fun TrackRow(
    track: Track,
    state: AppState,
    c: LocalController,
    onPlaylist: () -> Unit,
    modifier: Modifier = Modifier,
    dragHandle: Modifier? = null,
) {
    var menu by remember { mutableStateOf(false) }
    val current = track.id == state.current?.id
    val isSelected = track.id in state.selectedIds
    val background by
        animateColorAsState(
            if (current || isSelected) Panel else Color.Transparent,
            tween(if (state.reducedMotion) 0 else 180),
            label = "track-selection",
        )
    Row(
        modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(14.dp))
            .background(background)
            .semantics { selected = isSelected }
            .combinedClickable(
                onLongClick = {
                    if (state.view == LibraryView.HOME) menu = true
                    else c.selectTrack(track.id, control = true, shift = false)
                },
                onClick = {
                    if (state.selectedIds.isNotEmpty())
                        c.selectTrack(track.id, control = true, shift = false)
                    else if (state.view == LibraryView.QUEUE) c.playQueueTrack(track.id)
                    else c.play(track)
                },
            )
            .padding(vertical = 10.dp, horizontal = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (isSelected)
            Box(Modifier.size(52.dp), contentAlignment = Alignment.Center) {
                Icon(Icons.Outlined.CheckCircle, "Выбрано", tint = Coral)
            }
        else Cover(track, 52)
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(
                track.title,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
                color = if (current) Coral else Warm,
                fontWeight = FontWeight.Medium,
            )
            Text(
                track.artist,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                color = Color(0xFFAFBAAD),
                fontSize = 13.sp,
            )
        }
        IconButton(onClick = { c.toggleLike(track) }) {
            Icon(
                if (state.likes.any { it.id == track.id }) Icons.Outlined.Favorite
                else Icons.Outlined.FavoriteBorder,
                "Нравится",
                tint = if (state.likes.any { it.id == track.id }) Coral else Color(0xFFAFBAAD),
            )
        }
        if (dragHandle != null)
            Icon(
                Icons.Outlined.DragHandle,
                "Удерживай для перестановки",
                modifier = dragHandle.size(40.dp).padding(8.dp),
            )
        Box {
            IconButton(onClick = { menu = true }) { Icon(Icons.Outlined.MoreVert, "Действия") }
            DropdownMenu(menu, { menu = false }) {
                if (!track.id.startsWith("local:"))
                    DropdownMenuItem(
                        text = { Text("Другие записи") },
                        onClick = {
                            menu = false
                            c.findVersions(track)
                        },
                    )
                DropdownMenuItem(
                    text = { Text("Следующим") },
                    onClick = {
                        c.playNext(track)
                        menu = false
                    },
                )
                DropdownMenuItem(
                    text = { Text("В очередь") },
                    onClick = {
                        c.enqueue(track)
                        menu = false
                    },
                )
                DropdownMenuItem(
                    text = { Text("В плейлист") },
                    onClick = {
                        onPlaylist()
                        menu = false
                    },
                )
                if (state.view == LibraryView.QUEUE)
                    DropdownMenuItem(
                        text = { Text("Убрать из очереди") },
                        onClick = {
                            c.removeFromQueue(track.id)
                            menu = false
                        },
                    )
                if (state.view == LibraryView.QUEUE) {
                    DropdownMenuItem(
                        text = { Text("Выше в очереди") },
                        onClick = {
                            c.moveInQueue(track.id, -1)
                            menu = false
                        },
                    )
                    DropdownMenuItem(
                        text = { Text("Ниже в очереди") },
                        onClick = {
                            c.moveInQueue(track.id, 1)
                            menu = false
                        },
                    )
                }
                if (state.view == LibraryView.PLAYLIST)
                    DropdownMenuItem(
                        text = { Text("Убрать из плейлиста") },
                        onClick = {
                            state.playlistId?.let { c.removeFromPlaylist(it, track.id) }
                            menu = false
                        },
                    )
            }
        }
    }
}

@Composable
private fun MiniPlayer(c: LocalController) {
    val state by c.state.collectAsStateWithLifecycle()
    Surface(
        Modifier.padding(horizontal = 12.dp, vertical = 5.dp).fillMaxWidth().clickable {
            c.openNowPlaying(true)
        },
        color = Panel,
        shape = RoundedCornerShape(18.dp),
    ) {
        Column {
            Row(Modifier.padding(10.dp), verticalAlignment = Alignment.CenterVertically) {
                Cover(state.current, 44)
                Spacer(Modifier.width(10.dp))
                Column(Modifier.weight(1f)) {
                    Text(
                        state.current?.title.orEmpty(),
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                        fontWeight = FontWeight.SemiBold,
                    )
                    Text(
                        state.current?.artist.orEmpty(),
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                        fontSize = 12.sp,
                    )
                }
                if (state.playbackLoading)
                    CircularProgressIndicator(Modifier.size(24.dp), strokeWidth = 2.dp)
                else
                    IconButton(onClick = c::toggle) {
                        Icon(
                            if (state.playing) Icons.Outlined.Pause else Icons.Outlined.PlayArrow,
                            if (state.playing) "Пауза" else "Воспроизвести",
                        )
                    }
                IconButton(onClick = c::next, enabled = state.queue.isNotEmpty()) {
                    Icon(Icons.Outlined.SkipNext, "Следующий")
                }
            }
            LinearProgressIndicator(
                progress = {
                    (state.positionMs.toFloat() / state.durationMs.coerceAtLeast(1)).coerceIn(
                        0f,
                        1f,
                    )
                },
                modifier = Modifier.fillMaxWidth().height(2.dp),
                color = Coral,
                trackColor = MaterialTheme.colorScheme.outlineVariant,
            )
        }
    }
}

@Composable
private fun NowPlaying(c: LocalController, close: () -> Unit) {
    val state by c.state.collectAsStateWithLifecycle()
    var showLyrics by remember { mutableStateOf(false) }
    var entered by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) { entered = true }
    val reveal by
        animateFloatAsState(
            if (entered) 1f else 0f,
            tween(if (state.reducedMotion) 0 else 320),
            label = "player-reveal",
        )
    Dialog(
        onDismissRequest = close,
        properties =
            DialogProperties(usePlatformDefaultWidth = false, decorFitsSystemWindows = false),
    ) {
        Surface(
            Modifier.fillMaxSize().graphicsLayer {
                alpha = reveal
                translationY = (1f - reveal) * 40.dp.toPx()
            },
            color = Graphite,
        ) {
            Column(Modifier.fillMaxSize().systemBarsPadding().padding(horizontal = 24.dp)) {
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    IconButton(onClick = close) {
                        Icon(Icons.Outlined.KeyboardArrowDown, "Свернуть")
                    }
                    Text(
                        "СЕЙЧАС ИГРАЕТ",
                        modifier = Modifier.weight(1f),
                        fontSize = 12.sp,
                        letterSpacing = 2.sp,
                    )
                    IconButton(onClick = { showLyrics = !showLyrics }) {
                        Icon(
                            Icons.AutoMirrored.Outlined.Notes,
                            "Текст песни",
                            tint = if (showLyrics) Coral else Warm,
                        )
                    }
                }
                AnimatedContent(
                    targetState = showLyrics,
                    modifier = Modifier.weight(1f),
                    label = "player-mode",
                    transitionSpec = {
                        if (state.reducedMotion)
                            EnterTransition.None togetherWith ExitTransition.None
                        else fadeIn(tween(280)) togetherWith fadeOut(tween(180))
                    },
                ) { lyrics ->
                    if (lyrics) LyricsView(state, c)
                    else
                        BoxWithConstraints(
                            Modifier.fillMaxSize(),
                            contentAlignment = Alignment.Center,
                        ) {
                            val coverSize =
                                minOf(maxWidth, maxHeight, 400.dp).value.toInt().coerceAtLeast(1)
                            AnimatedContent(
                                targetState = state.current,
                                transitionSpec = {
                                    if (state.reducedMotion)
                                        EnterTransition.None togetherWith ExitTransition.None
                                    else
                                        (fadeIn(tween(320)) +
                                            scaleIn(
                                                initialScale = 0.94f,
                                                animationSpec = tween(320),
                                            )) togetherWith fadeOut(tween(180))
                                },
                                contentKey = { it?.id },
                                label = "playing-artwork",
                            ) { track ->
                                Cover(track, coverSize)
                            }
                        }
                }
                Text(
                    state.current?.title.orEmpty(),
                    fontSize = 25.sp,
                    fontWeight = FontWeight.Bold,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
                Text(state.current?.artist.orEmpty(), fontSize = 17.sp, color = Color(0xFFAFBAAD))
                if (state.playbackError != null)
                    Text(
                        state.playbackError.orEmpty(),
                        color = Coral,
                        modifier = Modifier.padding(top = 8.dp),
                    )
                var drag by remember(state.current?.id) { mutableStateOf<Float?>(null) }
                Slider(
                    value =
                        drag
                            ?: state.positionMs
                                .toFloat()
                                .coerceIn(0f, state.durationMs.coerceAtLeast(1).toFloat()),
                    onValueChange = { drag = it },
                    onValueChangeFinished = {
                        drag?.let { c.seek(it.toLong()) }
                        drag = null
                    },
                    valueRange = 0f..state.durationMs.coerceAtLeast(1).toFloat(),
                    enabled = state.seekable,
                )
                Row {
                    Text(time((drag ?: state.positionMs.toFloat()).toLong()), fontSize = 12.sp)
                    Spacer(Modifier.weight(1f))
                    Text(time(state.durationMs), fontSize = 12.sp)
                }
                Row(
                    Modifier.fillMaxWidth().padding(vertical = 20.dp),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    IconButton(onClick = c::toggleShuffle) {
                        Icon(
                            Icons.Outlined.Shuffle,
                            "Перемешать",
                            tint = if (state.shuffle) Coral else Warm,
                        )
                    }
                    IconButton(onClick = c::previous) {
                        Icon(
                            Icons.Outlined.SkipPrevious,
                            "Предыдущий",
                            modifier = Modifier.size(34.dp),
                        )
                    }
                    FilledIconButton(onClick = c::toggle, modifier = Modifier.size(72.dp)) {
                        if (state.playbackLoading)
                            CircularProgressIndicator(Modifier.size(30.dp), color = Graphite)
                        else
                            Icon(
                                if (state.playing) Icons.Outlined.Pause
                                else Icons.Outlined.PlayArrow,
                                if (state.playing) "Пауза" else "Воспроизвести",
                                modifier = Modifier.size(42.dp),
                            )
                    }
                    IconButton(onClick = c::next) {
                        Icon(Icons.Outlined.SkipNext, "Следующий", modifier = Modifier.size(34.dp))
                    }
                    IconButton(onClick = c::cycleRepeat) {
                        Icon(
                            if (state.repeatMode == RepeatMode.ONE) Icons.Outlined.RepeatOne
                            else Icons.Outlined.Repeat,
                            "Повтор",
                            tint = if (state.repeatMode != RepeatMode.OFF) Coral else Warm,
                        )
                    }
                }
                Row(
                    Modifier.fillMaxWidth().padding(bottom = 18.dp),
                    horizontalArrangement = Arrangement.SpaceEvenly,
                ) {
                    state.current?.let { track ->
                        IconButton(onClick = { c.toggleLike(track) }) {
                            Icon(
                                if (state.likes.any { it.id == track.id }) Icons.Outlined.Favorite
                                else Icons.Outlined.FavoriteBorder,
                                "Нравится",
                                tint = Coral,
                            )
                        }
                    }
                    TextButton(onClick = { showLyrics = !showLyrics }) {
                        Text(if (showLyrics) "Обложка" else "Текст песни")
                    }
                    IconButton(
                        onClick = {
                            close()
                            c.showView(LibraryView.QUEUE)
                        }
                    ) {
                        Icon(Icons.AutoMirrored.Outlined.QueueMusic, "Очередь")
                    }
                }
            }
        }
    }
}

@Composable
private fun LyricsView(state: AppState, c: LocalController) {
    val list = rememberLazyListState()
    val active = state.lyrics.indexOfLast { it.startMs <= state.positionMs }
    LaunchedEffect(active) {
        if (active >= 0) list.animateScrollToItem((active - 1).coerceAtLeast(0))
    }
    if (state.lyricsLoading)
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            CircularProgressIndicator()
        }
    else if (state.lyrics.isNotEmpty())
        Column {
            if (state.lyricsPacket.approximateWords)
                Text(
                    "Подсветка слов — расчётная",
                    color = Color(0xFFAFBAAD),
                    fontSize = 11.sp,
                    modifier = Modifier.padding(vertical = 8.dp),
                )
            LazyColumn(
                Modifier.fillMaxSize(),
                state = list,
                contentPadding = PaddingValues(vertical = 28.dp),
                verticalArrangement = Arrangement.spacedBy(22.dp),
            ) {
                itemsIndexed(state.lyrics) { index, line ->
                    val selected = index == active
                    val focus by
                        animateFloatAsState(
                            if (selected) 1f else 0.94f,
                            tween(if (state.reducedMotion) 0 else 300),
                            label = "lyric-focus",
                        )
                    val end =
                        line.endMs ?: state.lyrics.getOrNull(index + 1)?.startMs ?: state.durationMs
                    val words =
                        if (line.words.isNotEmpty()) line.words
                        else LyricTiming.estimatedWords(line.text, line.startMs, end)
                    val text = buildAnnotatedString {
                        words.forEach { word ->
                            val progress =
                                ((state.positionMs - word.startMs).toFloat() /
                                        (word.endMs - word.startMs).coerceAtLeast(1))
                                    .coerceIn(0f, 1f)
                            withStyle(
                                SpanStyle(
                                    color =
                                        if (selected) lerp(Color(0xFF899486), Warm, progress)
                                        else Color(0xFF6F796D)
                                )
                            ) {
                                append(word.text)
                            }
                        }
                        if (words.isEmpty()) append(line.text)
                    }
                    Text(
                        text,
                        color = if (selected) Warm else Color(0xFF6F796D),
                        fontSize = 27.sp,
                        fontWeight = FontWeight.Bold,
                        lineHeight = 34.sp,
                        modifier =
                            Modifier.fillMaxWidth()
                                .graphicsLayer {
                                    scaleX = focus
                                    scaleY = focus
                                    transformOrigin =
                                        androidx.compose.ui.graphics.TransformOrigin(0f, 0.5f)
                                }
                                .clickable(enabled = state.seekable) { c.seek(line.startMs) },
                    )
                }
            }
        }
    else
        Column(
            Modifier.fillMaxSize().verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.Center,
        ) {
            Text(
                state.lyricsPacket.plainText.ifBlank {
                    state.lyricsPacket.message.ifBlank { "Текст для этой записи пока не найден" }
                },
                fontSize = 22.sp,
                lineHeight = 32.sp,
            )
            TextButton(onClick = c::reloadLyrics) { Text("Повторить поиск") }
        }
}
