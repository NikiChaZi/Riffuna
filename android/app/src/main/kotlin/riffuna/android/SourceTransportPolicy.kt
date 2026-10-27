package riffuna.android

import java.net.URI

internal object SourceTransportPolicy {
    fun allowed(raw: String, audioOnly: Boolean = false): Boolean =
        runCatching {
                val uri = URI(raw)
                val host = uri.host?.lowercase(java.util.Locale.ROOT) ?: return false
                if (uri.scheme != "https" || uri.userInfo != null || uri.port !in listOf(-1, 443))
                    return false
                val audio = host.endsWith(".googlevideo.com") && uri.path == "/videoplayback"
                audio ||
                    (!audioOnly &&
                        host in
                            setOf(
                                "www.youtube.com",
                                "music.youtube.com",
                                "youtubei.googleapis.com",
                                "jnn-pa.googleapis.com",
                            ))
            }
            .getOrDefault(false)
}
