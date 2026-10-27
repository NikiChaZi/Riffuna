package riffuna.desktop

import kotlin.test.*
import kotlinx.serialization.json.*
import java.net.*
import java.nio.file.Files
import java.util.concurrent.Executors
import com.sun.net.httpserver.HttpServer
import riffuna.core.AudioSource

class AudioTransportTest {
    @Test fun parsesInclusiveSuffixAndInvalidRanges() {
        assertEquals(10L to 99L,AudioTransport.byteRange("bytes=10-",100))
        assertEquals(90L to 99L,AudioTransport.byteRange("bytes=-10",100))
        assertEquals(0L to 99L,AudioTransport.byteRange("bytes=0-999",100))
        assertNull(AudioTransport.byteRange("bytes=-0",100));assertNull(AudioTransport.byteRange("bytes=1-2,3-4",100))
        assertNull(AudioTransport.byteRange("bytes=9999999999999999999999999-",100))
    }
    @Test fun rangeAndWholeResponsesAreCachedAndCanSeek() {
        for(honorRange in listOf(true,false)) {
            val data=ByteArray(600000){(it%251).toByte()};val connections=java.util.concurrent.ConcurrentHashMap.newKeySet<Int>()
            val executor=Executors.newCachedThreadPool()
            val upstream=HttpServer.create(InetSocketAddress("127.0.0.1",0),0).apply {this.executor=executor}
            upstream.createContext("/audio"){exchange->
                connections.add(exchange.remoteAddress.port)
                val range=if(honorRange)AudioTransport.byteRange(exchange.requestHeaders.getFirst("Range"),data.size.toLong()) else null
                val (start,end)=range?:Pair(0L,data.lastIndex.toLong())
                exchange.responseHeaders.set("Content-Type","audio/mp4")
                if(range!=null)exchange.responseHeaders.set("Content-Range","bytes $start-$end/${data.size}")
                exchange.sendResponseHeaders(if(range==null)200 else 206,end-start+1)
                try{exchange.responseBody.use{it.write(data,start.toInt(),(end-start+1).toInt())}}finally{exchange.close()}
            }
            upstream.start()
            val directory=Files.createTempDirectory("riffuna-cache-test")
            AudioTransport(directory).use {transport->
                try {
                    val stream=transport.bind("test-id",AudioSource("http://127.0.0.1:${upstream.address.port}/audio"))
                    val request=URI(stream.uri).toURL().openConnection(Proxy.NO_PROXY) as HttpURLConnection
                    request.readTimeout=5000;request.setRequestProperty("Range","bytes=250123-490123")
                    assertEquals(206,request.responseCode)
                    assertContentEquals(data.copyOfRange(250123,490124),request.inputStream.use{it.readAllBytes()});request.disconnect()
                    val deadline=System.nanoTime()+5_000_000_000
                    var cached=transport.cached("test-id")
                    while(cached==null&&System.nanoTime()<deadline){Thread.sleep(20);cached=transport.cached("test-id")}
                    assertNotNull(cached);assertContentEquals(data,Files.readAllBytes(cached));assertTrue(connections.size<=3,"Audio chunks should reuse HTTP connections")
                    Files.write(cached,byteArrayOf(1,2,3));assertNull(transport.cached("test-id"))
                    val unknown=URI(stream.uri.substringBeforeLast('/')+"/wrong-token").toURL().openConnection(Proxy.NO_PROXY) as HttpURLConnection
                    assertEquals(404,unknown.responseCode);unknown.disconnect()
                }finally{upstream.stop(0);executor.shutdownNow()}
            }
        }
    }
    @Test fun activeTrackSurvivesRepeatedPrefetchAndCanBeInvalidatedForRetry() {
        val payload=ByteArray(4096){(it%127).toByte()};val upstream=HttpServer.create(InetSocketAddress("127.0.0.1",0),0)
        upstream.createContext("/audio"){exchange->exchange.responseHeaders.set("Content-Type","audio/mp4");exchange.sendResponseHeaders(200,payload.size.toLong());try{exchange.responseBody.use{it.write(payload)}}finally{exchange.close()}}
        upstream.start()
        try{AudioTransport(Files.createTempDirectory("riffuna-active-buffer")).use{transport->
            val source=AudioSource("http://127.0.0.1:${upstream.address.port}/audio")
            val active=transport.bind("current",source)
            repeat(5){transport.bind("prepared-$it",source,current=false)}
            fun request():HttpURLConnection=(URI(active.uri).toURL().openConnection(Proxy.NO_PROXY) as HttpURLConnection).apply{readTimeout=3000}
            val live=request();assertEquals(200,live.responseCode);assertContentEquals(payload,live.inputStream.use{it.readAllBytes()});live.disconnect()
            transport.invalidate("current");val invalid=request();assertEquals(404,invalid.responseCode);invalid.disconnect()
        }}finally{upstream.stop(0)}
    }

