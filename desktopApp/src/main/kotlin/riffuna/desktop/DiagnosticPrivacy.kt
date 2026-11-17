package riffuna.desktop

import kotlinx.serialization.json.*

internal fun startupReport(version: String?, visible: Boolean): JsonObject = buildJsonObject {
    put("ui", "Compose Multiplatform")
    put("language", "Kotlin")
    put("audio_backend", "libmpv/JNA")
    put("source_provider", "YouTube.js")
    put("python_runtime", false)
    put("qt_runtime", false)
    put("app_version", version)
    put("remote_server", false)
    put("window_visible", visible)
}

private val tracePhases =
    setOf(
        "start",
        "player-version",
        "player-script",
        "player-api",
        "audio-range",
        "session-api",
        "range-bridge",
        "range-bridge-error",
        "audio-ready",
        "attested-format-error",
        "attested-client-error",
        "direct-client",
        "direct-client-error",
        "signed-client-error",
    )
private val traceTypes =
    setOf("Error", "TypeError", "AbortError", "TimeoutError", "PlayerError", "InnertubeError")
private val traceCauses =
    setOf(
        "ENOTFOUND",
        "EAI_AGAIN",
        "ECONNRESET",
        "ECONNREFUSED",
        "ETIMEDOUT",
        "UND_ERR_CONNECT_TIMEOUT",
        "UND_ERR_HEADERS_TIMEOUT",
        "UND_ERR_BODY_TIMEOUT",
        "UND_ERR_SOCKET",
    )
private val traceClients =
    setOf("YTMUSIC", "VISIONOS", "IOS", "ANDROID_VR", "WEB_EMBEDDED", "TV_SIMPLY", "WEB")

internal fun safeSourceTrace(raw: String): String? {
    if (raw.length > 2_048) return null
    val row = runCatching { Json.parseToJsonElement(raw) as? JsonObject }.getOrNull() ?: return null
    fun value(key: String) = row[key] as? JsonPrimitive
    val phase = value("phase")?.content?.takeIf { it in tracePhases } ?: return null
    return buildJsonObject {
            put("phase", phase)
            value("status")?.intOrNull?.takeIf { it in 100..599 }?.let { put("status", it) }
            value("formats")?.intOrNull?.takeIf { it in 0..1000 }?.let { put("formats", it) }
            value("type")?.content?.takeIf { it in traceTypes }?.let { put("type", it) }
            value("cause")?.content?.takeIf { it in traceCauses }?.let { put("cause", it) }
            value("client")?.content?.takeIf { it in traceClients }?.let { put("client", it) }
            for (key in
                listOf("proxy_configured", "proxy_endpoint", "main_youtube", "music_youtube")) {
                value(key)?.booleanOrNull?.let { put(key, it) }
            }
        }
        .toString()
}
