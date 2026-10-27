@file:OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)

package riffuna.desktop.ui

import androidx.compose.animation.*
import androidx.compose.animation.core.*
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.*
import androidx.compose.foundation.shape.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.*
import androidx.compose.ui.draw.*
import androidx.compose.ui.graphics.*
import androidx.compose.ui.graphics.drawscope.clipRect
import androidx.compose.ui.text.*
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.*
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import riffuna.core.*

@Composable
fun LyricsPanel(
    controller: RiffunaController,
    screenState: AppState,
    onImport: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val playbackFlow =
        remember(controller) { controller.state.map { it.playback }.distinctUntilChanged() }
    val playback by playbackFlow.collectAsState(initial = screenState.playback)
    val state = screenState.copy(playback = playback)
    val packet = state.lyricsPacket
    Column(modifier) {
        Row(
            Modifier.fillMaxWidth().padding(bottom = 14.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                "Текст песни",
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.SemiBold,
                modifier = Modifier.weight(1f),
            )
            ActionIcon(
                Icons.Outlined.Refresh,
                "Обновить текст",
                controller::reloadLyrics,
                enabled = !state.lyricsLoading,
            )
            ActionIcon(Icons.Outlined.FileOpen, "Импорт LRC или TTML", onImport)
            ActionIcon(
                if (state.lyricsFocus) Icons.Outlined.CloseFullscreen
                else Icons.Outlined.OpenInFull,
                "Фокус на тексте · F2",
                { controller.setLyricsFocus(!state.lyricsFocus) },
                active = state.lyricsFocus,
            )
        }
        if (state.lyricsLoading && packet.lines.isEmpty() && packet.plainText.isBlank())
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator(Modifier.size(28.dp), strokeWidth = 2.dp)
            }
        else if (
            packet.state == "plain" || packet.lines.isEmpty() && packet.plainText.isNotBlank()
        ) {
            Text(
                "Без точной синхронизации",
                style = MaterialTheme.typography.labelMedium,
                color = RiffunaColors.Secondary,
            )
            Column(
                Modifier.weight(1f)
                    .verticalScroll(rememberScrollState())
                    .padding(top = 20.dp, bottom = 48.dp)
            ) {
                androidx.compose.foundation.text.selection.SelectionContainer {
                    Text(
                        packet.plainText,
                        style = MaterialTheme.typography.headlineSmall.copy(lineHeight = 38.sp),
                        color = RiffunaColors.Text,
                    )
                }
            }
        } else if (packet.lines.isEmpty())
            Column(
                Modifier.fillMaxSize(),
                verticalArrangement = Arrangement.Center,
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Icon(Icons.Outlined.Lyrics, null, Modifier.size(46.dp), tint = RiffunaColors.Muted)
                Spacer(Modifier.height(18.dp))
                Text(
                    if (packet.state == "instrumental") "Инструментальная запись"
                    else "Текст пока не найден",
                    style = MaterialTheme.typography.titleLarge,
                )
                Text(
                    packet.message.ifBlank { "Можно повторить поиск или открыть свой LRC / TTML" },
                    Modifier.padding(top = 8.dp),
                    style = MaterialTheme.typography.bodyMedium,
                    color = RiffunaColors.Secondary,
                )
                Row(Modifier.padding(top = 18.dp)) {
                    TextButton(onClick = controller::reloadLyrics) { Text("Повторить поиск") }
                    TextButton(onClick = onImport) { Text("Открыть файл") }
                }
            }
        else {
            val position = remember(state.current?.id) { Animatable(state.positionMs.toFloat()) }
            val reduced = LocalReducedMotion.current
            LaunchedEffect(state.positionMs, state.playing, reduced) {
                if (
                    reduced ||
                        !state.playing ||
                        kotlin.math.abs(position.value - state.positionMs) > 600
                )
                    position.snapTo(state.positionMs.toFloat())
                else
                    position.animateTo(state.positionMs.toFloat(), tween(90, easing = LinearEasing))
            }
            val active = packet.lines.indexOfLast { it.startMs <= state.positionMs }
            val list = rememberLazyListState()
            val scope = rememberCoroutineScope()
            var automatic by remember { mutableStateOf(false) }
            var manualUntil by remember { mutableLongStateOf(0L) }
            LaunchedEffect(list.isScrollInProgress) {
                if (list.isScrollInProgress && !automatic)
                    manualUntil = System.currentTimeMillis() + 6000
            }
            LaunchedEffect(active, state.lyricsFocus) {
                if (active >= 0 && System.currentTimeMillis() >= manualUntil) {
                    automatic = true
                    try {
                        if (reduced) list.scrollToItem(active) else list.animateScrollToItem(active)
                    } finally {
                        automatic = false
                    }
                }
            }
            BoxWithConstraints(Modifier.weight(1f).fillMaxWidth()) {
                LazyColumn(
                    Modifier.fillMaxSize(),
                    state = list,
                    contentPadding =
                        PaddingValues(top = maxHeight * .23f, bottom = maxHeight * .5f),
                    verticalArrangement = Arrangement.spacedBy(22.dp),
                ) {
                    itemsIndexed(packet.lines, key = { index, line -> "$index:${line.startMs}" }) {
                        index,
                        line ->
                        val selected = index == active
                        val opacity by
                            animateFloatAsState(
                                if (selected) 1f else if (index < active) .4f else .56f,
                                tween(if (reduced) 0 else 250),
                                label = "lyric line opacity",
                            )
                        val scale by
                            animateFloatAsState(
                                if (selected) 1f else .96f,
                                tween(if (reduced) 0 else 250),
                                label = "lyric line scale",
                            )
                        val end =
                            line.endMs
                                ?: packet.lines.getOrNull(index + 1)?.startMs
                                ?: state.durationMs
                        val words =
                            remember(line, end) {
                                line.words.ifEmpty {
                                    LyricTiming.estimatedWords(line.text, line.startMs, end)
                                }
                            }
                        val textStyle =
                            MaterialTheme.typography.headlineMedium.copy(
                                fontSize = if (state.lyricsFocus) 42.sp else 30.sp,
                                lineHeight = if (state.lyricsFocus) 53.sp else 40.sp,
                                fontWeight = FontWeight.SemiBold,
                            )
                        Box(
                            Modifier.fillMaxWidth()
                                .graphicsLayer {
                                    alpha = opacity
                                    scaleX = scale
                                    scaleY = scale
                                    transformOrigin = TransformOrigin(0f, .5f)
                                }
                                .clickable {
                                    manualUntil = 0
                                    controller.seek(line.startMs)
                                }
                        ) {
                            if (selected && words.isNotEmpty())
                                FlowRow(
                                    Modifier.fillMaxWidth(),
                                    horizontalArrangement = Arrangement.spacedBy(0.dp),
                                ) {
                                    words.forEach { word ->
                                        val progress =
                                            ((position.value - word.startMs) /
                                                    (word.endMs - word.startMs).coerceAtLeast(1))
                                                .coerceIn(0f, 1f)
                                        Box {
                                            Text(
                                                word.text,
                                                style = textStyle,
                                                color = RiffunaColors.Secondary.copy(alpha = .48f),
                                            )
                                            Text(
                                                word.text,
                                                style = textStyle,
                                                color = RiffunaColors.Text,
                                                modifier =
                                                    Modifier.drawWithContent {
                                                        clipRect(right = size.width * progress) {
                                                            this@drawWithContent.drawContent()
                                                        }
                                                    },
                                            )
                                        }
                                    }
                                }
                            else Text(line.text, style = textStyle, color = RiffunaColors.Text)
                        }
                    }
                }
                if (System.currentTimeMillis() < manualUntil && active >= 0)
                    FilledTonalButton(
                        onClick = {
                            manualUntil = 0
                            scope.launch {
                                automatic = true
                                try {
                                    if (reduced) list.scrollToItem(active)
                                    else list.animateScrollToItem(active)
                                } finally {
                                    automatic = false
                                }
                            }
                        },
                        modifier = Modifier.align(Alignment.BottomEnd).padding(12.dp),
                    ) {
                        Text("К текущей строке")
                    }
            }
            Row(
                Modifier.padding(top = 10.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Text(
                    if (packet.approximateWords) "Подсветка слов приблизительная"
                    else "Синхронизация по словам",
                    style = MaterialTheme.typography.labelSmall,
                    color = RiffunaColors.Muted,
                )
                if (packet.source.isNotBlank())
                    Text(
                        "· ${packet.source}",
                        style = MaterialTheme.typography.labelSmall,
                        color = RiffunaColors.Muted,
                    )
            }
        }
    }
}

