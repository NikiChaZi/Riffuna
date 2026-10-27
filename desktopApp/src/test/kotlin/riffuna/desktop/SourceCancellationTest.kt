package riffuna.desktop

import java.nio.file.*
import kotlin.test.*
import kotlinx.coroutines.*
import kotlinx.serialization.json.*

class SourceCancellationTest {
    @Test
    fun cancelledSourceRequestReleasesWorkerForTheNextRequest() = runBlocking {
        val root = Path.of(System.getProperty("user.dir")).parent
        val executable = root.resolve("build/desktop-resources/common/vendor/node/node.exe")
        check(Files.isRegularFile(executable)) { "Stage the desktop resources before source tests" }
        val home = Files.createTempDirectory("riffuna-source-cancel")
        val data = Files.createTempDirectory("riffuna-source-data")
        Files.createDirectories(data.resolve("youtube-js"))
        Files.createDirectories(home.resolve("vendor/node"))
        Files.createDirectories(home.resolve("source-runtime"))
        try {
            Files.createLink(home.resolve("vendor/node/node.exe"), executable)
        } catch (_: Exception) {
            Files.copy(executable, home.resolve("vendor/node/node.exe"))
        }
        Files.writeString(
            home.resolve("source-runtime/index.mjs"),
            """
            import {createInterface} from 'node:readline';
            import {writeFileSync} from 'node:fs';
            const lines=createInterface({input:process.stdin});
            for await(const line of lines){const request=JSON.parse(line);if(request.action==='slow'){writeFileSync(process.argv[2]+'/entered','ready');await new Promise(r=>setTimeout(r,20000));}process.stdout.write(JSON.stringify({ok:true,result:{action:request.action}})+'\n');}
        """
                .trimIndent(),
        )
        val source = DesktopSource(home, data)
        try {
            val slow = launch { source.request(buildJsonObject { put("action", "slow") }) }
            withTimeout(15000) {
                while (!Files.exists(data.resolve("youtube-js/entered"))) delay(25)
            }
            slow.cancel()
            withTimeout(3000) { slow.join() }
            // A cold Windows process can be scanned by antivirus; do not count that as cancellation
            // latency.
            val reply =
                withTimeout(15000) {
                    source.request(buildJsonObject { put("action", "capabilities") })
                }
            assertEquals("capabilities", reply["action"]!!.jsonPrimitive.content)
        } finally {
            source.close()
        }
    }
}
