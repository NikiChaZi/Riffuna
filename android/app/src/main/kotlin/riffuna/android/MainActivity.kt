package riffuna.android

import android.Manifest
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.provider.OpenableColumns
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.lifecycle.lifecycleScope
import java.io.ByteArrayOutputStream
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import riffuna.catalog.readRiffunaCollection

class MainActivity : ComponentActivity() {
    private val graph
        get() = (application as RiffunaApplication).graph

    private var lyricTargetId: String? = null

    private val documents =
        registerForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris ->
            val accepted =
                uris.filter { uri ->
                    runCatching {
                            contentResolver.takePersistableUriPermission(
                                uri,
                                Intent.FLAG_GRANT_READ_URI_PERMISSION,
                            )
                        }
                        .isSuccess
                }
            graph.controller.importLocalFiles(accepted.map { it.toString() })
        }
    private val importCollection =
        registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
            if (uri != null)
                lifecycleScope.launch {
                    try {
                        val content =
                            withContext(Dispatchers.IO) {
                                checkNotNull(contentResolver.openInputStream(uri)).use {
                                    it.readRiffunaCollection()
                                }
                            }
                        graph.controller.importCollection(content)
                    } catch (e: CancellationException) {
                        throw e
                    } catch (_: Exception) {
                        graph.controller.notifyUser("Не удалось прочитать коллекцию")
                    }
                }
        }

    private val exportCollection =
        registerForActivityResult(ActivityResultContracts.CreateDocument("application/json")) { uri
            ->
            if (uri != null)
                lifecycleScope.launch {
                    try {
                        val content = graph.controller.exportCollection()
                        withContext(Dispatchers.IO) {
                            checkNotNull(contentResolver.openOutputStream(uri, "wt")).use {
                                it.write(content.encodeToByteArray())
                            }
                        }
                        graph.controller.notifyUser("Коллекция сохранена")
                    } catch (e: CancellationException) {
                        throw e
                    } catch (_: Exception) {
                        graph.controller.notifyUser("Не удалось сохранить коллекцию")
                    }
                }
        }

    private val importLyrics =
        registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
            val targetId = lyricTargetId
            lyricTargetId = null
            if (uri != null && targetId != null) {
                lifecycleScope.launch {
                    try {
                        val (text, format) =
                            withContext(Dispatchers.IO) {
                                val name =
                                    contentResolver
                                        .query(
                                            uri,
                                            arrayOf(OpenableColumns.DISPLAY_NAME),
                                            null,
                                            null,
                                            null,
                                        )
                                        ?.use { cursor ->
                                            if (cursor.moveToFirst()) cursor.getString(0) else null
                                        }
                                        .orEmpty()
                                val format = name.substringAfterLast('.', "").lowercase()
                                require(format in setOf("lrc", "ttml", "xml"))
                                val text =
                                    checkNotNull(contentResolver.openInputStream(uri)).use { stream
                                        ->
                                        val output = ByteArrayOutputStream()
                                        val buffer = ByteArray(8192)
                                        while (true) {
                                            val count = stream.read(buffer)
                                            if (count == -1) break
                                            require(output.size() + count <= MAX_LOCAL_LYRIC_BYTES)
                                            output.write(buffer, 0, count)
                                        }
                                        output
                                            .toByteArray()
                                            .decodeToString(throwOnInvalidSequence = true)
                                    }
                                text to format
                            }
                        if (graph.controller.state.value.current?.id == targetId) {
                            graph.controller.importLyrics(text, format)
                        } else {
                            graph.controller.notifyUser("Трек сменился. Выбери файл заново")
                        }
                    } catch (e: CancellationException) {
                        throw e
                    } catch (_: Exception) {
                        graph.controller.notifyUser("Не удалось прочитать файл LRC или TTML")
                    }
                }
            }
        }

    private val notifications =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) {}

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        lyricTargetId = savedInstanceState?.getString("lyric_target_id")
        enableEdgeToEdge(
            statusBarStyle = SystemBarStyle.dark(android.graphics.Color.TRANSPARENT),
            navigationBarStyle = SystemBarStyle.dark(android.graphics.Color.TRANSPARENT),
        )
        if (
            android.os.Build.VERSION.SDK_INT >= 33 &&
                !getPreferences(MODE_PRIVATE).getBoolean("notification_requested", false)
        ) {
            getPreferences(MODE_PRIVATE).edit().putBoolean("notification_requested", true).apply()
            notifications.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
        setContent {
            RiffunaTheme {
                MobileApp(
                    graph.controller,
                    importFiles = { documents.launch(arrayOf("audio/*")) },
                    onImportCollection = {
                        importCollection.launch(arrayOf("application/json", "text/plain"))
                    },
                    onExportCollection = { exportCollection.launch("Riffuna-collection.json") },
                    catalogSource = graph.source,
                    offline = graph.offline,
                    onImportLyrics = { track ->
                        lyricTargetId = track.id
                        importLyrics.launch(arrayOf("*/*"))
                    },
                    onOpenReleases = {
                        try {
                            startActivity(
                                Intent(
                                    Intent.ACTION_VIEW,
                                    Uri.parse(
                                        "https://github.com/NikiChaZi/Riffuna/releases/latest"
                                    ),
                                )
                            )
                        } catch (_: android.content.ActivityNotFoundException) {
                            graph.controller.notifyUser("Не удалось открыть страницу обновлений")
                        }
                    },
                )
            }
        }
    }

    override fun onSaveInstanceState(outState: Bundle) {
        outState.putString("lyric_target_id", lyricTargetId)
        super.onSaveInstanceState(outState)
    }

    override fun onStart() {
        super.onStart()
        startService(Intent(this, PlaybackService::class.java))
    }
}
