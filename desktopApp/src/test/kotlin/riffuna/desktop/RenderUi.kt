@file:OptIn(androidx.compose.ui.ExperimentalComposeUiApi::class)

package riffuna.desktop

import androidx.compose.ui.ImageComposeScene
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.LayoutDirection
import java.lang.reflect.Proxy
import java.nio.file.*
import javax.swing.SwingUtilities
import kotlin.system.exitProcess
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.swing.Swing
import org.jetbrains.skia.EncodedImageFormat
import riffuna.core.*
import riffuna.desktop.ui.RiffunaApp

/** Renders our own Compose content offscreen; never opens or operates desktop windows. */
fun main() {
    System.setProperty("java.awt.headless", "true")
    val root = Path.of(System.getProperty("riffuna.project"))
    val output = root.resolve(".test-data/ui-render")
    Files.createDirectories(output)
    val library = SqliteLibrary(root.resolve(".test-data/full-ui-smoke/library.sqlite3"))
    try {
        val likes = library.likes()
        val history = library.history()
        val queue = library.queue()
        val current = library.current() ?: likes.firstOrNull()
        val lyrics =
            current?.let {
                LyricsRepository(root.resolve(".test-data/full-ui-smoke/lyrics")).load(it)
            } ?: LyricsPacket()
        val base =
            AppState(
                libraryState =
                    LibraryUiState(
                        likes = likes,
                        history = history,
                        playlists = library.playlists(),
                    ),
                queueState = QueueUiState(queue = queue.first, queueIndex = queue.second),
                playback =
                    PlaybackUiState(
                        current = current,
                        durationMs = (current?.duration ?: 0) * 1000L,
                        volume = .5f,
                        seekable = true,
                    ),
                lyricsState = LyricsUiState(lyrics = lyrics.lines, lyricsPacket = lyrics),
                navigationState = NavigationUiState(reducedMotion = true),
            )
        val scenes =
            listOf(
                "home" to base,
                "likes" to
                    base.copy(
                        navigationState = base.navigationState.copy(view = LibraryView.LIKES),
                        libraryState = base.libraryState.copy(visibleTracks = likes),
                    ),
                "search" to
                    base.copy(
                        navigationState = base.navigationState.copy(view = LibraryView.SEARCH),
                        searchState = base.searchState.copy(query = "Дора"),
                        libraryState =
                            base.libraryState.copy(
                                visibleTracks = likes.filter { it.artist.contains("Дора", true) }
                            ),
                    ),
                "playlists" to
                    base.copy(
                        navigationState = base.navigationState.copy(view = LibraryView.PLAYLISTS)
                    ),
                "expanded" to
                    base.copy(playback = base.playback.copy(expanded = true, positionMs = 65000)),
                "lyrics-focus" to
                    base.copy(
                        playback =
                            base.playback.copy(
                                expanded = true,
                                lyricsFocus = true,
                                positionMs = 65000,
                            )
                    ),
                "playback-error" to
                    base.copy(
                        navigationState = base.navigationState.copy(view = LibraryView.LIKES),
                        libraryState = base.libraryState.copy(visibleTracks = likes),
                        playback =
                            base.playback.copy(
                                playbackError = "Запись недоступна. Повтори попытку."
                            ),
                    ),
                "compact-queue" to
                    base.copy(
                        navigationState = base.navigationState.copy(view = LibraryView.LIKES),
                        libraryState = base.libraryState.copy(visibleTracks = likes),
                    ),
                "compact" to
                    base.copy(
                        navigationState = base.navigationState.copy(view = LibraryView.LIKES),
                        libraryState = base.libraryState.copy(visibleTracks = likes),
                        queueState = base.queueState.copy(queueVisible = false),
                    ),
            )
        for ((name, state) in scenes) {
            val flow = MutableStateFlow(state)
            val controller =
                Proxy.newProxyInstance(
                    RiffunaController::class.java.classLoader,
                    arrayOf(RiffunaController::class.java),
                ) { _, method, _ ->
                    if (method.name == "getState") flow else null
                } as RiffunaController
            lateinit var scene: ImageComposeScene
            SwingUtilities.invokeAndWait {
                scene =
                    ImageComposeScene(
                        if (name.startsWith("compact")) 1000 else 1280,
                        if (name.startsWith("compact")) 650 else 800,
                        Density(1f),
                        LayoutDirection.Ltr,
                        Dispatchers.Swing,
                    ) {
                        RiffunaApp(controller, {}, {})
                    }
            }
            try {
                repeat(60) {
                    SwingUtilities.invokeAndWait { scene.render(System.nanoTime()).close() }
                    Thread.sleep(35)
                }
                SwingUtilities.invokeAndWait {
                    val image = scene.render(System.nanoTime())
                    try {
                        val bytes = image.encodeToData(EncodedImageFormat.PNG)!!.bytes
                        Files.write(output.resolve("$name.png"), bytes)
                    } finally {
                        image.close()
                    }
                }
                println("UI_RENDER_OK $name")
            } finally {
                SwingUtilities.invokeAndWait { scene.close() }
            }
        }
        Files.writeString(
            output.resolve("README.txt"),
            "Offscreen QA renders of the actual Compose UI. Library copied from the user database. Position 65000 ms is a visual fixture, not a playback measurement. No user desktop input or windows.",
        )
    } finally {
        library.close()
    }
    exitProcess(0)
}
