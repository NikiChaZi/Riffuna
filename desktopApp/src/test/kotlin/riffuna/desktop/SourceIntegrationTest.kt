package riffuna.desktop

import kotlin.test.*
import kotlinx.coroutines.*
import kotlinx.serialization.json.*
import java.nio.file.Files
import java.nio.file.Path

/** Opt-in integration check: reaches YouTube and real libmpv, with volume zero. */
class SourceIntegrationTest {
    @Test fun packagedSourceSearchesRussianAndPlaysAudio()=runBlocking {
        org.junit.Assume.assumeTrue(System.getenv("RIFFUNA_LIVE_TEST")=="1")
        val home=Path.of(System.getProperty("user.dir")).parent.resolve("build/desktop-resources/common")
        val data=Files.createTempDirectory("riffuna-source-smoke")
        val source=DesktopSource(home,data)
        val audio=MpvAudio(home.resolve("vendor/libmpv/libmpv-2.dll"))
        try {
            val capability=source.request(buildJsonObject{put("action","capabilities")})
            assertEquals(false,capability["qt_loaded"]!!.jsonPrimitive.boolean)
            assertEquals(false,capability["python"]!!.jsonPrimitive.boolean)
            println("LIVE_PROXY configured=${DesktopNetwork.proxyUrl().isNotBlank()}")
            val started=System.nanoTime()
            val tracks=withTimeout(120000){source.search("Дора Понарошку",10)}
            assertTrue(tracks.isNotEmpty(),"Live Russian music search returned no tracks")
            assertTrue(tracks.any{it.artist.contains("Дора",true)||it.title.contains("Понарошку",true)})
            val track=tracks.first()
            println("LIVE_SEARCH_OK results=${tracks.size} duration=${track.duration} elapsed_ms=${(System.nanoTime()-started)/1_000_000}")
            println("LIVE_PROXY_BEFORE_AUDIO configured=${DesktopNetwork.proxyUrl().isNotBlank()}")
            val stream=withTimeout(120000){source.resolve(track)}
            assertTrue(stream.uri.startsWith("http://127.0.0.1:")||stream.uri.startsWith("file:"))
            println("LIVE_RESOLVE_OK elapsed_ms=${(System.nanoTime()-started)/1_000_000}")
            audio.setVolume(0f);audio.open(stream)
            withTimeout(40000){while(audio.state.value.positionMs<500)delay(100)}
            println("LIVE_PLAY_STATE ${audio.state.value}")
            audio.pause();delay(200)
            audio.seek(20000)
            try{withTimeout(10000){while(audio.state.value.positionMs<19500)delay(100)}}finally{println("LIVE_SEEK_STATE ${audio.state.value}")}
            assertFalse(audio.state.value.playing)
            audio.resume()
            withTimeout(10000){while(audio.state.value.positionMs<20500)delay(100)}
            assertTrue(audio.state.value.playing)
            println("LIVE_SOURCE_OK results=${tracks.size} track=${track.title} elapsed_seconds=${(System.nanoTime()-started)/1_000_000_000}")
        }finally {audio.close();source.close()}
    }
}