@Composable
fun ExpandedPlayer(
    controller: RiffunaController,
    state: AppState,
    coverModifier: Modifier,
    onImport: () -> Unit,
    onPlaylist: (List<Track>) -> Unit,
) {
    Column(Modifier.fillMaxSize().background(RiffunaColors.Background)) {
        Row(
            Modifier.fillMaxWidth().height(60.dp).padding(horizontal = 24.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            ActionIcon(
                Icons.Outlined.KeyboardArrowDown,
                "Свернуть плеер",
                { controller.openNowPlaying(false) },
            )
            Text(
                "Сейчас играет",
                Modifier.weight(1f).padding(start = 12.dp),
                style = MaterialTheme.typography.titleSmall,
                color = RiffunaColors.Secondary,
            )
            state.current?.let { track ->
                if (!track.isLocalFile)
                    TextButton(onClick = { controller.findVersions(track) }) {
                        Text("Другие записи")
                    }
                ActionIcon(
                    Icons.Outlined.PlaylistAdd,
                    "Добавить в плейлист",
                    { onPlaylist(listOf(track)) },
                )
            }
        }
        Row(
            Modifier.weight(1f).fillMaxWidth().padding(horizontal = 36.dp, vertical = 12.dp),
            horizontalArrangement = Arrangement.spacedBy(48.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            AnimatedVisibility(
                !state.lyricsFocus,
                enter =
                    fadeIn(tween(if (state.reducedMotion) 0 else 180)) +
                        expandHorizontally(tween(if (state.reducedMotion) 0 else 220)),
                exit =
                    fadeOut(tween(if (state.reducedMotion) 0 else 100)) +
                        shrinkHorizontally(tween(if (state.reducedMotion) 0 else 180)),
            ) {
                BoxWithConstraints(Modifier.widthIn(min = 220.dp, max = 360.dp).fillMaxHeight()) {
                    val side = minOf(maxWidth, (maxHeight - 140.dp).coerceAtLeast(180.dp))
                    Column(
                        Modifier.fillMaxSize(),
                        horizontalAlignment = Alignment.CenterHorizontally,
                        verticalArrangement = Arrangement.Center,
                    ) {
                        Artwork(
                            state.current?.thumbnail.orEmpty(),
                            coverModifier.size(side),
                            state.current?.title,
                            18.dp,
                        )
                        Spacer(Modifier.height(22.dp))
                        Text(
                            state.current?.title.orEmpty(),
                            style = MaterialTheme.typography.headlineSmall,
                            fontWeight = FontWeight.Bold,
                            maxLines = 2,
                            modifier = Modifier.fillMaxWidth(),
                        )
                        Text(
                            state.current?.artist.orEmpty(),
                            Modifier.fillMaxWidth().padding(top = 8.dp),
                            style = MaterialTheme.typography.titleMedium,
                            color = RiffunaColors.Secondary,
                        )
                    }
                }
            }
            LyricsPanel(controller, state, onImport, Modifier.weight(1f).fillMaxHeight())
        }
        PlayerBar(controller, state, showCover = false)
    }
}