    @Test fun completeAudioLargerThanTheMemoryWindowIsKeptOnDisk() {
        val length=24L*1024*1024+17;val upstream=HttpServer.create(InetSocketAddress("127.0.0.1",0),0)
        upstream.createContext("/large"){exchange->
            val (start,end)=AudioTransport.byteRange(exchange.requestHeaders.getFirst("Range"),length)?:Pair(0L,length-1)
            exchange.responseHeaders.set("Content-Type","audio/mp4");exchange.responseHeaders.set("Content-Range","bytes $start-$end/$length")
            exchange.sendResponseHeaders(206,end-start+1)
            try{exchange.responseBody.use{out->var position=start;while(position<=end){val count=minOf(8192L,end-position+1).toInt();out.write(ByteArray(count){((position+it)%127).toByte()});position+=count}}}finally{exchange.close()}
        }
        upstream.start();val directory=Files.createTempDirectory("riffuna-large-cache")
        try{AudioTransport(directory).use{transport->
            transport.bind("large",AudioSource("http://127.0.0.1:${upstream.address.port}/large"))
            val deadline=System.nanoTime()+25_000_000_000;var cached=transport.cached("large")
            while(cached==null&&System.nanoTime()<deadline){Thread.sleep(25);cached=transport.cached("large")}
            assertNotNull(cached);assertEquals(length,Files.size(cached))
            Files.newInputStream(cached).use{input->assertEquals(0,input.read());input.skipNBytes(length-2);assertEquals(((length-1)%127).toInt(),input.read())}
        }}finally{upstream.stop(0)}
        AudioTransport(directory).use{assertNotNull(it.cached("large"))}
    }

    @Test fun oversizedWholeResponseIsRejectedBeforeCaching() {
        val upstream=HttpServer.create(InetSocketAddress("127.0.0.1",0),0)
        upstream.createContext("/oversized"){exchange->runCatching{exchange.sendResponseHeaders(200,24L*1024*1024+1);exchange.responseBody.close()};exchange.close()};upstream.start()
        try{AudioTransport(Files.createTempDirectory("riffuna-audio-size-limit")).use{transport->
            val stream=transport.bind("oversized",AudioSource("http://127.0.0.1:${upstream.address.port}/oversized"))
            val connection=URI(stream.uri).toURL().openConnection(Proxy.NO_PROXY) as HttpURLConnection
            connection.readTimeout=5000;assertEquals(502,connection.responseCode);connection.disconnect();assertNull(transport.cached("oversized"))
        }}finally{upstream.stop(0)}
    }

    @Test fun rangeBridgeKeepsHttpsAndProxyHandlingOutsideTheJvm() {
        val payload=ByteArray(400000){(it%123).toByte()};val seen=java.util.concurrent.ConcurrentLinkedQueue<JsonObject>()
        val bridge=HttpServer.create(InetSocketAddress("127.0.0.1",0),0);val path="/12345678-1234-1234-1234-123456789abc"
        bridge.createContext(path){exchange->
            val input=Json.parseToJsonElement(String(exchange.requestBody.readAllBytes())).jsonObject;seen.add(input)
            val (start,end)=AudioTransport.byteRange(input["range"]!!.jsonPrimitive.content,payload.size.toLong())!!
            exchange.responseHeaders.set("Content-Type","audio/mp4");exchange.responseHeaders.set("Content-Range","bytes $start-$end/${payload.size}");exchange.sendResponseHeaders(206,end-start+1)
            try{exchange.responseBody.use{it.write(payload,start.toInt(),(end-start+1).toInt())}}finally{exchange.close()}
        };bridge.start()
        try{AudioTransport(Files.createTempDirectory("riffuna-range-bridge")).use{transport->
            transport.useRangeBridge("http://127.0.0.1:${bridge.address.port}$path")
            val source=AudioSource("https://fixture.googlevideo.com/audio",mapOf("User-Agent" to "Fixture"),"http://127.0.0.1:9")
            val local=transport.bind("bridged",source)
            val request=URI(local.uri).toURL().openConnection(Proxy.NO_PROXY) as HttpURLConnection;request.readTimeout=5000;request.setRequestProperty("Range","bytes=123-200123")
            assertEquals(206,request.responseCode);assertContentEquals(payload.copyOfRange(123,200124),request.inputStream.use{it.readAllBytes()});request.disconnect()
            assertTrue(seen.isNotEmpty());assertTrue(seen.all{it["uri"]!!.jsonPrimitive.content==source.uri&&it["proxy"]!!.jsonPrimitive.content==source.proxy});assertEquals("Fixture",seen.first()["headers"]!!.jsonObject["User-Agent"]!!.jsonPrimitive.content)
        }}finally{bridge.stop(0)}
    }

}
