package riffuna.android

import java.io.IOException
import okhttp3.Call
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response

/** Follow source redirects only after validating every HTTPS destination. */
internal object SourceHttp {
    fun client(): OkHttpClient =
        OkHttpClient.Builder()
            .dns(
                object : okhttp3.Dns {
                    override fun lookup(hostname: String) =
                        okhttp3.Dns.SYSTEM.lookup(hostname).sortedBy {
                            if (it is java.net.Inet4Address) 0 else 1
                        }
                }
            )
            .connectTimeout(15, java.util.concurrent.TimeUnit.SECONDS)
            .readTimeout(20, java.util.concurrent.TimeUnit.SECONDS)
            .callTimeout(25, java.util.concurrent.TimeUnit.SECONDS)
            .followRedirects(false)
            .build()

    fun execute(
        client: OkHttpClient,
        request: Request,
        audioOnly: Boolean = false,
        onCall: (Call) -> Unit = {},
        cancelled: () -> Boolean = { false },
    ): Response {
        var current = request
        for (hop in 0..5) {
            if (!SourceTransportPolicy.allowed(current.url.toString(), audioOnly))
                throw IOException("Blocked source redirect")
            val call = client.newCall(current)
            onCall(call)
            if (cancelled()) call.cancel()
            val response = call.execute()
            if (response.code !in setOf(301, 302, 303, 307, 308)) return response
            val next = response.header("Location")?.let(current.url::resolve)
            val get =
                response.code == 303 ||
                    (response.code in setOf(301, 302) && current.method == "POST")
            response.close()
            if (next == null || hop == 5) throw IOException("Invalid source redirect")
            current =
                current
                    .newBuilder()
                    .url(next)
                    .apply {
                        if (get)
                            method("GET", null)
                                .removeHeader("Content-Type")
                                .removeHeader("Content-Length")
                    }
                    .build()
        }
        throw IOException("Too many source redirects")
    }
}
