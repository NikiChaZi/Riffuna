package riffuna.core

/** Size-aware CDN requests also upgrade thumbnail URLs saved by older versions. */
object ArtworkRequests {
    fun candidates(url: String, requestedPixels: Int): List<String> {
        if (url.isBlank()) return emptyList()
        val match =
            Regex("^https://([^/?#]+)(/[^?#]*)(?:[?#].*)?$").matchEntire(url) ?: return listOf(url)
        val host = match.groupValues[1].lowercase()
        val path = match.groupValues[2]
        val pixels = listOf(128, 256, 512, 1024).firstOrNull { it >= requestedPixels } ?: 1024
        if (host.endsWith(".googleusercontent.com") || host.endsWith(".ggpht.com")) {
            val sized = Regex("=(?:w\\d+-h\\d+|s\\d+)(?=-|$)").replace(path, "=w$pixels-h$pixels")
            return listOf("https://$host$sized" + url.substringAfter(path, ""), url).distinct()
        }
        if (host.endsWith(".ytimg.com")) {
            val video =
                Regex(
                        "/(vi|vi_webp)/([A-Za-z0-9_-]{11})/(?:default|mqdefault|hqdefault|sddefault|maxresdefault|hq720)\\.(jpg|webp)"
                    )
                    .matchEntire(path) ?: return listOf(url)
            val base = "https://$host/${video.groupValues[1]}/${video.groupValues[2]}/"
            val extension = video.groupValues[3]
            val versions =
                if (pixels > 256) listOf("maxresdefault", "sddefault", "hqdefault")
                else listOf("hqdefault")
            return (versions.map { "$base$it.$extension" } + url).distinct()
        }
        return listOf(url)
    }

    /**
     * Missing YouTube high-resolution covers sometimes return a 120x90 placeholder with HTTP 200.
     */
    fun isPlaceholder(url: String, width: Int, height: Int): Boolean =
        Regex("^https://[^/]+\\.ytimg\\.com/(?:vi|vi_webp)/[^/]+/(?:maxresdefault|sddefault)\\.")
            .containsMatchIn(url) && (width < 320 || height < 180)
}
