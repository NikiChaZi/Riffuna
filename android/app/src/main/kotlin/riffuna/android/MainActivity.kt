package riffuna.android

import android.Manifest
import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts

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
    private val notifications =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) {}

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge(
            statusBarStyle = SystemBarStyle.dark(android.graphics.Color.TRANSPARENT),
            navigationBarStyle = SystemBarStyle.dark(android.graphics.Color.TRANSPARENT),
        )
        startService(Intent(this, PlaybackService::class.java))
        if (
            android.os.Build.VERSION.SDK_INT >= 33 &&
                !getPreferences(MODE_PRIVATE).getBoolean("notification_requested", false)
        ) {
            getPreferences(MODE_PRIVATE).edit().putBoolean("notification_requested", true).apply()
            notifications.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
        setContent {
            RiffunaTheme { MobileApp(graph.controller) { documents.launch(arrayOf("audio/*")) } }
        }
    }
}
