package riffuna.desktop

import java.nio.file.*
import kotlin.test.*
import kotlinx.coroutines.*
import kotlinx.serialization.json.*
import riffuna.core.Track

class SourceCancellationTest {
    @Test
    fun cancelledSourceRequestReleasesWorkerForTheNextRequest() = runBlocking {
        fakeSource { source, data ->
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
        }
    }

    @Test
    fun coldResolveStartsBeforeRangeBridgeIsReady() = runBlocking {
        fakeSource { source, _ ->
            val stream =
                withTimeout(15000) { source.resolve(Track("aaaaaaaaaaa", "Track", "Artist", 180)) }
            assertTrue(stream.uri.startsWith("http://127.0.0.1:"))
        }
    }

    private suspend fun fakeSource(test: suspend CoroutineScope.(DesktopSource, Path) -> Unit) =
        coroutineScope {
            val root = Path.of(System.getProperty("user.dir")).parent
            val executable = root.resolve("build/desktop-resources/common/vendor/node/node.exe")
            check(Files.isRegularFile(executable)) {
                "Stage the desktop resources before source tests"
            }
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
            import {existsSync, writeFileSync} from 'node:fs';
            const lines=createInterface({input:process.stdin});
            for await(const line of lines){
                const {action}=JSON.parse(line);
                const result={action};
                if(action==='slow'){
                    writeFileSync(process.argv[2]+'/entered','ready');
                    await new Promise(r=>setTimeout(r,20000));
                }
                if(action==='range_bridge'){
                    while(!existsSync(process.argv[2]+'/resolving')) await new Promise(r=>setTimeout(r,25));
                    result.uri='http://127.0.0.1:1/00000000-0000-4000-8000-000000000000';
                }
                if(action==='resolve'){
                    writeFileSync(process.argv[2]+'/resolving','ready');
                    result.uri='https://example.googlevideo.com/audio';
                }
                process.stdout.write(JSON.stringify({ok:true,result})+'\n');
            }
        """
                    .trimIndent(),
            )
            val source = DesktopSource(home, data)
            try {
                test(source, data)
            } finally {
                source.close()
            }
        }
}
