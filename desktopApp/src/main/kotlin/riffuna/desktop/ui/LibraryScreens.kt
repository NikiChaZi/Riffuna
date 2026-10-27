@file:OptIn(
    androidx.compose.foundation.ExperimentalFoundationApi::class,
    androidx.compose.ui.ExperimentalComposeUiApi::class,
)

package riffuna.desktop.ui

import androidx.compose.animation.core.*
import androidx.compose.foundation.*
import androidx.compose.foundation.interaction.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.*
import androidx.compose.foundation.lazy.grid.*
import androidx.compose.foundation.shape.*
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.*
import androidx.compose.ui.draw.*
import androidx.compose.ui.focus.*
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.key.*
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.*
import riffuna.core.*
import sh.calvin.reorderable.*

@Composable
fun SearchField(
    value: String,
    onChange: (String) -> Unit,
    placeholder: String,
    modifier: Modifier = Modifier,
    requester: FocusRequester? = null,
    onFocused: (Boolean) -> Unit = {},
    onSubmit: (() -> Unit)? = null,
) {
    var focused by remember { mutableStateOf(false) }
    Row(
        modifier
            .height(44.dp)
            .clip(RoundedCornerShape(11.dp))
            .background(RiffunaColors.Raised)
            .border(
                1.dp,
                if (focused) RiffunaColors.Coral.copy(alpha = .7f) else RiffunaColors.Border,
                RoundedCornerShape(11.dp),
            )
            .padding(horizontal = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Icon(Icons.Outlined.Search, null, Modifier.size(19.dp), tint = RiffunaColors.Secondary)
        BasicTextField(
            value,
            onChange,
            singleLine = true,
            textStyle = MaterialTheme.typography.bodyMedium.copy(color = RiffunaColors.Text),
            cursorBrush = androidx.compose.ui.graphics.SolidColor(RiffunaColors.Coral),
            modifier =
                Modifier.weight(1f)
                    .then(if (requester != null) Modifier.focusRequester(requester) else Modifier)
                    .onFocusChanged {
                        focused = it.isFocused
                        onFocused(it.isFocused)
                    }
                    .onPreviewKeyEvent {
                        if (
                            onSubmit != null &&
                                it.type == KeyEventType.KeyDown &&
                                it.key == Key.Enter
                        ) {
                            onSubmit()
                            true
                        } else false
                    },
            decorationBox = { inner ->
                Box {
                    if (value.isEmpty())
                        Text(
                            placeholder,
                            style = MaterialTheme.typography.bodyMedium,
                            color = RiffunaColors.Secondary,
                        )
                    inner()
                }
            },
        )
        if (value.isNotEmpty())
            ActionIcon(Icons.Outlined.Close, "Очистить", { onChange("") }, size = 24.dp)
    }
}

@Composable
fun Sidebar(
    controller: RiffunaController,
    state: AppState,
    onNewPlaylist: () -> Unit,
    onSettings: () -> Unit,
    onHelp: () -> Unit,
) {
    Column(
        Modifier.width(188.dp)
            .fillMaxHeight()
            .background(RiffunaColors.Surface)
            .padding(horizontal = 12.dp)
    ) {
        Row(
            Modifier.height(78.dp).padding(start = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Surface(color = RiffunaColors.Coral, shape = RoundedCornerShape(10.dp)) {
                Text(
                    "R",
                    Modifier.padding(horizontal = 9.dp, vertical = 3.dp),
                    style = MaterialTheme.typography.headlineSmall,
                    fontWeight = FontWeight.Black,
                    color = RiffunaColors.Background,
                )
            }
            Text(
                "Riffuna",
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.Bold,
            )
        }
        Column(
            Modifier.weight(1f).verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(5.dp),
        ) {
            listOf(
                    Triple(LibraryView.HOME, "Главная", Icons.Outlined.Home),
                    Triple(LibraryView.SEARCH, "Поиск", Icons.Outlined.Search),
                    Triple(LibraryView.RESONANCE, "Резонанс", Icons.Outlined.GraphicEq),
                )
                .forEach { (key, title, icon) ->
                    NavigationRow(title, icon, state.view == key) { controller.showView(key) }
                }
            Text(
                "МОЯ МУЗЫКА",
                Modifier.padding(start = 12.dp, top = 28.dp, bottom = 9.dp),
                style = MaterialTheme.typography.labelSmall,
                color = RiffunaColors.Muted,
            )
            listOf(
                    Triple(LibraryView.LIKES, "Мне нравится", Icons.Outlined.FavoriteBorder),
                    Triple(LibraryView.HISTORY, "История", Icons.Outlined.History),
                )
                .forEach { (key, title, icon) ->
                    NavigationRow(title, icon, state.view == key) { controller.showView(key) }
                }
            Row(
                Modifier.padding(start = 12.dp, top = 22.dp, bottom = 6.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    "ПЛЕЙЛИСТЫ",
                    style = MaterialTheme.typography.labelSmall,
                    color = RiffunaColors.Muted,
                    modifier = Modifier.weight(1f),
                )
                ActionIcon(Icons.Outlined.Add, "Создать плейлист", onNewPlaylist, size = 28.dp)
            }
            NavigationRow(
                "Все плейлисты",
                Icons.Outlined.LibraryMusic,
                state.view == LibraryView.PLAYLISTS,
            ) {
                controller.showView(LibraryView.PLAYLISTS)
            }
            state.playlists.forEach { playlist ->
                Row(
                    Modifier.fillMaxWidth()
                        .clip(RoundedCornerShape(8.dp))
                        .background(
                            if (state.playlistId == playlist.id) RiffunaColors.Raised
                            else Color.Transparent
                        )
                        .clickable { controller.openPlaylist(playlist.id) }
                        .padding(8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    Artwork(playlist.thumbnail, Modifier.size(30.dp), playlist.name, 5.dp)
                    Text(
                        playlist.name,
                        style = MaterialTheme.typography.bodySmall,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
        }
        Row(Modifier.fillMaxWidth().height(54.dp), verticalAlignment = Alignment.CenterVertically) {
            ActionIcon(Icons.Outlined.Settings, "Настройки", onSettings)
            Spacer(Modifier.weight(1f))
            ActionIcon(Icons.Outlined.Keyboard, "Горячие клавиши · F1", onHelp)
        }
    }
}

@Composable
private fun NavigationRow(
    title: String,
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    selected: Boolean,
    onClick: () -> Unit,
) {
    val source = remember { MutableInteractionSource() }
    val hover by source.collectIsHoveredAsState()
    Row(
        Modifier.fillMaxWidth()
            .height(42.dp)
            .clip(RoundedCornerShape(9.dp))
            .background(
                if (selected) RiffunaColors.Selected
                else if (hover) RiffunaColors.Raised else Color.Transparent
            )
            .hoverable(source)
            .clickable(onClick = onClick)
            .padding(horizontal = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Icon(
            icon,
            null,
            Modifier.size(20.dp),
            tint = if (selected) RiffunaColors.Coral else RiffunaColors.Secondary,
        )
        Text(
            title,
            style = MaterialTheme.typography.bodyMedium,
            color = if (selected) RiffunaColors.Text else RiffunaColors.Secondary,
            fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal,
        )
    }
}

@Composable
fun HomeScreen(
    controller: RiffunaController,
    state: AppState,
    onPlaylist: (List<Track>) -> Unit,
    onSearch: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val current = state.current ?: state.history.firstOrNull()
    LazyColumn(
        modifier,
        verticalArrangement = Arrangement.spacedBy(24.dp),
        contentPadding = PaddingValues(bottom = 28.dp),
    ) {
        item {
            Text(
                "Главная",
                style = MaterialTheme.typography.headlineLarge,
                fontWeight = FontWeight.Bold,
            )
        }
        item {
            if (current != null)
                Surface(color = Color(0xFF252724), shape = RoundedCornerShape(18.dp)) {
                    Row(
                        Modifier.fillMaxWidth().padding(22.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(22.dp),
                    ) {
                        Artwork(
                            current.thumbnail,
                            Modifier.size(142.dp).clickable { controller.play(current) },
                            current.title,
                            12.dp,
                        )
                        Column(
                            Modifier.weight(1f),
                            verticalArrangement = Arrangement.spacedBy(9.dp),
                        ) {
                            Text(
                                "ВЕРНУТЬСЯ К МУЗЫКЕ",
                                style = MaterialTheme.typography.labelSmall,
                                color = RiffunaColors.Secondary,
                            )
                            Text(
                                current.title,
                                style = MaterialTheme.typography.headlineMedium,
                                fontWeight = FontWeight.Bold,
                                maxLines = 2,
                                overflow = TextOverflow.Ellipsis,
                            )
                            Text(
                                current.artist,
                                style = MaterialTheme.typography.bodyLarge,
                                color = RiffunaColors.Secondary,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                            )
                            Button(
                                onClick = {
                                    if (state.current?.id == current.id) controller.toggle()
                                    else controller.play(current)
                                },
                                shape = RoundedCornerShape(24.dp),
                                modifier = Modifier.padding(top = 5.dp),
                            ) {
                                Icon(
                                    if (state.playing && state.current?.id == current.id)
                                        Icons.Filled.Pause
                                    else Icons.Filled.PlayArrow,
                                    null,
                                    Modifier.size(20.dp),
                                )
                                Spacer(Modifier.width(6.dp))
                                Text(
                                    if (state.playing && state.current?.id == current.id) "Пауза"
                                    else "Слушать"
                                )
                            }
                        }
                    }
                }
            else
                EmptyState(
                    Icons.Outlined.Headphones,
                    "Твоя музыка начинается здесь",
                    "Найди любимый трек, сохрани лайк или создай плейлист",
                    "Найти музыку",
                    onSearch,
                )
        }
        if (state.history.isNotEmpty())
            item {
                SectionTitle("Недавно слушал", "Вся история") {
                    controller.showView(LibraryView.HISTORY)
                }
                LazyRow(horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                    items(state.history.take(12), key = { it.id }) { track ->
                        CoverCard(track, { controller.play(track) }, { onPlaylist(listOf(track)) })
                    }
                }
            }
        item {
            Surface(
                color = Color(0xFF2D2925),
                shape = RoundedCornerShape(16.dp),
                modifier =
                    Modifier.fillMaxWidth().clickable { controller.showView(LibraryView.RESONANCE) },
            ) {
                Row(
                    Modifier.padding(22.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(18.dp),
                ) {
                    Icon(
                        Icons.Outlined.GraphicEq,
                        null,
                        Modifier.size(40.dp),
                        tint = RiffunaColors.Coral,
                    )
                    Column(Modifier.weight(1f)) {
                        Text(
                            "Резонанс",
                            style = MaterialTheme.typography.titleLarge,
                            fontWeight = FontWeight.Bold,
                        )
                        Text(
                            "Музыка на основе твоих лайков",
                            Modifier.padding(top = 5.dp),
                            style = MaterialTheme.typography.bodyMedium,
                            color = RiffunaColors.Secondary,
                        )
                    }
                    ActionIcon(
                        Icons.Outlined.ArrowForward,
                        "Открыть Резонанс",
                        { controller.showView(LibraryView.RESONANCE) },
                    )
                }
            }
        }
        if (state.likes.isNotEmpty())
            item {
                SectionTitle("Тебе нравится", "Все лайки") {
                    controller.showView(LibraryView.LIKES)
                }
                LazyRow(horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                    items(state.likes.take(12), key = { it.id }) { track ->
                        CoverCard(track, { controller.play(track) }, { onPlaylist(listOf(track)) })
                    }
                }
            }
    }
}

@Composable
private fun CoverCard(track: Track, onPlay: () -> Unit, onPlaylist: () -> Unit) {
    val source = remember { MutableInteractionSource() }
    val hover by source.collectIsHoveredAsState()
    Column(
        Modifier.width(154.dp)
            .clip(RoundedCornerShape(12.dp))
            .background(if (hover) RiffunaColors.Raised else Color.Transparent)
            .hoverable(source)
            .combinedClickable(onClick = onPlay, onLongClick = onPlaylist)
            .padding(8.dp)
    ) {
        Box(Modifier.size(138.dp)) {
            Artwork(track.thumbnail, Modifier.fillMaxSize(), track.title, 9.dp)
            androidx.compose.animation.AnimatedVisibility(
                hover,
                modifier = Modifier.align(Alignment.BottomEnd).padding(8.dp),
                enter =
                    androidx.compose.animation.fadeIn() +
                        androidx.compose.animation.scaleIn(initialScale = .85f),
                exit = androidx.compose.animation.fadeOut(),
            ) {
                FilledIconButton(onClick = onPlay, modifier = Modifier.size(38.dp)) {
                    Icon(Icons.Filled.PlayArrow, "Слушать")
                }
            }
        }
        Text(
            track.title,
            Modifier.padding(top = 11.dp),
            style = MaterialTheme.typography.bodyMedium,
            fontWeight = FontWeight.Medium,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        Text(
            track.artist,
            Modifier.padding(top = 5.dp),
            style = MaterialTheme.typography.bodySmall,
            color = RiffunaColors.Secondary,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
fun EmptyState(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    title: String,
    message: String,
    action: String? = null,
    onAction: () -> Unit = {},
) {
    Column(
        Modifier.fillMaxWidth().padding(vertical = 52.dp, horizontal = 24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Icon(icon, null, Modifier.size(44.dp), tint = RiffunaColors.Muted)
        Text(title, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold)
        Text(message, color = RiffunaColors.Secondary, style = MaterialTheme.typography.bodyMedium)
        if (action != null)
            Button(onClick = onAction, modifier = Modifier.padding(top = 8.dp)) { Text(action) }
    }
}

@Composable
fun TracksScreen(
    controller: RiffunaController,
    state: AppState,
    listState: LazyListState,
    onPlaylist: (List<Track>) -> Unit,
    onEdit: () -> Unit,
    onOpen: (Track) -> Unit,
    filterFocus: FocusRequester,
    onInputFocus: (Boolean) -> Unit,
) {
    val tracks = displayedTracks(state)
    val playlist = state.playlists.firstOrNull { it.id == state.playlistId }
    val listFocus = remember { FocusRequester() }
    var filterFocused by remember { mutableStateOf(false) }
    var sortMenu by remember { mutableStateOf(false) }
    var listMenu by remember { mutableStateOf(false) }
    val reorder =
        rememberReorderableLazyListState(listState) { from, to ->
            val ids = state.visibleTracks.map { it.id }.toMutableList()
            val a = ids.indexOf(from.key)
            val b = ids.indexOf(to.key)
            if (a >= 0 && b >= 0) {
                ids.add(b, ids.removeAt(a))
                controller.reorderPlaylist(ids)
            }
        }
    val reorderEnabled =
        state.view == LibraryView.PLAYLIST &&
            state.localFilter.isBlank() &&
            state.localOrder == LocalOrder.CUSTOM
    Column(
        Modifier.fillMaxSize()
            .focusRequester(listFocus)
            .onPreviewKeyEvent { event ->
                if (filterFocused || event.type != KeyEventType.KeyDown)
                    return@onPreviewKeyEvent false
                when (event.key) {
                    Key.Enter -> {
                        tracks.firstOrNull { it.id in state.selectedIds }?.let(controller::play)
                        true
                    }
                    Key.DirectionUp,
                    Key.DirectionDown -> {
                        val current = tracks.indexOfFirst { it.id in state.selectedIds }
                        val next =
                            if (current < 0) 0
                            else
                                (current + if (event.key == Key.DirectionUp) -1 else 1).coerceIn(
                                    0,
                                    (tracks.size - 1).coerceAtLeast(0),
                                )
                        tracks.getOrNull(next)?.let {
                            controller.selectTrack(it.id, event.isCtrlPressed, event.isShiftPressed)
                        }
                        true
                    }
                    else -> false
                }
            }
            .focusable(),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            if (state.view == LibraryView.PLAYLIST)
                Artwork(playlist?.thumbnail.orEmpty(), Modifier.size(80.dp), playlist?.name, 12.dp)
            else if (state.view == LibraryView.LIKES)
                Surface(
                    color = RiffunaColors.Coral.copy(alpha = .12f),
                    shape = RoundedCornerShape(12.dp),
                ) {
                    Icon(
                        Icons.Filled.Favorite,
                        null,
                        Modifier.padding(22.dp).size(36.dp),
                        tint = RiffunaColors.Coral,
                    )
                }
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(7.dp)) {
                Text(
                    when (state.view) {
                        LibraryView.LIKES -> "Мне нравится"
                        LibraryView.HISTORY -> "История"
                        LibraryView.PLAYLIST -> playlist?.name ?: "Плейлист"
                        else -> "Музыкальные записи"
                    },
                    style = MaterialTheme.typography.headlineLarge,
                    fontWeight = FontWeight.Bold,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
                Text(
                    if (state.view == LibraryView.SEARCH)
                        state.query + " · " + trackCount(state.visibleTracks.size)
                    else trackCount(tracks.size),
                    style = MaterialTheme.typography.bodyMedium,
                    color = RiffunaColors.Secondary,
                )
                if (!playlist?.description.isNullOrBlank())
                    Text(
                        playlist!!.description,
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
                        color = RiffunaColors.Secondary,
                        style = MaterialTheme.typography.bodyMedium,
                    )
            }
        }
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(9.dp),
        ) {
            Button(
                onClick = controller::playAll,
                enabled = tracks.isNotEmpty(),
                shape = RoundedCornerShape(24.dp),
            ) {
                Icon(Icons.Filled.PlayArrow, null, Modifier.size(19.dp))
                Spacer(Modifier.width(6.dp))
                Text("Слушать всё")
            }
            ActionIcon(
                Icons.Outlined.Shuffle,
                "Перемешать и слушать",
                {
                    if (!state.shuffle) controller.toggleShuffle()
                    controller.playAll()
                },
                enabled = tracks.isNotEmpty(),
                active = state.shuffle,
            )
            if (playlist != null)
                Box {
                    ActionIcon(
                        Icons.Outlined.MoreHoriz,
                        "Действия с плейлистом",
                        { listMenu = true },
                    )
                    DropdownMenu(listMenu, { listMenu = false }) {
                        DropdownMenuItem(
                            { Text("Изменить название и описание") },
                            {
                                onEdit()
                                listMenu = false
                            },
                        )
                        DropdownMenuItem(
                            { Text("Создать копию") },
                            {
                                controller.duplicatePlaylist(playlist.id)
                                listMenu = false
                            },
                        )
                        DropdownMenuItem(
                            { Text("Добавить всё в очередь") },
                            {
                                controller.enqueueMany(state.visibleTracks)
                                listMenu = false
                            },
                        )
                        DropdownMenuItem(
                            { Text("Копировать в другой плейлист…") },
                            {
                                onPlaylist(state.visibleTracks)
                                listMenu = false
                            },
                        )
                    }
                }
            Spacer(Modifier.weight(1f))
            Box {
                TextButton(onClick = { sortMenu = true }) {
                    Icon(Icons.Outlined.Sort, null, Modifier.size(18.dp))
                    Spacer(Modifier.width(6.dp))
                    Text(
                        if (state.view == LibraryView.SEARCH)
                            if (state.searchOrder == SearchOrder.VIEWS) "По просмотрам"
                            else "По релевантности"
                        else
                            when (state.localOrder) {
                                LocalOrder.TITLE -> "По названию"
                                LocalOrder.ARTIST -> "По исполнителю"
                                LocalOrder.SHORTEST -> "Сначала короткие"
                                LocalOrder.LONGEST -> "Сначала длинные"
                                else ->
                                    if (state.view == LibraryView.PLAYLIST) "Порядок плейлиста"
                                    else "Сначала новые"
                            }
                    )
                }
                DropdownMenu(sortMenu, { sortMenu = false }) {
                    if (state.view == LibraryView.SEARCH)
                        listOf(
                                SearchOrder.RELEVANCE to "По релевантности",
                                SearchOrder.VIEWS to "По просмотрам найденных записей",
                            )
                            .forEach { (key, title) ->
                                DropdownMenuItem(
                                    { Text(title) },
                                    {
                                        controller.setSearchOrder(key)
                                        sortMenu = false
                                    },
                                )
                            }
                    else
                        listOf(
                                LocalOrder.CUSTOM to
                                    if (state.view == LibraryView.PLAYLIST) "Порядок плейлиста"
                                    else "Сначала новые",
                                LocalOrder.TITLE to "По названию",
                                LocalOrder.ARTIST to "По исполнителю",
                                LocalOrder.SHORTEST to "Сначала короткие",
                                LocalOrder.LONGEST to "Сначала длинные",
                            )
                            .forEach { (key, title) ->
                                DropdownMenuItem(
                                    { Text(title) },
                                    {
                                        controller.setLocalOrder(key)
                                        sortMenu = false
                                    },
                                )
                            }
                }
            }
        }
        if (state.view != LibraryView.SEARCH || tracks.isNotEmpty())
            SearchField(
                state.localFilter,
                controller::setLocalFilter,
                "Найти в списке",
                Modifier.fillMaxWidth(),
                filterFocus,
                {
                    filterFocused = it
                    onInputFocus(it)
                },
            )
        if (state.selectedIds.isNotEmpty())
            Surface(color = RiffunaColors.Selected, shape = RoundedCornerShape(10.dp)) {
                Row(
                    Modifier.fillMaxWidth().padding(horizontal = 10.dp, vertical = 5.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    ActionIcon(
                        Icons.Outlined.Close,
                        "Снять выделение",
                        controller::clearSelection,
                        size = 28.dp,
                    )
                    Text(
                        "Выбрано: ${state.selectedIds.size}",
                        style = MaterialTheme.typography.labelMedium,
                        modifier = Modifier.weight(1f),
                    )
                    val selection = tracks.filter { it.id in state.selectedIds }
                    ActionIcon(
                        Icons.Outlined.PlaylistAdd,
                        "В очередь",
                        { controller.enqueueMany(selection) },
                    )
                    ActionIcon(Icons.Outlined.LibraryMusic, "В плейлист", { onPlaylist(selection) })
                    if (state.view in setOf(LibraryView.LIKES, LibraryView.PLAYLIST))
                        ActionIcon(
                            Icons.Outlined.DeleteOutline,
                            "Убрать выбранные",
                            controller::removeSelected,
                        )
                }
            }
        if (state.searchLoading && state.view == LibraryView.SEARCH)
            LinearProgressIndicator(Modifier.fillMaxWidth())
        if (tracks.isEmpty())
            Box(Modifier.weight(1f), contentAlignment = Alignment.Center) {
                EmptyState(
                    if (state.view == LibraryView.LIKES) Icons.Outlined.FavoriteBorder
                    else Icons.Outlined.Search,
                    if (state.searchLoading) "Ищем музыку…"
                    else if (state.localFilter.isNotBlank()) "Нет совпадений"
                    else if (state.view == LibraryView.SEARCH && state.query.isNotBlank())
                        "Ничего не найдено"
                    else "Здесь пока пусто",
                    if (state.view == LibraryView.LIKES) "Сохраняй любимые треки сердечком"
                    else if (state.view == LibraryView.SEARCH) state.status
                    else "Добавляй записи через меню трека",
                    if (
                        state.view == LibraryView.SEARCH &&
                            state.query.isNotBlank() &&
                            !state.searchLoading
                    )
                        "Повторить поиск"
                    else null,
                    { controller.search(state.query) },
                )
            }
        else
            LazyColumn(
                Modifier.weight(1f),
                state = listState,
                verticalArrangement = Arrangement.spacedBy(2.dp),
                contentPadding = PaddingValues(bottom = 18.dp),
            ) {
                itemsIndexed(tracks, key = { _, t -> t.id }) { index, track ->
                    @Composable
                    fun Content(drag: Modifier? = null) {
                        TrackRow(
                            track,
                            index,
                            isCurrentTrack(state, track),
                            state.playing,
                            state.likes.any { it.id == track.id },
                            track.id in state.selectedIds,
                            onPlay = {
                                listFocus.requestFocus()
                                controller.play(track)
                            },
                            onSelect = { ctrl, shift ->
                                listFocus.requestFocus()
                                controller.selectTrack(track.id, ctrl, shift)
                            },
                            onLike = { controller.toggleLike(track) },
                            onQueue = {
                                controller.enqueueMany(
                                    if (track.id in state.selectedIds)
                                        tracks.filter { it.id in state.selectedIds }
                                    else listOf(track)
                                )
                            },
                            onNext = { controller.playNext(track) },
                            onPlaylist = {
                                onPlaylist(
                                    if (track.id in state.selectedIds)
                                        tracks.filter { it.id in state.selectedIds }
                                    else listOf(track)
                                )
                            },
                            onVersions = { controller.findVersions(track) },
                            onArtist = { controller.search(track.artist) },
                            onOpen = { onOpen(track) },
                            onRemove =
                                when (state.view) {
                                    LibraryView.LIKES -> {
                                        { controller.toggleLike(track) }
                                    }
                                    LibraryView.PLAYLIST -> {
                                        {
                                            controller.removeFromPlaylist(
                                                state.playlistId!!,
                                                track.id,
                                            )
                                        }
                                    }
                                    else -> null
                                },
                            dragModifier = drag,
                        )
                    }
                    if (reorderEnabled)
                        ReorderableItem(reorder, track.id) { Content(Modifier.draggableHandle()) }
                    else Content()
                }
                if (state.view == LibraryView.SEARCH)
                    item {
                        Box(
                            Modifier.fillMaxWidth().padding(vertical = 12.dp),
                            contentAlignment = Alignment.Center,
                        ) {
                            if (state.canLoadMore)
                                OutlinedButton(
                                    onClick = controller::loadMore,
                                    enabled = !state.searchLoading,
                                ) {
                                    Text(if (state.searchLoading) "Загружаем…" else "Показать ещё")
                                }
                            else
                                Text(
                                    "Больше записей по этому запросу не найдено",
                                    style = MaterialTheme.typography.labelSmall,
                                    color = RiffunaColors.Muted,
                                )
                        }
                    }
            }
    }
}

@Composable
fun PlaylistsScreen(
    controller: RiffunaController,
    state: AppState,
    onNew: () -> Unit,
    onEdit: (PlaylistSummary) -> Unit,
) {
    Column(Modifier.fillMaxSize(), verticalArrangement = Arrangement.spacedBy(20.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                "Плейлисты",
                style = MaterialTheme.typography.headlineLarge,
                fontWeight = FontWeight.Bold,
                modifier = Modifier.weight(1f),
            )
            Button(onClick = onNew) {
                Icon(Icons.Outlined.Add, null, Modifier.size(18.dp))
                Spacer(Modifier.width(6.dp))
                Text("Создать")
            }
        }
        if (state.playlists.isEmpty())
            EmptyState(
                Icons.Outlined.LibraryMusic,
                "Собери свой первый плейлист",
                "Любимые записи, настроение или музыка в дорогу",
                "Создать плейлист",
                onNew,
            )
        else
            LazyVerticalGrid(
                columns = GridCells.Adaptive(170.dp),
                verticalArrangement = Arrangement.spacedBy(18.dp),
                horizontalArrangement = Arrangement.spacedBy(16.dp),
            ) {
                items(state.playlists, key = { it.id }) { playlist ->
                    Column(
                        Modifier.clip(RoundedCornerShape(12.dp))
                            .background(RiffunaColors.Surface)
                            .combinedClickable(
                                onClick = { controller.openPlaylist(playlist.id) },
                                onLongClick = { onEdit(playlist) },
                            )
                            .padding(12.dp)
                    ) {
                        Artwork(
                            playlist.thumbnail,
                            Modifier.fillMaxWidth().aspectRatio(1f),
                            playlist.name,
                            10.dp,
                        )
                        Text(
                            playlist.name,
                            Modifier.padding(top = 13.dp),
                            style = MaterialTheme.typography.titleMedium,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                        Text(
                            trackCount(playlist.trackCount),
                            Modifier.padding(top = 5.dp),
                            style = MaterialTheme.typography.bodySmall,
                            color = RiffunaColors.Secondary,
                        )
                    }
                }
            }
    }
}

@Composable
fun ResonanceScreen(controller: RiffunaController, state: AppState) {
    Column(Modifier.fillMaxSize(), verticalArrangement = Arrangement.spacedBy(18.dp)) {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Icon(Icons.Outlined.GraphicEq, null, Modifier.size(38.dp), tint = RiffunaColors.Coral)
            Column(Modifier.weight(1f)) {
                Text(
                    "Резонанс",
                    style = MaterialTheme.typography.headlineLarge,
                    fontWeight = FontWeight.Bold,
                )
                Text(
                    "Музыка на основе твоих лайков",
                    Modifier.padding(top = 6.dp),
                    color = RiffunaColors.Secondary,
                )
            }
            ActionIcon(
                Icons.Outlined.Refresh,
                "Обновить рекомендации",
                controller::refreshRecommendations,
                enabled = !state.recommendationsLoading,
            )
        }
        if (state.recommendationsLoading) LinearProgressIndicator(Modifier.fillMaxWidth())
        if (state.suggestions.isEmpty())
            EmptyState(
                Icons.Outlined.GraphicEq,
                if (state.recommendationsLoading) "Подбираем музыку…"
                else if (state.likes.isEmpty()) "Покажи, что тебе нравится"
                else "Пока недостаточно данных",
                if (state.likes.isEmpty()) "Лайки помогают находить музыку для тебя"
                else state.status,
            )
        else
            LazyColumn(verticalArrangement = Arrangement.spacedBy(5.dp)) {
                items(state.suggestions, key = { it.catalogId }) { song ->
                    Row(
                        Modifier.fillMaxWidth()
                            .clip(RoundedCornerShape(10.dp))
                            .background(RiffunaColors.Surface)
                            .clickable { controller.playSuggestion(song) }
                            .padding(horizontal = 16.dp, vertical = 15.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(14.dp),
                    ) {
                        if (state.resolvingSuggestionId == song.catalogId)
                            CircularProgressIndicator(Modifier.size(25.dp), strokeWidth = 2.dp)
                        else
                            Icon(
                                Icons.Filled.PlayArrow,
                                "Слушать",
                                Modifier.size(25.dp),
                                tint = RiffunaColors.Coral,
                            )
                        Column(Modifier.weight(1f)) {
                            Text(
                                song.title,
                                style = MaterialTheme.typography.bodyLarge,
                                fontWeight = FontWeight.Medium,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                            )
                            Text(
                                song.artist,
                                Modifier.padding(top = 5.dp),
                                style = MaterialTheme.typography.bodySmall,
                                color = RiffunaColors.Secondary,
                            )
                        }
                        song.genres.firstOrNull()?.let { SmallTag(it) }
                    }
                }
            }
    }
}
