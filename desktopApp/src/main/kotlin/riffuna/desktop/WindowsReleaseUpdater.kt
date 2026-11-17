package riffuna.desktop

import java.io.IOException
import java.net.URI
import java.nio.file.Files
import java.nio.file.Path
import java.nio.file.StandardCopyOption
import java.security.MessageDigest
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.withContext
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

internal data class WindowsRelease(
    val version: String,
    val name: String,
    val size: Long,
    val sha256: String,
    val url: URI,
)

internal class WindowsReleaseUpdater(private val home: Path) {
    private val helper = windowsHelper(home)
    private val runtime = home.parent?.parent
    val portable =
        System.getProperty("compose.application.resources.dir") == null ||
            runtime?.fileName?.toString().equals("Riffuna.runtime", ignoreCase = true)
    val version: String? =
        runCatching { Files.readString(home.resolve("vendor/windows/version.txt")).trim() }
            .getOrNull()
            ?.takeIf { versionParts(it) != null }

    val available: Boolean = version != null && Files.isRegularFile(helper)

    suspend fun check(): WindowsRelease? =
        withContext(Dispatchers.IO) {
            val current = version ?: error("Не удалось определить версию Riffuna.")
            val raw = metadata("https://api.github.com/repos/NikiChaZi/Riffuna/releases/latest")
            readRelease(raw, current, ::downloadText)
        }

    suspend fun prepareInstaller(release: WindowsRelease, onProgress: (Long) -> Unit) {
        withContext(Dispatchers.IO) {
            check(available && !portable) { "Установка доступна только для установленной сборки." }
            val directory = Files.createTempDirectory("riffuna-update-")
            val installer = directory.resolve(release.name)
            val updater = directory.resolve("RiffunaWindows.exe")
            try {
                val digest = MessageDigest.getInstance("SHA-256")
                var received = 0L
                connection(release.url, assetHosts).useResponse { response ->
                    response.inputStream.use { input ->
                        Files.newOutputStream(installer).use { output ->
                            val block = ByteArray(128 * 1024)
                            while (true) {
                                currentCoroutineContext().ensureActive()
                                val count = input.read(block)
                                if (count < 0) break
                                received += count
                                check(received <= release.size) { "Размер установщика не совпал." }
                                digest.update(block, 0, count)
                                output.write(block, 0, count)
                                onProgress(received)
                            }
                        }
                    }
                }
                check(received == release.size && digest.digest().toHex() == release.sha256) {
                    "Размер или SHA-256 установщика не совпали."
                }
                Files.copy(helper, updater, StandardCopyOption.COPY_ATTRIBUTES)
                currentCoroutineContext().ensureActive()
                ProcessBuilder(
                        updater.toString(),
                        "--install",
                        ProcessHandle.current().pid().toString(),
                        installer.toString(),
                        release.sha256,
                    )
                    .directory(directory.toFile())
                    .redirectOutput(ProcessBuilder.Redirect.DISCARD)
                    .redirectError(ProcessBuilder.Redirect.DISCARD)
                    .start()
            } catch (failure: Exception) {
                listOf(installer, updater, directory).forEach {
                    runCatching { Files.deleteIfExists(it) }
                }
                throw failure
            }
        }
    }

    private fun metadata(url: String): String =
        connection(URI(url), setOf("api.github.com")).useResponse { response ->
            response.inputStream.use { input -> readBoundedText(input, 2 * 1024 * 1024) }
        }

    private fun downloadText(url: URI): String =
        connection(url, assetHosts).useResponse { response ->
            response.inputStream.use { input -> readBoundedText(input, 32 * 1024) }
        }

    private fun readBoundedText(input: java.io.InputStream, limit: Int): String =
        input.readNBytes(limit + 1).also { require(it.size <= limit) }.toString(Charsets.UTF_8)

