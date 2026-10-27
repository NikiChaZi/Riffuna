package riffuna.desktop
import kotlin.test.*
import kotlinx.serialization.json.*
import riffuna.core.*
import java.nio.file.Files
class MusicRulesTest {
    @Test fun musicSearchRejectsJunkButKeepsMusicalVersionsAndOst() {
        fun row(title:String,type:String="MUSIC_VIDEO_TYPE_ATV",live:Boolean=false)=buildJsonObject{put("id","aaaaaaaaaaa");put("title",title);put("artist","Дора");put("duration",147);put("musicType",type);put("live",live)}
        assertNotNull(MusicRules.catalog(row("Понарошку"),"дора"))
        listOf("Понарошку Live","Понарошку (Премьера клипа)","Понарошку Разбор трека","Понарошку 1 час","Понарошку Мультфильм").forEach{assertNull(MusicRules.catalog(row(it),"дора"),it)}
        listOf("Понарошку (Slowed)","Понарошку (Mashup)","Понарошку (Sped Up)","Rules of Nature Extended").forEach{assertNotNull(MusicRules.catalog(row(it),""),it)}
        assertNull(MusicRules.catalog(row("Понарошку","MUSIC_VIDEO_TYPE_OMV"),"дора"));assertNull(MusicRules.catalog(row("Понарошку",live=true),"дора"))
        assertTrue(MusicRules.score("rule of nature","Rules of Nature Extended","Crimson")>0)
        assertTrue(MusicRules.score("rule of nature","The Sounds of Water and Nature Rule","Water Sounds")<0)
    }
    @Test fun alternativesRequireSameWorkAndRespectProcessing() {
        val original=Track("aaaaaaaaaaa","Город под дождём","Слава КПСС",203)
        assertTrue(MusicRules.versionMatches(original,Track("bbbbbbbbbbb","Слава КПСС — Город под дождём (uncensored)","Archive",204)))
        assertFalse(MusicRules.versionMatches(original,Track("bbbbbbbbbbb","Слава КПСС — Другой трек","Archive",204)))
        assertFalse(MusicRules.versionMatches(original,Track("bbbbbbbbbbb","Слава КПСС — Город под дождём LIVE","Archive",204)))
        assertEquals(listOf("ULTRA SLOWED"),MusicRules.profile("Song (Ultra Slowed)"))
    }
}
class LyricsRepositoryTest {
    @Test fun enhancedLrcTtmlAndEstimatesAreBounded() {
        val rows=LyricTiming.parseLrc("[offset:200]\n[00:10.00]<00:10.00>Hello <00:10.50>world\n[00:13.000]Next line")
        assertEquals(9800,rows.first().startMs);assertEquals(2,rows.first().words.size)
        val ttml="""<tt xmlns="http://www.w3.org/ns/ttml"><body><div><p begin="1s" end="3s"><span begin="1s" end="2s">Hello </span><span begin="2s" end="3s">world</span></p></div></body></tt>"""
        val parsed=LyricsRepository.parseTtml(ttml);assertEquals(2,parsed.single().words.size);assertEquals("Hello world",parsed.single().text)
        assertFails{LyricsRepository.parseTtml("<!DOCTYPE a [<!ENTITY x SYSTEM 'file:///x'>]><tt/>")}
        val estimate=LyricTiming.estimatedWords("A few words",1000,5000);assertTrue(estimate.all{it.startMs>=1000&&it.endMs<=5000&&it.endMs>it.startMs})
    }
    @Test fun mismatchedEditionOrDurationCannotGetWrongClock() {
        val repo=LyricsRepository(Files.createTempDirectory("riffuna-lyrics-test"));val track=Track("aaaaaaaaaaa","Понарошку","Дора",147)
        fun row(duration:Int,title:String="Понарошку")=buildJsonObject{put("trackName",title);put("artistName","Dora");put("duration",duration);put("plainLyrics","Привет мир");put("syncedLyrics","[00:10]Привет\n[02:10]мир")}
        assertEquals("synced",repo.match(track,track.title,track.artist,listOf(row(147)))?.state)
        assertEquals("plain",repo.match(track,track.title,track.artist,listOf(row(135)))?.state)
        assertNull(repo.match(track,track.title,track.artist,listOf(row(147,"Понарошку (Slowed)"))))
        val local=repo.import(track,"[00:10]<00:10>Привет <00:11>мир","lrc");assertFalse(local.approximateWords)
        assertEquals(local,repo.load(track))
    }
}
