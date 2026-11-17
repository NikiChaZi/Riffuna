package riffuna.desktop.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import java.util.Locale
import riffuna.core.RiffunaController
import riffuna.core.Track
import riffuna.core.isLocalFile
import riffuna.desktop.OfflineDownloads
import riffuna.desktop.offlineGib

internal val LocalOfflineDownloads = staticCompositionLocalOf<OfflineDownloads?> { null }

@Composable
internal fun OfflineTrackMenuItem(track: Track, onClose: () -> Unit) {
    val downloads = LocalOfflineDownloads.current ?: return
    if (track.isLocalFile) return
    val state by downloads.state.collectAsState()
    val id = downloads.recording(track).id
    val saved = state.saved[id] != null
    val task = state.tasks[id]
    DropdownMenuItem(
        text = {
            Text(
                when {
                    saved -> "Убрать из скачанного"
                    task?.error != null -> "Повторить скачивание"
                    task?.percent != null -> "Скачивание · ${task.percent}%"
                    task != null -> "Ожидает скачивания"
                    else -> "Сохранить для офлайна"
                }
            )
        },
        enabled = saved || task == null || task.error != null,
        onClick = {
            if (saved) downloads.remove(id) else downloads.save(listOf(track))
            onClose()
        },
        leadingIcon = {
            Icon(if (saved) Icons.Outlined.DeleteOutline else Icons.Outlined.Download, null)
        },
    )
}

@Composable
internal fun OfflineDownloadsScreen(downloads: OfflineDownloads, controller: RiffunaController) {
    val state by downloads.state.collectAsState()
    val saved =
        remember(state.saved) {
            state.saved.values.sortedWith(
                compareBy({ it.track.artist.lowercase() }, { it.track.title.lowercase() })
            )
        }
    val tasks = state.tasks.values.toList()
    var showLimits by remember { mutableStateOf(false) }
    Column(
        Modifier.fillMaxSize().padding(vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Row(
            Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(
                    "Скачанное",
                    style = MaterialTheme.typography.headlineSmall,
                    fontWeight = FontWeight.Bold,
                )
                Text(
                    "${saved.size} треков · ${offlineSize(state.used)} из ${offlineSize(state.limit)}",
                    color = RiffunaColors.Secondary,
                    style = MaterialTheme.typography.bodyMedium,
                )
            }
            Box {
                OutlinedButton(onClick = { showLimits = true }) { Text("Лимит хранения") }
                DropdownMenu(showLimits, { showLimits = false }) {
                    for (size in listOf(1L, 3L, 5L, 10L, 20L)) {
                        DropdownMenuItem(
                            text = { Text("$size ГБ") },
                            onClick = {
                                downloads.setLimit(size * offlineGib)
                                showLimits = false
                            },
                            trailingIcon = {
                                if (state.limit == size * offlineGib)
                                    Icon(Icons.Outlined.Check, null)
                            },
                        )
                    }
                }
            }
            Button(
                onClick = {
                    controller.playContext(saved.map { it.track }, exactRecordings = true)
                },
                enabled = saved.isNotEmpty(),
            ) {
                Icon(Icons.Outlined.PlayArrow, null)
                Spacer(Modifier.width(6.dp))
                Text("Слушать всё")
            }
        }
        LinearProgressIndicator(
            progress = { (state.used.toDouble() / state.limit).toFloat().coerceIn(0f, 1f) },
            modifier = Modifier.fillMaxWidth(),
        )
        state.message?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        if (saved.isEmpty() && tasks.isEmpty()) {
            Text(
                "Сохрани трек или плейлист через меню действий. Скачанные записи доступны без сети.",
                color = RiffunaColors.Secondary,
                modifier = Modifier.padding(vertical = 24.dp),
            )
        } else {
            LazyColumn(
                Modifier.fillMaxWidth().weight(1f),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                items(tasks, key = { "task-${it.track.id}" }) { task ->
                    DownloadRow(task.track) {
                        if (task.error != null) {
                            Column(Modifier.weight(1f)) {
                                Text(
                                    task.error,
                                    color = MaterialTheme.colorScheme.error,
                                    style = MaterialTheme.typography.bodySmall,
                                )
                            }
                            TextButton(onClick = { downloads.retry(task.track) }) {
                                Text("Повторить")
                            }
                            ActionIcon(
                                Icons.Outlined.Close,
                                "Убрать ошибку",
                                { downloads.remove(task.track.id) },
                            )
                        } else {
                            Column(
                                Modifier.width(170.dp),
                                verticalArrangement = Arrangement.spacedBy(5.dp),
                            ) {
                                Text(
                                    task.percent?.let { "Скачивание · $it%" }
                                        ?: "Ожидает скачивания",
                                    color = RiffunaColors.Secondary,
                                    style = MaterialTheme.typography.bodySmall,
                                )
                                if (task.percent != null)
                                    LinearProgressIndicator(
                                        progress = { task.percent / 100f },
                                        modifier = Modifier.fillMaxWidth(),
                                    )
                            }
                        }
                    }
                }
                items(saved, key = { "saved-${it.track.id}" }) { entry ->
                    DownloadRow(entry.track) {
                        Text(
                            offlineSize(entry.audio.bytes),
                            color = RiffunaColors.Secondary,
                            style = MaterialTheme.typography.bodySmall,
                        )
                        ActionIcon(
                            Icons.Outlined.PlayArrow,
                            "Слушать без сети",
                            {
                                controller.playContext(
                                    saved.map { it.track },
                                    saved.indexOf(entry),
                                    exactRecordings = true,
                                )
                            },
                        )
                        ActionIcon(
                            Icons.Outlined.DeleteOutline,
                            "Удалить скачанный файл",
                            { downloads.remove(entry.track.id) },
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun DownloadRow(track: Track, actions: @Composable RowScope.() -> Unit) {
    Surface(color = RiffunaColors.Raised, shape = RoundedCornerShape(10.dp)) {
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 10.dp, vertical = 7.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Artwork(track.thumbnail, Modifier.size(36.dp), track.title, 5.dp)
            Column(Modifier.weight(1f)) {
                Text(track.title, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text(
                    track.artist,
                    color = RiffunaColors.Secondary,
                    style = MaterialTheme.typography.bodySmall,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            actions()
        }
    }
}

private fun offlineSize(bytes: Long): String =
    if (bytes >= offlineGib) String.format(Locale.ROOT, "%.1f ГБ", bytes.toDouble() / offlineGib)
    else if (bytes in 1L until 1024L * 1024L) String.format(Locale.ROOT, "%.0f КБ", bytes / 1024.0)
    else String.format(Locale.ROOT, "%.0f МБ", bytes / (1024.0 * 1024))