    private fun connection(initial: URI, hosts: Set<String>): java.net.HttpURLConnection {
        var uri = initial
        repeat(5) {
            require(uri.scheme == "https" && uri.host in hosts && uri.userInfo == null)
            require(uri.port == -1 || uri.port == 443)
            val response =
                DesktopNetwork.open(uri.toString()).apply {
                    instanceFollowRedirects = false
                    connectTimeout = 10_000
                    readTimeout = 30_000
                    setRequestProperty(
                        "Accept",
                        if (uri.host == "api.github.com") "application/vnd.github+json" else "*/*",
                    )
                }
            try {
                val status = response.responseCode
                if (status == 200) return response
                if (status !in setOf(301, 302, 303, 307, 308))
                    throw IOException("GitHub ответил с кодом $status.")
                uri =
                    uri.resolve(
                        response.getHeaderField("Location")
                            ?: throw IOException("Пустое перенаправление.")
                    )
            } catch (failure: Exception) {
                response.disconnect()
                throw failure
            }
            response.disconnect()
        }
        throw IOException("GitHub перенаправил запрос слишком много раз.")
    }

    private inline fun <T> java.net.HttpURLConnection.useResponse(
        block: (java.net.HttpURLConnection) -> T
    ): T =
        try {
            block(this)
        } finally {
            disconnect()
        }

    companion object {
        private val json = Json { ignoreUnknownKeys = true }
        private val semver =
            Regex("""(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})""")
        private val sha = Regex("[0-9a-f]{64}")
        private val assetHosts =
            setOf(
                "github.com",
                "release-assets.githubusercontent.com",
                "objects.githubusercontent.com",
            )

        private fun versionParts(version: String): List<Int>? =
            semver.matchEntire(version)?.groupValues?.drop(1)?.map(String::toInt)

        private fun isNewer(candidate: List<Int>, current: List<Int>): Boolean =
            candidate.zip(current).firstOrNull { (a, b) -> a != b }?.let { (a, b) -> a > b }
                ?: false

        internal fun readRelease(
            raw: String,
            currentVersion: String,
            checksums: (URI) -> String,
        ): WindowsRelease? {
            val current = versionParts(currentVersion) ?: return null
            val release = json.decodeFromString<ReleaseMetadata>(raw)
            if (release.draft || release.prerelease || !release.tag_name.startsWith("v"))
                return null
            val version = release.tag_name.drop(1)
            val candidate = versionParts(version) ?: return null
            if (!isNewer(candidate, current)) return null

            val root = "https://github.com/NikiChaZi/Riffuna/releases/download/${release.tag_name}/"
            val name = "Riffuna-$version-windows-x64.exe"
            val asset =
                release.assets.singleOrNull {
                    it.name == name && it.browser_download_url == root + name
                } ?: return null
            require(asset.size in 1..1_073_741_824L) { "Некорректный размер установщика." }
            val digest = asset.digest.orEmpty().lowercase()
            val hash =
                if (digest.startsWith("sha256:") && sha.matches(digest.removePrefix("sha256:")))
                    digest.removePrefix("sha256:")
                else {
                    val sums =
                        release.assets.singleOrNull {
                            it.name == "SHA256SUMS.txt" &&
                                it.browser_download_url == root + "SHA256SUMS.txt"
                        } ?: error("В релизе отсутствует контрольная сумма установщика.")
                    checksums(URI(sums.browser_download_url))
                        .lineSequence()
                        .mapNotNull { line ->
                            val parts = line.trim().split(Regex("\\s+"), limit = 2)
                            val checksum = parts.first().lowercase()
                            if (
                                parts.size == 2 &&
                                    parts.last().removePrefix("*") == name &&
                                    sha.matches(checksum)
                            )
                                checksum
                            else null
                        }
                        .singleOrNull() ?: error("Нет однозначной контрольной суммы установщика.")
                }
            return WindowsRelease(version, name, asset.size, hash, URI(asset.browser_download_url))
        }

        private fun ByteArray.toHex(): String = joinToString("") { "%02x".format(it) }
    }
}

@Serializable
private data class ReleaseMetadata(
    val tag_name: String,
    val draft: Boolean = true,
    val prerelease: Boolean = true,
    val assets: List<ReleaseAsset> = emptyList(),
)

@Serializable
private data class ReleaseAsset(
    val name: String,
    val browser_download_url: String,
    val size: Long,
    val digest: String? = null,
)
