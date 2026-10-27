@file:OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)

package riffuna.desktop.ui

import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.*
import androidx.compose.foundation.shape.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.*
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.*
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import riffuna.core.*

@Composable
fun PlaylistEditor(
    original: PlaylistSummary?,
    onDismiss: () -> Unit,
    onSave: (String, String) -> Unit,
    onDelete: (() -> Unit)? = null,
) {
    var name by remember(original?.id) { mutableStateOf(original?.name.orEmpty()) }
    var description by remember(original?.id) { mutableStateOf(original?.description.orEmpty()) }
    var deleting by remember { mutableStateOf(false) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = {
            Text(
                if (deleting) "Удалить плейлист?"
                else if (original == null) "Новый плейлист" else "Изменить плейлист"
            )
        },
        text = {
            if (deleting)
                Text("Плейлист «${original?.name}» будет удалён. Лайки и история сохранятся.")
            else
                Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
                    OutlinedTextField(
                        name,
                        { if (it.length <= 100) name = it },
                        label = { Text("Название") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    OutlinedTextField(
                        description,
                        { if (it.length <= 2000) description = it },
                        label = { Text("Описание") },
                        minLines = 2,
                        maxLines = 4,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    if (onDelete != null)
                        TextButton(onClick = { deleting = true }) {
                            Text("Удалить плейлист", color = MaterialTheme.colorScheme.error)
                        }
                }
        },
        confirmButton = {
            TextButton(
                enabled = deleting || name.trim().isNotEmpty(),
                onClick = { if (deleting) onDelete?.invoke() else onSave(name.trim(), description) },
            ) {
                Text(if (deleting) "Удалить" else "Сохранить")
            }
        },
        dismissButton = {
            TextButton(onClick = { if (deleting) deleting = false else onDismiss() }) {
                Text("Отмена")
            }
        },
    )
}

@Composable
fun AddPlaylistDialog(
    playlists: List<PlaylistSummary>,
    tracks: List<Track>,
    onDismiss: () -> Unit,
    onPick: (Long) -> Unit,
    onCreate: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Добавить в плейлист") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text(trackCount(tracks.size), color = RiffunaColors.Secondary)
                LazyColumn(
                    Modifier.heightIn(max = 340.dp),
                    verticalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    items(playlists, key = { it.id }) { playlist ->
                        Row(
                            Modifier.fillMaxWidth()
                                .clickable { onPick(playlist.id) }
                                .padding(vertical = 7.dp),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(12.dp),
                        ) {
                            Artwork(playlist.thumbnail, Modifier.size(40.dp), playlist.name, 6.dp)
                            Column {
                                Text(playlist.name, maxLines = 1, overflow = TextOverflow.Ellipsis)
                                Text(
                                    trackCount(playlist.trackCount),
                                    style = MaterialTheme.typography.labelSmall,
                                    color = RiffunaColors.Secondary,
                                )
                            }
                        }
                    }
                }
                OutlinedButton(onClick = onCreate) {
                    Icon(Icons.Outlined.Add, null, Modifier.size(18.dp))
                    Spacer(Modifier.width(8.dp))
                    Text("Создать плейлист")
                }
            }
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text("Закрыть") } },
    )
}

