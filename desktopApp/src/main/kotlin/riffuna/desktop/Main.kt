package riffuna.desktop

import androidx.compose.runtime.*
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Window
import androidx.compose.ui.window.application
import androidx.compose.ui.window.rememberWindowState
import kotlinx.coroutines.delay
import riffuna.core.LocalController
import java.nio.file.Path
import java.nio.file.Files
import kotlinx.serialization.json.*
import javax.imageio.ImageIO
import java.awt.Dimension
import riffuna.desktop.ui.RiffunaApp

fun main(args:Array<String>) {
    if("--diagnose" in args) {
        val home=Path.of(System.getProperty("compose.application.resources.dir")?:System.getProperty("riffuna.home",System.getProperty("user.dir")))
        val index=args.indexOf("--report")
        val report=if(index>=0&&index+1<args.size)Path.of(args[index+1])else Path.of(System.getProperty("java.io.tmpdir"),"riffuna-diagnostics.json")
        kotlin.system.exitProcess(Diagnostics.run(home,report,"--live" in args))
    }
    WindowsAppearance.prepareIdentity()
    val data=System.getenv("MUSICDESK_DATA_DIR")?.let(Path::of)?:Path.of(System.getProperty("user.home"),".riffuna")
    val guard=InstanceGuard.acquire(data)
    if(guard==null){javax.swing.JOptionPane.showMessageDialog(null,"Riffuna уже запущен. Найди окно на панели задач.","Riffuna",javax.swing.JOptionPane.INFORMATION_MESSAGE);return}
    try {runApp(data)}finally{guard.close()}
}

private fun runApp(data:Path) = application {
    val home=Path.of(System.getProperty("compose.application.resources.dir")?:System.getProperty("riffuna.home",System.getProperty("user.dir")))
    val controller=remember { LocalController(SqliteLibrary(data.resolve("library.sqlite3")),DesktopSource(home,data),MpvAudio(home.resolve("vendor/libmpv/libmpv-2.dll"))) }
    val windowState=rememberWindowState(width=1280.dp,height=800.dp)
    val exit={controller.close();exitApplication()}
    LaunchedEffect(Unit) { System.getenv("MUSICDESK_AUTOCLOSE_MS")?.toLongOrNull()?.let{delay(it);exit()} }
    Window(onCloseRequest=exit,title="Riffuna",state=windowState) {
        LaunchedEffect(Unit) {
            window.minimumSize=Dimension(1000,650)
            WindowsAppearance.apply(window)
            runCatching{window.iconImage=ImageIO.read(home.resolve("assets/riffuna.png").toFile())}
            delay(200)
            System.getenv("MUSICDESK_UI_REPORT")?.let { file ->
                val report=buildJsonObject {
                    put("ui","Compose Multiplatform");put("language","Kotlin");put("database_path",data.resolve("library.sqlite3").toAbsolutePath().toString())
                    put("audio_backend","libmpv/JNA");put("source_provider","YouTube.js");put("python_runtime",false);put("qt_runtime",false);put("app_version","0.2.0");put("remote_server",false);put("window_visible",window.isShowing)
                    put("likes",controller.state.value.likes.size);put("queue",controller.state.value.queue.size)
                }
                val path=Path.of(file);Files.createDirectories(path.parent);Files.writeString(path,report.toString())
            }
        }
        RiffunaApp(controller,onOpen={track->runCatching{java.awt.Desktop.getDesktop().browse(java.net.URI("https://www.youtube.com/watch?v="+track.id))}},onImport={
            val dialog=java.awt.FileDialog(window,"Открыть LRC / TTML",java.awt.FileDialog.LOAD)
            dialog.setFilenameFilter {_,name->name.substringAfterLast('.').lowercase() in setOf("lrc","ttml","xml")}
            dialog.isVisible=true
            val name=dialog.file
            if(name!=null)runCatching{val file=Path.of(dialog.directory,name);require(Files.size(file)<=1_048_576);controller.importLyrics(Files.readString(file),name.substringAfterLast('.'))}
            dialog.dispose()
        })
    }
}
