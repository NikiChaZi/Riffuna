package riffuna.desktop

import com.sun.jna.*
import java.nio.file.Path
import java.util.concurrent.TimeUnit

/** A separate disabled-output MPV handle reads tags without touching the active player. */
internal class MpvMetadataReader(path: Path) {
    private interface Api : Library {
        fun mpv_create(): Pointer

        fun mpv_initialize(handle: Pointer): Int

        fun mpv_set_option_string(handle: Pointer, name: String, value: String): Int

        fun mpv_command(handle: Pointer, args: Pointer): Int

        fun mpv_wait_event(handle: Pointer, timeout: Double): Pointer?

        fun mpv_get_property_string(handle: Pointer, name: String): Pointer?

        fun mpv_free(value: Pointer)

        fun mpv_terminate_destroy(handle: Pointer)
    }

    private val api = Native.load(path.toAbsolutePath().toString(), Api::class.java)

    fun read(path: Path): LocalMetadata {
        val handle = api.mpv_create()
        try {
            mapOf(
                    "config" to "no",
                    "load-scripts" to "no",
                    "ytdl" to "no",
                    "terminal" to "no",
                    "vo" to "null",
                    "ao" to "null",
                    "aid" to "auto",
                    "vid" to "no",
                    "pause" to "yes",
                    "idle" to "yes",
                )
                .forEach { (name, value) ->
                    check(api.mpv_set_option_string(handle, name, value) >= 0)
                }
            check(api.mpv_initialize(handle) >= 0)
            check(
                api.mpv_command(
                    handle,
                    StringArray(arrayOf("loadfile", path.toString()), "UTF-8"),
                ) >= 0
            )
            val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(3)
            var loaded = false
            while (System.nanoTime() < deadline && !loaded) {
                val event = api.mpv_wait_event(handle, .05)?.let { MpvAudio.Event(it) } ?: continue
                when (event.eventId) {
                    8 -> loaded = true
                    7 -> error("Не удалось прочитать аудиофайл")
                }
            }
            check(loaded) { "Не удалось прочитать метаданные аудио" }
            fun property(name: String): String? {
                val pointer = api.mpv_get_property_string(handle, name) ?: return null
                return try {
                    pointer.getString(0, "UTF-8")
                } finally {
                    api.mpv_free(pointer)
                }
            }
            val filename = path.fileName.toString().substringBeforeLast('.')
            val pieces = filename.split(" - ", limit = 2)
            val artist =
                property("metadata/by-key/artist")?.takeIf { it.isNotBlank() }
                    ?: if (pieces.size == 2) pieces.first() else "Неизвестный исполнитель"
            val title =
                property("metadata/by-key/title")?.takeIf { it.isNotBlank() } ?: pieces.last()
            return LocalMetadata(
                title,
                artist,
                property("duration")?.toDoubleOrNull()?.toInt() ?: 0,
            )
        } finally {
            api.mpv_terminate_destroy(handle)
        }
    }
}
