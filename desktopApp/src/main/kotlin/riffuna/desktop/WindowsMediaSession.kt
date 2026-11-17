package riffuna.desktop

import java.nio.file.Files
import java.nio.file.Path
import java.util.Base64
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch
import riffuna.core.ArtworkRequests
import riffuna.core.LocalController

internal fun windowsHelper(home: Path): Path = home.resolve("vendor/windows/RiffunaWindows.exe")

internal object WindowsMediaSession {
    suspend fun run(home: Path, data: Path, controller: LocalController) = coroutineScope {
        val helper = windowsHelper(home)
        if (!Files.isRegularFile(helper)) return@coroutineScope
        val process =
            runCatching {
                    ProcessBuilder(helper.toString(), "--media")
                        .redirectError(ProcessBuilder.Redirect.DISCARD)
                        .start()
                }
                .getOrNull() ?: return@coroutineScope
        val writer = process.outputStream.bufferedWriter(Charsets.UTF_8)
        val commands = Channel<String>(capacity = 16)
        // Closing the process unblocks the pipe on every exit path, including cancellation.
        Thread(
                {
                    try {
                        process.inputStream.bufferedReader(Charsets.UTF_8).useLines { lines ->
                            lines.forEach { commands.trySend(it) }
                        }
                    } finally {
                        commands.close()
                    }
                },
                "Riffuna Windows media commands",
            )
            .apply { isDaemon = true }
            .start()

        fun send(vararg fields: String) {
            synchronized(writer) {
                runCatching {
                        writer.write(fields.joinToString("\t"))
                        writer.newLine()
                        writer.flush()
                    }
                    .onFailure { commands.close() }
            }
        }

        val stateUpdates =
            launch(Dispatchers.IO) {
                controller.state
                    .map { state ->
                        val track = state.current
                        if (track == null) listOf("clear")
                        else {
                            val status =
                                when {
                                    state.playbackLoading -> "changing"
                                    state.playing -> "playing"
                                    else -> "paused"
                                }
                            listOf(
                                "state",
                                status,
                                (state.positionMs.coerceAtLeast(0) / 1000 * 1000).toString(),
                                state.durationMs.coerceAtLeast(track.duration * 1000L).toString(),
                                if (state.seekable) "1" else "0",
                            )
                        }
                    }
                    .distinctUntilChanged()
                    .collect { send(*it.toTypedArray()) }
            }
        val metadataUpdates =
            launch(Dispatchers.IO) {
                val store = ArtworkStore(data.resolve("artwork"))
                val fallback = home.resolve("assets/riffuna.png")
                controller.state
                    .map { it.current }
                    .distinctUntilChanged()
                    .collectLatest { track ->
                        if (track == null) return@collectLatest
                        val title = encode(track.title)
                        val artist = encode(track.artist)
                        send("metadata", title, artist, "")
                        val artwork =
                            ArtworkRequests.candidates(track.thumbnail, 256)
                                .take(3)
                                .firstNotNullOfOrNull { url ->
                                    runCatching { store.load(url) }.getOrNull()
                                } ?: runCatching { Files.readAllBytes(fallback) }.getOrNull()
                        if (artwork != null && controller.state.value.current == track)
                            send(
                                "metadata",
                                title,
                                artist,
                                Base64.getEncoder().encodeToString(artwork),
                            )
                    }
            }
        try {
            for (command in commands) {
                when (command.substringBefore('\t')) {
                    "play" -> controller.resumePlayback()
                    "pause" -> controller.pausePlayback()
                    "next" -> controller.next()
                    "previous" -> controller.previous()
                    "seek" ->
                        command.substringAfter('\t', "").toLongOrNull()?.let { position ->
                            if (controller.state.value.seekable) controller.seek(position)
                        }
                }
            }
        } finally {
            process.destroy()
            stateUpdates.cancel()
            metadataUpdates.cancel()
        }
    }

    private fun encode(value: String): String =
        Base64.getEncoder().encodeToString(value.take(4096).toByteArray(Charsets.UTF_8))
}
