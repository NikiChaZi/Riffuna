package riffuna.desktop

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFails
import kotlin.test.assertNull

class WindowsReleaseUpdaterTest {
    private val digest = "ac".repeat(32)
    private val tag = "v0.10.0"
    private val name = "Riffuna-0.10.0-windows-x64.exe"
    private val download = "https://github.com/NikiChaZi/Riffuna/releases/download/$tag/"

    @Test
    fun newerWindowsInstallerUsesGitHubDigest() {
        val release =
            WindowsReleaseUpdater.readRelease(metadata(), "0.9.8") {
                error("GitHub already supplies a digest")
            }
        assertEquals("0.10.0", release?.version)
        assertEquals(digest, release?.sha256)
        assertEquals(download + name, release?.url?.toString())
    }

    @Test
    fun currentVersionAndAssetsFromAnotherRepositoryAreIgnored() {
        assertNull(WindowsReleaseUpdater.readRelease(metadata(), "0.10.0") { error("not needed") })
        assertNull(
            WindowsReleaseUpdater.readRelease(
                metadata().replace("NikiChaZi/Riffuna", "Somebody/Riffuna"),
                "0.9.8",
            ) {
                error("not needed")
            }
        )
    }

    @Test
    fun legacyChecksumMustNameExactAssetAndBeUnambiguous() {
        val raw = metadata().replace(""" "digest":"sha256:$digest" """.trim(), """"digest":null""")
        assertEquals(
            digest,
            WindowsReleaseUpdater.readRelease(raw, "0.9.8") { url ->
                    assertEquals(download + "SHA256SUMS.txt", url.toString())
                    "$digest *$name\n" + "ab".repeat(32) + "  Riffuna.apk"
                }
                ?.sha256,
        )
        assertFails {
            WindowsReleaseUpdater.readRelease(raw, "0.9.8") { "$digest  $name\n$digest  $name" }
        }
    }

    private fun metadata(): String =
        """
        {
            "tag_name":"$tag",
            "draft":false,
            "prerelease":false,
            "assets":[
                {
                    "name":"$name",
                    "browser_download_url":"$download$name",
                    "size":1234,
                    "digest":"sha256:$digest"
                },
                {
                    "name":"SHA256SUMS.txt",
                    "browser_download_url":"${download}SHA256SUMS.txt",
                    "size":120
                }
            ]
        }
        """
            .trimIndent()
}