@Composable
fun VersionsDialog(controller: RiffunaController, state: AppState) {
    val reference = state.versionReference ?: return
    var chosen by remember(reference.id) { mutableStateOf<RecordingVersion?>(null) }
    Dialog(
        onDismissRequest = controller::closeVersions,
        properties = DialogProperties(usePlatformDefaultWidth = false),
    ) {
        Surface(
            modifier = Modifier.widthIn(min = 550.dp, max = 740.dp).fillMaxHeight(.83f),
            shape = RoundedCornerShape(18.dp),
            color = RiffunaColors.Surface,
            border = BorderStroke(1.dp, RiffunaColors.Border),
        ) {
            Column(Modifier.padding(24.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        "Другие записи",
                        style = MaterialTheme.typography.headlineSmall,
                        fontWeight = FontWeight.Bold,
                        modifier = Modifier.weight(1f),
                    )
                    ActionIcon(Icons.Outlined.Close, "Закрыть", controller::closeVersions)
                }
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(14.dp),
                ) {
                    Artwork(reference.thumbnail, Modifier.size(52.dp), reference.title, 8.dp)
                    Column(Modifier.weight(1f)) {
                        Text(reference.title, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        Text(
                            reference.artist + " · " + timeLabel(reference.duration * 1000L),
                            Modifier.padding(top = 5.dp),
                            style = MaterialTheme.typography.bodySmall,
                            color = RiffunaColors.Secondary,
                        )
                    }
                }
                Text(
                    "Названия загрузок не подтверждают отсутствие цензуры. Выбери подходящую запись на слух.",
                    style = MaterialTheme.typography.bodySmall,
                    color = RiffunaColors.Secondary,
                )
                if (state.versionsLoading) LinearProgressIndicator(Modifier.fillMaxWidth())
                if (state.versionError.isNotBlank())
                    Text(state.versionError, color = MaterialTheme.colorScheme.error)
                if (state.versions.isEmpty())
                    Box(Modifier.weight(1f).fillMaxWidth(), contentAlignment = Alignment.Center) {
                        Text(
                            if (state.versionsLoading) "Проверяем другие загрузки…"
                            else "Подходящих записей не найдено",
                            color = RiffunaColors.Secondary,
                        )
                    }
                else
                    LazyColumn(
                        Modifier.weight(1f),
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        items(state.versions, key = { it.track.id }) { version ->
                            Surface(
                                color =
                                    if (chosen?.track?.id == version.track.id)
                                        RiffunaColors.Selected
                                    else RiffunaColors.Background,
                                shape = RoundedCornerShape(10.dp),
                                modifier = Modifier.fillMaxWidth().clickable { chosen = version },
                            ) {
                                Column(
                                    Modifier.padding(14.dp),
                                    verticalArrangement = Arrangement.spacedBy(7.dp),
                                ) {
                                    Row(verticalAlignment = Alignment.CenterVertically) {
                                        SmallTag(version.label, coral = true)
                                        Spacer(Modifier.weight(1f))
                                        Text(
                                            timeLabel(version.track.duration * 1000L),
                                            style = MaterialTheme.typography.labelSmall,
                                            color = RiffunaColors.Secondary,
                                        )
                                    }
                                    Text(version.track.title, fontWeight = FontWeight.SemiBold)
                                    Text(
                                        version.evidence,
                                        style = MaterialTheme.typography.bodySmall,
                                        color = RiffunaColors.Secondary,
                                    )
                                }
                            }
                        }
                    }
                Row(
                    Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(10.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    TextButton(onClick = { controller.resetVersion(reference) }) {
                        Text("Исходная запись")
                    }
                    Spacer(Modifier.weight(1f))
                    TextButton(onClick = controller::closeVersions) { Text("Закрыть") }
                    Button(
                        enabled = chosen != null,
                        onClick = { chosen?.let { controller.chooseVersion(reference, it.track) } },
                    ) {
                        Text("Слушать")
                    }
                }
            }
        }
    }
}

@Composable
fun SettingsDialog(controller: RiffunaController, state: AppState, onDismiss: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Настройки") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(20.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text("Меньше движения", fontWeight = FontWeight.Medium)
                        Text(
                            "Уменьшить анимации переходов",
                            style = MaterialTheme.typography.bodySmall,
                            color = RiffunaColors.Secondary,
                        )
                    }
                    Switch(state.reducedMotion, controller::setReducedMotion)
                }
                HorizontalDivider()
                Text("Устройство вывода", style = MaterialTheme.typography.titleSmall)
                Column(Modifier.heightIn(max = 220.dp).verticalScroll(rememberScrollState())) {
                    state.audioDevices.forEach { device ->
                        Row(
                            Modifier.fillMaxWidth()
                                .clickable { controller.selectAudioDevice(device.id) }
                                .padding(vertical = 4.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            RadioButton(
                                state.audioDevice == device.id,
                                { controller.selectAudioDevice(device.id) },
                            )
                            Text(device.name, style = MaterialTheme.typography.bodySmall)
                        }
                    }
                }
                Text(
                    "Полные аудиофайлы сохраняются в локальном кэше до 1 ГБ. Лайки, история и плейлисты хранятся отдельно от приложения.",
                    style = MaterialTheme.typography.bodySmall,
                    color = RiffunaColors.Secondary,
                )
            }
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text("Готово") } },
    )
}

@Composable
fun KeyboardDialog(onDismiss: () -> Unit) {
    val keys =
        listOf(
            "Пробел" to "Слушать / пауза",
            "Ctrl + ← / →" to "Предыдущий / следующий трек",
            "Ctrl + F" to "Поиск музыки",
            "Ctrl + Shift + F" to "Поиск внутри списка",
            "Ctrl + Q" to "Открыть очередь",
            "Ctrl + A" to "Выбрать весь список",
            "Ctrl / Shift + клик" to "Выделение нескольких записей",
            "Alt + ↑ / ↓" to "Переместить выбранный трек",
            "Alt + ← / →" to "Назад / вперёд",
            "Ctrl + Shift + S / R" to "Перемешивание / повтор",
            "F2" to "Фокус на тексте",
            "Esc" to "Свернуть плеер / снять выделение",
        )
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Горячие клавиши") },
        text = {
            Column(
                Modifier.verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                keys.forEach { (key, action) ->
                    Row {
                        Text(
                            key,
                            Modifier.width(170.dp),
                            color = RiffunaColors.Coral,
                            style = MaterialTheme.typography.bodySmall,
                        )
                        Text(action, style = MaterialTheme.typography.bodySmall)
                    }
                }
            }
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text("Готово") } },
    )
}
