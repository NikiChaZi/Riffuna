package riffuna.android

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import riffuna.core.Track

@Composable
internal fun AndroidOfflineScreen(
    offline: AndroidOffline,
    onBack: () -> Unit,
    onPlay: ((Track) -> Unit)? = null,
) {
    val entries by offline.entries.collectAsState()
    val capacity by offline.limitMiB.collectAsState()
    var choosingCapacity by remember { mutableStateOf(false) }
    var confirmClear by remember { mutableStateOf(false) }
    val used = entries.filter { it.status == AndroidOfflineStatus.Ready }.sumOf { it.bytes }

    Column(Modifier.fillMaxSize().padding(16.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            TextButton(onClick = onBack) { Text("Назад") }
            Text("Офлайн-загрузки", style = MaterialTheme.typography.titleLarge)
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Занято ${used / (1024 * 1024)} из $capacity МБ", Modifier.weight(1f))
            Column {
                TextButton(onClick = { choosingCapacity = true }) { Text("Лимит") }
                DropdownMenu(
                    expanded = choosingCapacity,
                    onDismissRequest = { choosingCapacity = false },
                ) {
                    offline.capacitiesMiB.forEach { value ->
                        DropdownMenuItem(
                            text = { Text("$value МБ") },
                            onClick = {
                                offline.setLimitMiB(value)
                                choosingCapacity = false
                            },
                        )
                    }
                }
            }
        }
        if (entries.isNotEmpty()) {
            Row {
                if (
                    entries.any {
                        it.status == AndroidOfflineStatus.Queued ||
                            it.status == AndroidOfflineStatus.Downloading
                    }
                ) {
                    TextButton(onClick = offline::cancelAll) { Text("Отменить все") }
                }
                TextButton(onClick = { confirmClear = true }) { Text("Очистить") }
            }
        } else {
            Text("Загрузок пока нет")
        }
        LazyColumn(verticalArrangement = Arrangement.spacedBy(12.dp)) {
            items(entries, key = { it.track.id }) { entry ->
                val track = entry.track
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text(track.title, style = MaterialTheme.typography.titleMedium)
                        Text(track.artist)
                        when (entry.status) {
                            AndroidOfflineStatus.Queued -> Text("В очереди")
                            AndroidOfflineStatus.Downloading -> {
                                val progress =
                                    (entry.bytes.toFloat() / entry.total).coerceIn(0f, 1f)
                                LinearProgressIndicator(
                                    progress = { progress },
                                    modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
                                )
                                Text("${(progress * 100).toInt()}%")
                            }
                            AndroidOfflineStatus.Ready -> Text(entry.error ?: "Доступен офлайн")
                            AndroidOfflineStatus.Failed -> Text(entry.error.orEmpty())
                        }
                    }
                    when (entry.status) {
                        AndroidOfflineStatus.Queued,
                        AndroidOfflineStatus.Downloading ->
                            TextButton(onClick = { offline.cancel(track.id) }) { Text("Отменить") }
                        AndroidOfflineStatus.Ready -> {
                            if (onPlay != null) {
                                TextButton(onClick = { onPlay(track) }) { Text("Играть") }
                            }
                            TextButton(onClick = { offline.delete(track.id) }) { Text("Удалить") }
                        }
                        AndroidOfflineStatus.Failed -> {
                            TextButton(onClick = { offline.enqueue(track) }) { Text("Повторить") }
                            TextButton(onClick = { offline.delete(track.id) }) { Text("Удалить") }
                        }
                    }
                }
            }
        }
    }
    if (confirmClear) {
        AlertDialog(
            onDismissRequest = { confirmClear = false },
            title = { Text("Очистить загрузки?") },
            text = { Text("Сохранённые треки будут удалены, текущие загрузки отменены.") },
            confirmButton = {
                TextButton(
                    onClick = {
                        offline.deleteAll()
                        confirmClear = false
                    }
                ) {
                    Text("Очистить")
                }
            },
            dismissButton = { TextButton(onClick = { confirmClear = false }) { Text("Назад") } },
        )
    }
}
