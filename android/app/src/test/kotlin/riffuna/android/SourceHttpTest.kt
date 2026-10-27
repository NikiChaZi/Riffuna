package riffuna.android

import java.io.IOException
import kotlin.test.*
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.Test

class SourceHttpTest {
    @Test
    fun audioRedirectKeepsRangeAndHeaders() {
        val visited = mutableListOf<Request>()
        val client =
            OkHttpClient.Builder()
                .followRedirects(false)
                .addInterceptor { chain ->
                    val request = chain.request()
                    visited.add(request)
                    Response.Builder()
                        .request(request)
                        .protocol(Protocol.HTTP_1_1)
                        .message("Test")
                        .body(byteArrayOf().toResponseBody())
                        .apply {
                            if (visited.size == 1)
                                code(302)
                                    .header(
                                        "Location",
                                        "https://r2.googlevideo.com/videoplayback?follow=1",
                                    )
                            else code(206)
                        }
                        .build()
                }
                .build()
        SourceHttp.execute(
                client,
                Request.Builder()
                    .url("https://r1.googlevideo.com/videoplayback")
                    .header("Range", "bytes=100-199")
                    .header("User-Agent", "RiffunaTest")
                    .build(),
                audioOnly = true,
            )
            .use { assertEquals(206, it.code) }
        assertEquals(2, visited.size)
        assertEquals("bytes=100-199", visited.last().header("Range"))
        assertEquals("RiffunaTest", visited.last().header("User-Agent"))
    }

    @Test
    fun untrustedRedirectIsBlockedBeforeSecondRequest() {
        var calls = 0
        val client =
            OkHttpClient.Builder()
                .followRedirects(false)
                .addInterceptor { chain ->
                    calls++
                    Response.Builder()
                        .request(chain.request())
                        .protocol(Protocol.HTTP_1_1)
                        .message("Redirect")
                        .code(302)
                        .header("Location", "https://untrusted.example/videoplayback")
                        .body(byteArrayOf().toResponseBody())
                        .build()
                }
                .build()
        assertFailsWith<IOException> {
            SourceHttp.execute(
                client,
                Request.Builder().url("https://r1.googlevideo.com/videoplayback").build(),
                audioOnly = true,
            )
        }
        assertEquals(1, calls)
    }

    @Test
    fun redirectLoopIsBounded() {
        var calls = 0
        val client =
            OkHttpClient.Builder()
                .followRedirects(false)
                .addInterceptor { chain ->
                    calls++
                    Response.Builder()
                        .request(chain.request())
                        .protocol(Protocol.HTTP_1_1)
                        .message("Redirect")
                        .code(302)
                        .header("Location", "/videoplayback?again=$calls")
                        .body(byteArrayOf().toResponseBody())
                        .build()
                }
                .build()
        assertFailsWith<IOException> {
            SourceHttp.execute(
                client,
                Request.Builder().url("https://r1.googlevideo.com/videoplayback").build(),
                audioOnly = true,
            )
        }
        assertEquals(6, calls)
    }
}
