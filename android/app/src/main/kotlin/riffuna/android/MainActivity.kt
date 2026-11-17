package riffuna.android

import android.Manifest
import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import riffuna.catalog.readRiffunaCollection

class MainActivity : ComponentActivity() {
    private val graph
        get() = (application as RiffunaApplication).graph

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

    private val notifications =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) {}

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
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
                )
            }
        }
    }

    override fun onStart() {
        super.onStart()
        startService(Intent(this, PlaybackService::class.java))
    }
}
