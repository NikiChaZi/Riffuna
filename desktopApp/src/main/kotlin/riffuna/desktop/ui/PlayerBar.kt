@file:OptIn(androidx.compose.foundation.ExperimentalFoundationApi::class)

package riffuna.desktop.ui

import androidx.compose.animation.core.*
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.*
import androidx.compose.ui.draw.*
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.*
import riffuna.core.*

@Composable
fun PlayerBar(
    controller: RiffunaController,
    state: AppState,
    coverModifier: Modifier = Modifier,
    showCover: Boolean = true,
) {
    var output by remember { mutableStateOf(false) }
    var rememberedVolume by remember { mutableFloatStateOf(.65f) }
    Surface(color = Color(0xFF191D21)) {
        Column {
            HorizontalDivider(color = RiffunaColors.Border)
            Row(
                Modifier.fillMaxWidth().height(104.dp).padding(horizontal = 20.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(18.dp),
            ) {
                Row(
                    Modifier.weight(.95f),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    if (showCover)
                        Artwork(
                            state.current?.thumbnail.orEmpty(),
                            coverModifier.size(56.dp).clickable(enabled = state.current != null) {
                                controller.setLyricsFocus(false)
                                controller.openNowPlaying(true)
                            },
                            state.current?.title,
                            8.dp,
                        )
                    Column(
                        Modifier.weight(1f).clickable(enabled = state.current != null) {
                            controller.openNowPlaying(true)
                        },
                        verticalArrangement = Arrangement.spacedBy(5.dp),
                    ) {
                        Text(
                            state.current?.title ?: "Выбери свою музыку",
                            style = MaterialTheme.typography.bodyMedium,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                        Text(
                            state.current?.artist ?: "Поиск, лайки и твои плейлисты",
                            style = MaterialTheme.typography.labelMedium,
                            color = RiffunaColors.Secondary,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                        if (state.playbackError != null)
                            Text(
                                state.playbackError.orEmpty(),
                                style = MaterialTheme.typography.labelSmall,
                                color = RiffunaColors.Coral,
                                maxLines = 2,
                                overflow = TextOverflow.Ellipsis,
                            )
                        else if (state.loading || state.playbackLoading)
                            Text(
                                "Подключаем запись…",
                                style = MaterialTheme.typography.labelSmall,
                                color = RiffunaColors.Secondary,
                            )
                    }
                    state.current?.let { track ->
                        ActionIcon(
                            if (state.likes.any { it.id == track.id }) Icons.Filled.Favorite
                            else Icons.Outlined.FavoriteBorder,
                            "Мне нравится",
                            { controller.toggleLike(track) },
                            active = state.likes.any { it.id == track.id },
                            size = 30.dp,
                        )
                    }
                }
                Column(Modifier.weight(1.4f), horizontalAlignment = Alignment.CenterHorizontally) {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(14.dp),
                    ) {
                        ActionIcon(
                            Icons.Outlined.Shuffle,
                            "Перемешать",
                            controller::toggleShuffle,
                            active = state.shuffle,
                            size = 32.dp,
                        )
                        ActionIcon(
                            Icons.Filled.SkipPrevious,
                            "Предыдущий трек",
                            controller::previous,
                            size = 34.dp,
                        )
                        val scale by
                            animateFloatAsState(
                                if (state.playbackLoading) .94f else 1f,
                                tween(if (LocalReducedMotion.current) 0 else 170),
                                label = "play state",
                            )
                        FilledIconButton(
                            onClick = controller::toggle,
                            enabled = state.current != null || state.queue.isNotEmpty(),
                            modifier = Modifier.size(44.dp).scale(scale),
                            colors =
                                IconButtonDefaults.filledIconButtonColors(
                                    containerColor = RiffunaColors.Coral,
                                    contentColor = RiffunaColors.Background,
                                ),
                        ) {
                            if (state.playbackLoading)
                                CircularProgressIndicator(
                                    Modifier.size(20.dp),
                                    strokeWidth = 2.dp,
                                    color = RiffunaColors.Background,
                                )
                            else
                                Icon(
                                    if (state.playing) Icons.Filled.Pause
                                    else Icons.Filled.PlayArrow,
                                    if (state.playing) "Пауза" else "Слушать",
                                    Modifier.size(28.dp),
                                )
                        }
                        ActionIcon(
                            Icons.Filled.SkipNext,
                            "Следующий трек",
                            controller::next,
                            size = 34.dp,
                        )
                        ActionIcon(
                            if (state.repeatMode == RepeatMode.ONE) Icons.Outlined.RepeatOne
                            else Icons.Outlined.Repeat,
                            when (state.repeatMode) {
                                RepeatMode.ONE -> "Повторяется один трек"
                                RepeatMode.ALL -> "Повторяется очередь"
                                else -> "Повтор выключен"
                            },
                            controller::cycleRepeat,
                            active = state.repeatMode != RepeatMode.OFF,
                            size = 32.dp,
                        )
                    }
                    Row(
                        Modifier.fillMaxWidth().padding(top = 4.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                        Text(
                            timeLabel(state.positionMs),
                            style = MaterialTheme.typography.labelSmall,
                            color = RiffunaColors.Secondary,
                            modifier = Modifier.width(32.dp),
                        )
                        ProgressSlider(
                            if (state.durationMs > 0) state.positionMs.toFloat() / state.durationMs
                            else 0f,
                            {},
                            Modifier.weight(1f),
                            onCommit = { controller.seek((it * state.durationMs).toLong()) },
                            enabled = state.seekable && state.durationMs > 0,
                            label = { timeLabel((it * state.durationMs).toLong()) },
                        )
                        Text(
                            timeLabel(state.durationMs),
                            style = MaterialTheme.typography.labelSmall,
                            color = RiffunaColors.Secondary,
                            modifier = Modifier.width(32.dp),
                        )
                    }
                }
                Row(
                    Modifier.weight(.8f),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    ActionIcon(
                        Icons.Outlined.Lyrics,
                        "Текст песни",
                        {
                            if (!state.expanded) {
                                controller.openNowPlaying(true)
                                controller.setLyricsFocus(true)
                            } else controller.setLyricsFocus(!state.lyricsFocus)
                        },
                        active = state.expanded,
                        enabled = state.current != null,
                        size = 30.dp,
                    )
                    ActionIcon(
                        Icons.Outlined.QueueMusic,
                        "Очередь",
                        {
                            if (state.expanded) {
                                controller.openNowPlaying(false)
                                if (!state.queueVisible) controller.toggleQueue()
                            } else controller.toggleQueue()
                        },
                        active = state.queueVisible && !state.expanded,
                        size = 30.dp,
                    )
                    Box {
                        ActionIcon(
                            Icons.Outlined.Speaker,
                            "Устройство вывода",
                            {
                                controller.refreshAudioDevices()
                                output = true
                            },
                            size = 30.dp,
                        )
                        DropdownMenu(output, { output = false }) {
                            state.audioDevices.forEach { device ->
                                DropdownMenuItem(
                                    text = { Text(device.name) },
                                    onClick = {
                                        controller.selectAudioDevice(device.id)
                                        output = false
                                    },
                                    leadingIcon = {
                                        if (device.id == state.audioDevice)
                                            Icon(Icons.Outlined.Check, null)
                                    },
                                )
                            }
                        }
                    }
                    ActionIcon(
                        if (state.volume == 0f) Icons.Outlined.VolumeOff
                        else Icons.Outlined.VolumeUp,
                        if (state.volume == 0f) "Включить звук" else "Выключить звук",
                        {
                            if (state.volume > 0) {
                                rememberedVolume = state.volume
                                controller.setVolume(0f)
                            } else controller.setVolume(rememberedVolume)
                        },
                        size = 28.dp,
                    )
                    ProgressSlider(
                        state.volume,
                        controller::setVolume,
                        Modifier.weight(1f),
                        label = { "Громкость: ${(it*100).toInt()}%" },
                    )
                }
            }
        }
    }
}
