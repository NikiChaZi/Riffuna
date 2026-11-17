package riffuna.desktop.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.*
import androidx.compose.ui.unit.dp
import java.awt.FileDialog
import java.awt.Frame
import java.awt.KeyboardFocusManager
import java.nio.file.Files
import java.nio.file.Path
import java.nio.file.StandardCopyOption
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import riffuna.catalog.readRiffunaCollection
import riffuna.core.RiffunaController

@Composable
internal fun CollectionSettings(controller: RiffunaController) {
    val scope = rememberCoroutineScope()
    var busy by remember { mutableStateOf(false) }

    fun transfer(export: Boolean) {
        val file = chooseCollectionFile(export) ?: return
        busy = true
        scope.launch {
            try {
                if (export) {
                    val content = controller.exportCollection()
                    withContext(Dispatchers.IO) { saveCollectionFile(file, content) }
                    controller.notifyUser("Коллекция сохранена")
                } else {
                    val content =
                        withContext(Dispatchers.IO) {
                            Files.newInputStream(file).use { it.readRiffunaCollection() }
                        }
                    controller.importCollection(content)
                }
            } catch (e: CancellationException) {
                throw e
            } catch (_: Exception) {
                controller.notifyUser(
                    "Не удалось " + if (export) "сохранить коллекцию" else "прочитать коллекцию"
                )
            } finally {
                busy = false
            }
        }
    }

    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text("Перенос коллекции", style = MaterialTheme.typography.titleSmall)
        Text(
            "Лайки, плейлисты и выбранные записи. Локальные аудиофайлы нужно перенести отдельно.",
            style = MaterialTheme.typography.bodySmall,
        )
        Row {
            TextButton(onClick = { transfer(true) }, enabled = !busy) { Text("Экспортировать") }
            TextButton(onClick = { transfer(false) }, enabled = !busy) { Text("Импортировать") }
        }
    }
}

private fun chooseCollectionFile(export: Boolean): Path? {
    val owner = KeyboardFocusManager.getCurrentKeyboardFocusManager().activeWindow as? Frame
    val dialog =
        FileDialog(
            owner,
            if (export) "Сохранить коллекцию Riffuna" else "Импортировать коллекцию Riffuna",
            if (export) FileDialog.SAVE else FileDialog.LOAD,
        )
    return try {
        dialog.file = if (export) "Riffuna-collection.json" else "*.json"
        dialog.isVisible = true
        dialog.file?.let { name -> Path.of(dialog.directory, name) }
    } finally {
        dialog.dispose()
    }
}

private fun saveCollectionFile(file: Path, content: String) {
    val temporary =
        Files.createTempFile(file.toAbsolutePath().parent, ".riffuna-collection-", ".tmp")
    try {
        Files.writeString(temporary, content)
        Files.move(temporary, file, StandardCopyOption.REPLACE_EXISTING)
    } finally {
        Files.deleteIfExists(temporary)
    }
}
