package riffuna.android

import androidx.activity.compose.BackHandler
import androidx.compose.animation.*
import androidx.compose.animation.core.*
import androidx.compose.foundation.*
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
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import coil3.compose.AsyncImage
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
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
    Box(
        modifier.size(size.dp).clip(RoundedCornerShape((size / 8).dp)).background(Panel),
        contentAlignment = Alignment.Center,
    ) {
        if (track?.thumbnail?.startsWith("https://") == true)
            AsyncImage(
                track.thumbnail,
                contentDescription = null,
                modifier = Modifier.fillMaxSize(),
                contentScale = ContentScale.Crop,
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
    var playlistTrack by remember { mutableStateOf<Track?>(null) }
    val snackbar = remember { SnackbarHostState() }
    LaunchedEffect(state.toast) { if (state.toast.isNotBlank()) snackbar.showSnackbar(state.toast) }
    BackHandler(state.expanded || state.canGoBack) {
        if (state.expanded) controller.openNowPlaying(false) else controller.navigateBack()
    }
    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        bottomBar = {
            Column {
                if (state.current != null) MiniPlayer(controller)
                NavigationBar(containerColor = Graphite) {
                    listOf(
                            Triple(LibraryView.HOME, "Главная", Icons.Outlined.Home),
                            Triple(LibraryView.SEARCH, "Поиск", Icons.Outlined.Search),
                            Triple(LibraryView.LIKES, "Любимое", Icons.Outlined.FavoriteBorder),
                            Triple(
                                LibraryView.QUEUE,
                                "Очередь",
                                Icons.AutoMirrored.Outlined.QueueMusic,
                            ),
                        )
                        .forEach { (view, label, icon) ->
                            NavigationBarItem(
                                selected = state.view == view,
                                onClick = { controller.showView(view) },
                                icon = { Icon(icon, null) },
                                label = { Text(label, maxLines = 1) },
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
                    "riffuna",
                    fontSize = 30.sp,
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
            }
            when (state.view) {
                LibraryView.HOME ->
                    LazyColumn(verticalArrangement = Arrangement.spacedBy(18.dp)) {
                        item {
                            Text(
                                "Твоя музыка.\nВ твоём ритме.",
                                fontSize = 32.sp,
                                lineHeight = 36.sp,
                                fontWeight = FontWeight.SemiBold,
                            )
                        }
                        item {
                            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                                FilledTonalButton(
                                    onClick = { controller.showView(LibraryView.HISTORY) }
                                ) {
                                    Text("Недавно слушал")
                                }
                                OutlinedButton(onClick = importFiles) { Text("Добавить файлы") }
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
                                    onPlaylist = { playlistTrack = track },
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
                                    onPlaylist = { playlistTrack = track },
                                )
                            }
                        }
                    }
                LibraryView.PLAYLISTS -> {
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
                    LazyColumn {
                        items(state.playlists, key = { it.id }) { p ->
                            ListItem(
                                headlineContent = { Text(p.name) },
                                supportingContent = { Text("${p.trackCount} треков") },
                                leadingContent = { Icon(Icons.Outlined.LibraryMusic, null) },
                                modifier = Modifier.clickable { controller.openPlaylist(p.id) },
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
                    }
                    val tracks =
                        if (state.view == LibraryView.QUEUE) state.queue else state.visibleTracks
                    if (tracks.isNotEmpty())
                        Row(verticalAlignment = Alignment.CenterVertically) {
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
                            Text("${tracks.size} треков", color = Color(0xFFAFBAAD))
                        }
                    if (state.searchLoading || state.localImporting)
                        LinearProgressIndicator(Modifier.fillMaxWidth().padding(vertical = 12.dp))
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
                    else
                        LazyColumn(Modifier.weight(1f)) {
                            items(tracks, key = { it.id }) { track ->
                                TrackRow(
                                    track,
                                    state,
                                    controller,
                                    onPlaylist = { playlistTrack = track },
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
    if (state.expanded) NowPlaying(controller) { controller.openNowPlaying(false) }
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
    playlistTrack?.let { track ->
        AlertDialog(
            onDismissRequest = { playlistTrack = null },
            title = { Text("Добавить в плейлист") },
            text = {
                Column {
                    if (state.playlists.isEmpty()) Text("Сначала создай плейлист в библиотеке")
                    state.playlists.forEach { p ->
                        TextButton(
                            onClick = {
                                controller.addToPlaylist(p.id, listOf(track))
                                playlistTrack = null
                            }
                        ) {
                            Text(p.name)
                        }
                    }
                }
            },
            confirmButton = { TextButton(onClick = { playlistTrack = null }) { Text("Закрыть") } },
        )
    }
}

@Composable
private fun TrackRow(track: Track, state: AppState, c: LocalController, onPlaylist: () -> Unit) {
    var menu by remember { mutableStateOf(false) }
    val current = track.id == state.current?.id
    Row(
        Modifier.fillMaxWidth()
            .clip(RoundedCornerShape(14.dp))
            .background(if (current) Panel else Color.Transparent)
            .clickable {
                if (state.view == LibraryView.QUEUE) c.playQueueTrack(track.id) else c.play(track)
            }
            .padding(vertical = 10.dp, horizontal = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Cover(track, 52)
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
        Box {
            IconButton(onClick = { menu = true }) { Icon(Icons.Outlined.MoreVert, "Действия") }
            DropdownMenu(menu, { menu = false }) {
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
                            "Пауза / играть",
                        )
                    }
                IconButton(onClick = c::next) { Icon(Icons.Outlined.SkipNext, "Следующий") }
            }
            LinearProgressIndicator(
                progress = {
                    (state.positionMs.toFloat() / state.durationMs.coerceAtLeast(1)).coerceIn(
                        0f,
                        1f,
                    )
                },
                modifier = Modifier.fillMaxWidth().height(2.dp),
            )
        }
    }
}

@Composable
private fun NowPlaying(c: LocalController, close: () -> Unit) {
    val state by c.state.collectAsStateWithLifecycle()
    var showLyrics by remember { mutableStateOf(false) }
    Dialog(
        onDismissRequest = close,
        properties =
            DialogProperties(usePlatformDefaultWidth = false, decorFitsSystemWindows = false),
    ) {
        Surface(Modifier.fillMaxSize(), color = Graphite) {
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
                ) { lyrics ->
                    if (lyrics) LyricsView(state, c)
                    else
                        BoxWithConstraints(
                            Modifier.fillMaxSize(),
                            contentAlignment = Alignment.Center,
                        ) {
                            val coverSize =
                                minOf(maxWidth, maxHeight, 400.dp).value.toInt().coerceAtLeast(1)
                            Cover(state.current, coverSize)
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
                                "Пауза / играть",
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
        LazyColumn(
            Modifier.fillMaxSize(),
            state = list,
            contentPadding = PaddingValues(vertical = 28.dp),
            verticalArrangement = Arrangement.spacedBy(22.dp),
        ) {
            itemsIndexed(state.lyrics) { index, line ->
                val color by
                    animateColorAsState(
                        if (index == active) Warm else Color(0xFF6F796D),
                        label = "lyric-line",
                    )
                Text(
                    line.text,
                    color = color,
                    fontSize = if (index == active) 27.sp else 25.sp,
                    fontWeight = FontWeight.Bold,
                    lineHeight = 34.sp,
                    modifier =
                        Modifier.fillMaxWidth().clickable(enabled = state.seekable) {
                            c.seek(line.startMs)
                        },
                )
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
