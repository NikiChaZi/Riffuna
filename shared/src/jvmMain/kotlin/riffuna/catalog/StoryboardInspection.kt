package riffuna.catalog

import java.net.URI
import kotlinx.serialization.json.*

data class StoryboardGrid(
    val width: Int,
    val height: Int,
    val rows: Int,
    val columns: Int,
    val count: Int,
    val sheets: Int,
)

/** Platform decoders provide RGB samples; both platforms apply the same evidence checks. */
object StoryboardInspection {
    fun inspect(
        info: JsonObject,
        fetch: (String, Int) -> ByteArray,
        decode: (ByteArray, StoryboardGrid) -> List<IntArray>?,
    ): String? {
        val id = info["id"]?.jsonPrimitive?.content ?: return null
        val board =
            info["storyboards"]
                ?.jsonArray
                .orEmpty()
                .map { it.jsonObject }
                .filter { row ->
                    val width = row["thumbnail_width"]?.jsonPrimitive?.intOrNull ?: 0
                    val height = row["thumbnail_height"]?.jsonPrimitive?.intOrNull ?: 0
                    val rows = row["rows"]?.jsonPrimitive?.intOrNull ?: 0
                    val columns = row["columns"]?.jsonPrimitive?.intOrNull ?: 0
                    width in 100..320 &&
                        height in 1..240 &&
                        rows in 1..100 &&
                        columns in 1..100 &&
                        rows * columns in 1..100 &&
                        width.toLong() * height * rows * columns <= 4_000_000 &&
                        (row["thumbnail_count"]?.jsonPrimitive?.intOrNull ?: 0) >= 6
                }
                .maxByOrNull { it["thumbnail_width"]!!.jsonPrimitive.int } ?: return null
        val width = board["thumbnail_width"]!!.jsonPrimitive.int
        val height = board["thumbnail_height"]!!.jsonPrimitive.int
        val rows = board["rows"]!!.jsonPrimitive.int
        val columns = board["columns"]!!.jsonPrimitive.int
        val total = board["thumbnail_count"]!!.jsonPrimitive.int
        val sheets = board["storyboard_count"]?.jsonPrimitive?.intOrNull ?: return null
        if (sheets !in 1..200 || total > rows * columns * sheets) return null
        var reference: IntArray? = null
        var observed = 0
        for (index in listOf(0, sheets / 2, sheets - 1).distinct()) {
            val url =
                board["template_url"]?.jsonPrimitive?.content?.replace("\$M", index.toString())
                    ?: return null
            val uri = URI(url)
            if (
                uri.scheme != "https" ||
                    uri.userInfo != null ||
                    uri.port !in listOf(-1, 443) ||
                    uri.host?.endsWith(".ytimg.com") != true ||
                    !uri.path.startsWith("/sb/$id/")
            )
                return null
            val count = minOf(rows * columns, total - index * rows * columns)
            if (count <= 0) return null
            val data = fetch(url, 2 * 1024 * 1024)
            if (data.size > 2 * 1024 * 1024) return null
            val samples =
                decode(data, StoryboardGrid(width, height, rows, columns, count, sheets))
                    ?: return null
            if (samples.size != count) return null
            for (pixels in samples) {
                if (pixels.size != 32 * 24 * 3) return null
                val gray =
                    DoubleArray(32 * 24) { at ->
                        (pixels[at * 3] + pixels[at * 3 + 1] + pixels[at * 3 + 2]) / 3.0
                    }
                val mean = gray.average()
                if (gray.sumOf { (it - mean) * (it - mean) } / gray.size < 64) return null
                val previous = reference
                if (previous == null) reference = pixels
                else {
                    val differences =
                        pixels.indices.map { kotlin.math.abs(pixels[it] - previous[it]) }
                    if (
                        differences.average() > 3 ||
                            differences.count { it > 24 }.toDouble() / pixels.size > .02
                    )
                        return null
                }
                observed++
            }
        }
        return if (observed >= 6)
            "Категория YouTube: ${info["category"]?.jsonPrimitive?.content}. На $observed выбранных кадрах начала, середины и конца — статичное непустое изображение. Между выбранными кадрами видео не проверено."
        else null
    }
}
