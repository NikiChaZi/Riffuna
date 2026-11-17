package riffuna.desktop.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import java.awt.Desktop
import java.net.URI
import java.nio.file.Path
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import riffuna.core.LocalController
import riffuna.desktop.WindowsMediaSession
import riffuna.desktop.WindowsRelease
import riffuna.desktop.WindowsReleaseUpdater

private sealed interface UpdateState {
    data object Idle : UpdateState

    data object Checking : UpdateState

    data object Latest : UpdateState

    data class Ready(val release: WindowsRelease) : UpdateState

    data class Downloading(val fraction: Float) : UpdateState

    data class Error(val message: String) : UpdateState
}

private class WindowsUpdateActions(
    private val scope: CoroutineScope,
    val updater: WindowsReleaseUpdater,
    private val exit: () -> Unit,
) {
    val state = MutableStateFlow<UpdateState>(UpdateState.Idle)

    fun check() {
        if (state.value is UpdateState.Checking || state.value is UpdateState.Downloading) return
        state.value = UpdateState.Checking
        scope.launch {
            try {
                state.value = updater.check()?.let { UpdateState.Ready(it) } ?: UpdateState.Latest
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (failure: Exception) {
                state.value = UpdateState.Error(failure.message ?: "GitHub недоступен.")
            }
        }
    }

    fun install(release: WindowsRelease) {
        if (updater.portable || state.value != UpdateState.Ready(release)) return
        state.value = UpdateState.Downloading(0f)
        scope.launch {
            try {
                updater.prepareInstaller(release) { bytes ->
                    state.value = UpdateState.Downloading(bytes.toFloat() / release.size)
                }
                exit()
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (failure: Exception) {
                state.value =
                    UpdateState.Error(failure.message ?: "Не удалось получить установщик.")
            }
        }
    }
}

private val LocalWindowsUpdates = staticCompositionLocalOf<WindowsUpdateActions?> { null }

@Composable
internal fun ProvideWindowsIntegration(
    home: Path,
    data: Path,
    controller: LocalController,
    onExit: () -> Unit,
    content: @Composable () -> Unit,
) {
    val scope = rememberCoroutineScope()
    val latestExit by rememberUpdatedState(onExit)
    val updater = remember(home) { WindowsReleaseUpdater(home) }
    val actions = remember(scope, updater) { WindowsUpdateActions(scope, updater) { latestExit() } }
    LaunchedEffect(home, data, controller) { WindowsMediaSession.run(home, data, controller) }
    CompositionLocalProvider(
        LocalWindowsUpdates provides actions.takeIf { updater.available },
        content = content,
    )
}

@Composable
internal fun WindowsUpdatesSettings() {
    val actions = LocalWindowsUpdates.current ?: return
    val state by actions.state.collectAsState()
    Column(verticalArrangement = Arrangement.spacedBy(5.dp)) {
        Text("Обновления · ${actions.updater.version}", style = MaterialTheme.typography.titleSmall)
        when (val current = state) {
            UpdateState.Idle -> TextButton(actions::check) { Text("Проверить обновления") }
            UpdateState.Checking -> Text("Проверяем релизы GitHub…")
            UpdateState.Latest -> {
                Text("Более свежего установщика Windows пока нет.")
                TextButton(actions::check) { Text("Проверить снова") }
            }
            is UpdateState.Ready -> {
                Text("Доступна версия ${current.release.version}.")
                if (actions.updater.portable) {
                    Text("Для переносимой сборки открой страницу релиза.")
                    TextButton(
                        onClick = {
                            runCatching {
                                Desktop.getDesktop()
                                    .browse(
                                        URI(
                                            "https://github.com/NikiChaZi/Riffuna/releases/tag/v${current.release.version}"
                                        )
                                    )
                            }
                        }
                    ) {
                        Text("Открыть релиз")
                    }
                } else {
                    Text("После проверки файла Riffuna закроется и запустит установщик.")
                    TextButton(onClick = { actions.install(current.release) }) {
                        Text("Скачать и установить")
                    }
                }
            }
            is UpdateState.Downloading -> {
                LinearProgressIndicator(
                    progress = { current.fraction },
                    modifier = Modifier.fillMaxWidth(),
                )
                Text("Загрузка установщика · ${(current.fraction * 100).toInt()}%")
            }
            is UpdateState.Error -> {
                Text(
                    "Не удалось обновить Riffuna. ${current.message}",
                    style = MaterialTheme.typography.bodySmall,
                )
                TextButton(actions::check) { Text("Проверить снова") }
            }
        }
    }
}
