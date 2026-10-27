package riffuna.desktop

import com.sun.jna.Library
import com.sun.jna.Native
import com.sun.jna.Pointer
import com.sun.jna.StringArray
import com.sun.jna.Structure
import com.sun.jna.ptr.DoubleByReference
import com.sun.jna.ptr.IntByReference
import java.nio.file.Path
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.serialization.json.*
import riffuna.core.*

class MpvAudio(path: Path) : AudioEngine {
    @Structure.FieldOrder("eventId", "error", "reply", "data")
    class Event(pointer: Pointer) : Structure(pointer) {
        @JvmField var eventId = 0
        @JvmField var error = 0
        @JvmField var reply = 0L
        @JvmField var data: Pointer? = null

        init {
            read()
        }
    }

    private interface Api : Library {
        fun mpv_observe_property(ctx: Pointer, reply: Long, name: String, format: Int): Int

        fun mpv_wait_event(ctx: Pointer, timeout: Double): Pointer?

        fun mpv_create(): Pointer

        fun mpv_initialize(ctx: Pointer): Int

        fun mpv_set_option_string(ctx: Pointer, name: String, value: String): Int

        fun mpv_set_property_string(ctx: Pointer, name: String, value: String): Int

        fun mpv_get_property(ctx: Pointer, name: String, format: Int, value: Pointer): Int

        fun mpv_get_property_string(ctx: Pointer, name: String): Pointer?

        fun mpv_free(pointer: Pointer)

        fun mpv_command(ctx: Pointer, args: Pointer): Int

        fun mpv_terminate_destroy(ctx: Pointer)
    }

    private val api = Native.load(path.toAbsolutePath().toString(), Api::class.java)
    private val handle = api.mpv_create()
    private val mutable = MutableStateFlow(AudioState())
    override val state: StateFlow<AudioState> = mutable
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var closed = false
    private var loaded = false
    private var fileReady = false
    private var outputRevision = 0L

    init {
        mapOf(
                "config" to "no",
                "load-scripts" to "no",
                "ytdl" to "no",
                "terminal" to "no",
                "vo" to "null",
                "vid" to "no",
                "audio-display" to "no",
                "idle" to "yes",
                "keep-open" to "yes",
                "pause" to "yes",
                "volume" to "0",
                "gapless-audio" to "yes",
                "audio-samplerate" to "48000",
                "audio-format" to "float",
                "audio-channels" to "stereo",
                "audio-stream-silence" to "yes",
            )
            .forEach { (key, value) ->
                check(api.mpv_set_option_string(handle, key, value) >= 0) {
                    "Unsupported audio option: $key"
                }
            }
        check(api.mpv_initialize(handle) >= 0) { "Could not initialize libmpv" }
        api.mpv_observe_property(handle, 42L, "audio-device-list", 0)
        scope.launch {
            while (isActive) {
                delay(100)
                synchronized(this@MpvAudio) {
                    var failure = false
                    var outputChanged = false
                    if (!closed)
                        for (index in 0 until 32) {
                            val pointer = api.mpv_wait_event(handle, 0.0) ?: break
                            val event = Event(pointer)
                            if (event.eventId == 0) break
                            if (event.eventId == 22 && event.reply == 42L) {
                                outputRevision++
                                outputChanged = true
                            }
                            if (event.eventId == 8) fileReady = true
                            if (event.eventId == 7 && event.data?.getInt(0) == 4) failure = true
                        }
                    if (outputChanged && !loaded)
                        mutable.value = mutable.value.copy(outputRevision = outputRevision)
                    if (failure && loaded) {
                        loaded = false
                        fileReady = false
                        mutable.value =
                            AudioState(
                                error = "Не удалось открыть аудио. Повтори попытку.",
                                outputRevision = outputRevision,
                            )
                    }
                    if (!closed && loaded && !fileReady) {
                        mutable.value =
                            AudioState(buffering = true, outputRevision = outputRevision)
                    }
                    if (!closed && loaded && fileReady) {
                        val pos = number("time-pos")
                        val duration = number("duration")
                        mutable.value =
                            AudioState(
                                ((pos ?: 0.0) * 1000).toLong(),
                                ((duration ?: 0.0) * 1000).toLong(),
                                pos != null &&
                                    !flag("pause") &&
                                    !flag("paused-for-cache") &&
                                    !flag("eof-reached"),
                                flag("eof-reached"),
                                buffering = flag("paused-for-cache"),
                                seekable = flag("seekable"),
                                outputRevision = outputRevision,
                            )
                    }
                }
            }
        }
    }

    private fun command(vararg values: String) {
        check(api.mpv_command(handle, StringArray(values)) >= 0) { "Audio command failed" }
    }

    private fun property(name: String, value: String) {
        check(api.mpv_set_property_string(handle, name, value) >= 0) { "Audio setting unavailable" }
    }

    private fun number(name: String): Double? {
        val result = DoubleByReference()
        return if (api.mpv_get_property(handle, name, 5, result.pointer) >= 0) result.value
        else null
    }

    private fun flag(name: String): Boolean {
        val result = IntByReference()
        return api.mpv_get_property(handle, name, 3, result.pointer) >= 0 && result.value != 0
    }

    override suspend fun open(source: AudioSource) =
        synchronized(this) {
            check(!closed)
            loaded = false
            fileReady = false
            property("pause", "yes")
            for (index in 0 until 128) {
                val pointer = api.mpv_wait_event(handle, 0.0) ?: break
                if (Event(pointer).eventId == 0) break
            }
            property(
                "http-header-fields",
                source.headers.entries.joinToString(",") {
                    it.key + ": " + it.value.replace("\r", "").replace("\n", "")
                },
            )
            property("http-proxy", source.proxy)
            command("loadfile", source.uri, "replace")
            property("pause", if (source.autoPlay) "no" else "yes")
            loaded = true
            mutable.value = AudioState(outputRevision = outputRevision)
        }

    @Synchronized
    override fun toggle() {
        if (!closed && loaded) property("pause", if (flag("pause")) "no" else "yes")
    }

    @Synchronized
    override fun resume() {
        if (!closed && loaded) property("pause", "no")
    }

    @Synchronized
    override fun pause() {
        if (!closed) property("pause", "yes")
    }

    @Synchronized
    override fun seek(positionMs: Long) {
        if (!closed && loaded)
            command("seek", (positionMs.coerceAtLeast(0) / 1000.0).toString(), "absolute+exact")
    }

    @Synchronized
    override fun setVolume(volume: Float) {
        if (!closed) property("volume", (volume.coerceIn(0f, 1f) * 100).toString())
    }

    @Synchronized
    override fun devices(): List<AudioDevice> {
        if (closed) return emptyList()
        val pointer = api.mpv_get_property_string(handle, "audio-device-list") ?: return emptyList()
        return try {
            Json.parseToJsonElement(pointer.getString(0, "UTF-8")).jsonArray.map { row ->
                val item = row.jsonObject
                AudioDevice(
                    item["name"]!!.jsonPrimitive.content,
                    item["description"]!!.jsonPrimitive.content,
                )
            }
        } finally {
            api.mpv_free(pointer)
        }
    }

    @Synchronized
    override fun selectDevice(id: String) {
        require(devices().any { it.id == id })
        property("audio-device", id)
        val description = devices().firstOrNull { it.id == id }?.name.orEmpty()
        property(
            "audio-stream-silence",
            if (id == "auto" || description.contains("buds3 fe", true)) "yes" else "no",
        )
    }

    @Synchronized
    override fun close() {
        if (closed) return
        closed = true
        scope.cancel()
        api.mpv_terminate_destroy(handle)
    }
}
