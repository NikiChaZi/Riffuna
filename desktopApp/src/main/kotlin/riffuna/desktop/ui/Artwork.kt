@file:OptIn(androidx.compose.ui.ExperimentalComposeUiApi::class)

package riffuna.desktop.ui

import androidx.compose.foundation.*
import androidx.compose.foundation.gestures.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.*
import androidx.compose.ui.draw.*
import androidx.compose.ui.geometry.*
import androidx.compose.ui.graphics.*
import androidx.compose.ui.input.pointer.*
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.semantics.*
import androidx.compose.ui.unit.*
import java.net.URI
import java.nio.file.*
import java.nio.file.Path as FilePath
import java.util.concurrent.Semaphore
import kotlinx.coroutines.*
import org.jetbrains.skia.Image as SkiaImage
import riffuna.desktop.ArtworkStore

private object ArtworkCache {
    private val memory = linkedMapOf<String, ImageBitmap>()
    private val slots = Semaphore(4)
    private val store by lazy {
        ArtworkStore(
            FilePath.of(
                    System.getenv("MUSICDESK_DATA_DIR")
                        ?: FilePath.of(System.getProperty("user.home"), ".riffuna").toString()
                )
                .resolve("artwork")
        )
    }

    suspend fun load(url: String): ImageBitmap? =
        withContext(Dispatchers.IO) {
            if (url.isBlank()) return@withContext null
            synchronized(memory) {
                memory[url]?.let {
                    return@withContext it
                }
            }
            runCatching {
                    slots.acquire()
                    try {
                        synchronized(memory) {
                            memory[url]?.let {
                                return@withContext it
                            }
                        }
                        val image =
                            SkiaImage.makeFromEncoded(store.load(url)).toComposeImageBitmap()
                        synchronized(memory) {
                            memory[url] = image
                            while (memory.size > 64) memory.remove(memory.keys.first())
                        }
                        image
                    } finally {
                        slots.release()
                    }
                }
                .getOrNull()
        }
}

@Composable
fun Artwork(
    url: String,
    modifier: Modifier = Modifier,
    description: String? = null,
    radius: Dp = 10.dp,
) {
    BoxWithConstraints(modifier.clip(RoundedCornerShape(radius)).background(RiffunaColors.Raised)) {
        val pixels = if (maxWidth > 240.dp) 720 else if (maxWidth > 100.dp) 512 else 128
        val quality =
            remember(url, pixels) {
                runCatching {
                        val host = URI(url).host.orEmpty()
                        when {
                            host.endsWith("googleusercontent.com") || host.endsWith("ggpht.com") ->
                                Regex("w\\d+-h\\d+").replace(url, "w$pixels-h$pixels")
                            host.endsWith("ytimg.com") && pixels > 128 ->
                                Regex("/(?:default|mqdefault|sddefault)\\.jpg")
                                    .replace(url, "/hqdefault.jpg")
                            else -> url
                        }
                    }
                    .getOrDefault(url)
            }
        val image by
            produceState<ImageBitmap?>(null, quality) {
                value =
                    ArtworkCache.load(quality)
                        ?: if (quality != url) ArtworkCache.load(url) else null
            }
        val actual = image
        if (actual != null)
            Image(actual, description, Modifier.fillMaxSize(), contentScale = ContentScale.Crop)
        else
            Canvas(Modifier.fillMaxSize().padding(16.dp)) {
                val r = size.minDimension * .42f
                drawCircle(RiffunaColors.Border, r)
                for (fraction in listOf(.85f, .7f, .55f)) drawCircle(
                    RiffunaColors.Secondary.copy(alpha = .12f),
                    r * fraction,
                    style = androidx.compose.ui.graphics.drawscope.Stroke(1f),
                )
                drawCircle(RiffunaColors.Coral.copy(alpha = .6f), r * .2f)
                drawCircle(RiffunaColors.Raised, r * .065f)
            }
    }
}

/** Click and drag share one normalized coordinate; seeks commit once on release. */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun ProgressSlider(
    value: Float,
    onChange: (Float) -> Unit,
    modifier: Modifier = Modifier,
    onCommit: ((Float) -> Unit)? = null,
    enabled: Boolean = true,
    label: (Float) -> String = { "${(it*100).toInt()}%" },
) {
    var width by remember { mutableFloatStateOf(1f) }
    var hover by remember { mutableStateOf(false) }
    var hoverX by remember { mutableFloatStateOf(0f) }
    var draft by remember { mutableStateOf<Float?>(null) }
    val currentChange by rememberUpdatedState(onChange)
    val currentCommit by rememberUpdatedState(onCommit)
    val shown = (draft ?: value).coerceIn(0f, 1f)
    fun update(x: Float) {
        val next = (x / width).coerceIn(0f, 1f)
        draft = next
        if (currentCommit == null) currentChange(next)
    }
    Box(modifier) {
        TooltipArea(
            tooltip = {
                Surface(color = RiffunaColors.Raised, shape = RoundedCornerShape(6.dp)) {
                    Text(
                        label((hoverX / width).coerceIn(0f, 1f)),
                        Modifier.padding(horizontal = 9.dp, vertical = 5.dp),
                        style = MaterialTheme.typography.labelMedium,
                    )
                }
            },
            delayMillis = 250,
        ) {
            Box(
                Modifier.fillMaxWidth()
                    .height(24.dp)
                    .onSizeChanged { width = it.width.toFloat().coerceAtLeast(1f) }
                    .onPointerEvent(PointerEventType.Enter) {
                        hover = true
                        it.changes.firstOrNull()?.let { p -> hoverX = p.position.x }
                    }
                    .onPointerEvent(PointerEventType.Move) {
                        it.changes.firstOrNull()?.let { p -> hoverX = p.position.x }
                    }
                    .onPointerEvent(PointerEventType.Exit) { hover = false }
                    .semantics {
                        progressBarRangeInfo = ProgressBarRangeInfo(shown, 0f..1f)
                        setProgress {
                            if (enabled) {
                                currentChange(it)
                                currentCommit?.invoke(it)
                                true
                            } else false
                        }
                    }
                    .pointerInput(enabled) {
                        if (enabled)
                            detectTapGestures { position ->
                                val next = (position.x / width).coerceIn(0f, 1f)
                                currentChange(next)
                                currentCommit?.invoke(next)
                            }
                    }
                    .pointerInput(enabled) {
                        if (enabled)
                            detectDragGestures(
                                onDragStart = { update(it.x) },
                                onDragEnd = {
                                    draft?.let {
                                        currentChange(it)
                                        currentCommit?.invoke(it)
                                    }
                                    draft = null
                                },
                                onDragCancel = { draft = null },
                                onDrag = { change, _ ->
                                    change.consume()
                                    update(change.position.x)
                                },
                            )
                    }
            ) {
                Canvas(Modifier.fillMaxSize()) {
                    val y = size.height / 2
                    drawRoundRect(
                        RiffunaColors.Border,
                        Offset(0f, y - 2.dp.toPx()),
                        Size(size.width, 4.dp.toPx()),
                        CornerRadius(2.dp.toPx()),
                    )
                    if (shown > 0)
                        drawRoundRect(
                            if (enabled) RiffunaColors.Coral else RiffunaColors.Muted,
                            Offset(0f, y - 2.dp.toPx()),
                            Size(size.width * shown, 4.dp.toPx()),
                            CornerRadius(2.dp.toPx()),
                        )
                    if (enabled && (hover || draft != null))
                        drawCircle(RiffunaColors.Text, 5.dp.toPx(), Offset(size.width * shown, y))
                }
            }
        }
    }
}
