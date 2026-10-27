package riffuna.desktop

import com.sun.jna.platform.win32.Advapi32Util
import com.sun.jna.platform.win32.WinReg
import java.net.*

object DesktopNetwork {
    fun proxyUrl(): String {
        val environment =
            listOf("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy").firstNotNullOfOrNull {
                System.getenv(it)?.takeIf(String::isNotBlank)
            }
        if (environment != null) return environment
        if (!System.getProperty("os.name").startsWith("Windows", true)) return ""
        return runCatching {
                val path = "Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings"
                if (
                    Advapi32Util.registryGetIntValue(
                        WinReg.HKEY_CURRENT_USER,
                        path,
                        "ProxyEnable",
                    ) != 1
                )
                    return ""
                val all =
                    Advapi32Util.registryGetStringValue(
                        WinReg.HKEY_CURRENT_USER,
                        path,
                        "ProxyServer",
                    )
                val selected =
                    if ('=' in all)
                        all.split(';').firstOrNull { it.startsWith("https=") }?.substringAfter('=')
                            ?: all.split(';')
                                .firstOrNull { it.startsWith("http=") }
                                ?.substringAfter('=')
                            ?: ""
                    else all
                if (selected.isBlank()) ""
                else if ("://" in selected) selected else "http://$selected"
            }
            .getOrDefault("")
    }

    fun open(url: String, proxy: String = proxyUrl()): HttpURLConnection {
        val uri = URI(url)
        require(uri.scheme in setOf("http", "https"))
        val connection =
            if (proxy.isBlank()) uri.toURL().openConnection(Proxy.NO_PROXY)
            else {
                val target = URI(proxy)
                require(target.scheme in setOf("http", "https"))
                uri.toURL()
                    .openConnection(
                        Proxy(
                            Proxy.Type.HTTP,
                            InetSocketAddress(target.host, if (target.port > 0) target.port else 80),
                        )
                    )
            }
        return (connection as HttpURLConnection).apply {
            connectTimeout = 5000
            readTimeout = 10000
            instanceFollowRedirects = true
            setRequestProperty("User-Agent", "Riffuna/0.2.0")
            setRequestProperty("Accept-Encoding", "identity")
        }
    }

    fun bytes(url: String, limit: Int = 1_000_000): ByteArray {
        val connection = open(url)
        try {
            check(connection.responseCode == 200)
            val bytes = connection.inputStream.use { it.readNBytes(limit + 1) }
            check(bytes.size <= limit)
            return bytes
        } finally {
            connection.disconnect()
        }
    }
}
