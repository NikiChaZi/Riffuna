package riffuna.desktop

import kotlinx.coroutines.*
import kotlinx.serialization.json.*
import riffuna.core.Track
import java.nio.file.*
import javax.imageio.ImageIO

/** Offline package verification, using a private temporary library and no windows. */
object Diagnostics {
    fun run(home:Path,report:Path,live:Boolean=false):Int=runBlocking {
        val data=Files.createTempDirectory("riffuna-package-check")
        val result=buildJsonObject {
            put("app_version","0.2.0");put("headless",true);put("test_library",true);put("live_network_requested",live)
            try {
                val library=SqliteLibrary(data.resolve("library.sqlite3"))
                try {
                    val track=Track("aaaaaaaaaaa","Diagnostic track","Diagnostic artist",180)
                    library.like(track,true);library.saveQueue(listOf(track),0,track)
                    val playlist=library.createPlaylist("Diagnostic playlist");library.addToPlaylist(playlist,listOf(track))
                    check(library.likes().single()==track&&library.queue().first.single()==track&&library.playlistTracks(playlist).single()==track)
                    put("database_roundtrip",true)
                }finally{library.close()}
                val audio=MpvAudio(home.resolve("vendor/libmpv/libmpv-2.dll"))
                try{put("audio_devices",audio.devices().size);put("audio_backend","libmpv/JNA")}finally{audio.close()}
                val source=DesktopSource(home,data)
                try {
                    val capability=source.request(buildJsonObject{put("action","capabilities")})
                    check(capability["python"]?.jsonPrimitive?.booleanOrNull==false&&capability["qt_loaded"]?.jsonPrimitive?.booleanOrNull==false)
                    put("source_provider",capability["provider"]!!.jsonPrimitive.content)
                    put("python_runtime",false);put("qt_runtime",false);source.verifyTransport();put("audio_range_bridge",true)
                    if(live){
                        val started=System.nanoTime()
                        put("live_stage","search")
                        val tracks=withTimeout(90000){source.search("Дора Понарошку",10)};check(tracks.isNotEmpty());put("live_search_results",tracks.size)
                        put("live_stage","resolve")
                        val stream=withTimeout(90000){source.resolve(tracks.first())};put("live_resolve_ms",(System.nanoTime()-started)/1_000_000)
                        val player=MpvAudio(home.resolve("vendor/libmpv/libmpv-2.dll"))
                        try{
                            put("live_stage","playback");player.setVolume(0f);player.open(stream)
                            withTimeout(40000){while(player.state.value.positionMs<500&&player.state.value.error==null)delay(100)};check(player.state.value.error==null);put("live_audio_started",true)
                            put("live_stage","seek");player.pause();delay(200);player.seek(20000)
                            withTimeout(12000){while(player.state.value.positionMs<19500&&player.state.value.error==null)delay(100)};check(player.state.value.error==null&&!player.state.value.playing);put("live_paused_seek",true)
                            put("live_stage","resume");player.resume();withTimeout(10000){while(player.state.value.positionMs<20500&&player.state.value.error==null)delay(100)};check(player.state.value.playing);put("live_resume",true);put("live_stage","complete")
                        }catch(error:Throwable){val current=player.state.value;put("live_position_ms",current.positionMs);put("live_duration_ms",current.durationMs);put("live_buffering",current.buffering);put("live_playing",current.playing);put("live_ended",current.ended);throw error}finally{player.close()}
                    }
                }finally{source.close()}
                val directory=home.resolve("music-model")
                val seeds=Json.parseToJsonElement(Files.readString(directory.resolve("catalog.json"))).jsonArray.take(3).map{value->val item=value.jsonObject;Track(item["id"]!!.jsonPrimitive.content,item["title"]!!.jsonPrimitive.content,item["artist"]!!.jsonPrimitive.content)}
                MusicModel(directory).use{model->val recommendations=model.recommend(seeds,emptyList());check(recommendations.isNotEmpty());put("onnx_recommendations",recommendations.size)}
                check(ImageIO.read(home.resolve("assets/riffuna.png").toFile())!=null);put("icon",true)
                org.jetbrains.skia.Surface.makeRasterN32Premul(24,24).use{surface->surface.canvas.clear(0xFF101214.toInt());surface.makeImageSnapshot().use{image->image.encodeToData(org.jetbrains.skia.EncodedImageFormat.PNG).use{data->check(data!=null&&data.bytes.isNotEmpty())}}};put("ui_renderer","Skia");put("ui_render",true)
                put("status","ok")
            }catch(error:Throwable){put("status","failed");put("error_type",error.javaClass.simpleName)}
        }
        val output=report.toAbsolutePath();Files.createDirectories(output.parent);Files.writeString(output,result.toString())
        if(result["status"]?.jsonPrimitive?.content=="ok")0 else 1
    }
}
