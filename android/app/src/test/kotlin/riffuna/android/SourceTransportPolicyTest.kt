package riffuna.android

import kotlin.test.*

class SourceTransportPolicyTest {
    @Test
    fun publicYoutubeAndAudioAreAllowed() {
        assertTrue(
            SourceTransportPolicy.allowed("https://youtubei.googleapis.com/youtubei/v1/search")
        )
        assertTrue(
            SourceTransportPolicy.allowed(
                "https://rr1---sn.example.googlevideo.com/videoplayback?itag=140",
                true,
            )
        )
    }

    @Test
    fun bridgeCannotReadFilesLocalhostOrUnrelatedSites() {
        listOf(
                "file:///data/data/app.riffuna.android/library.sqlite3",
                "http://127.0.0.1/",
                "https://youtube.com.evil.example/",
                "https://googlevideo.com.evil.example/videoplayback",
                "https://evil.example/",
            )
            .forEach { assertFalse(SourceTransportPolicy.allowed(it)) }
    }

    @Test
    fun credentialsPortsAndNonAudioEndpointsAreRejected() {
        assertFalse(SourceTransportPolicy.allowed("https://user@www.youtube.com/"))
        assertFalse(SourceTransportPolicy.allowed("https://www.youtube.com:8080/"))
        assertFalse(SourceTransportPolicy.allowed("https://www.youtube.com/watch?v=abc", true))
        assertFalse(SourceTransportPolicy.allowed("https://rr1.googlevideo.com/other", true))
    }
}
