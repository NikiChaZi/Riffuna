package riffuna.android

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Rect
import java.io.ByteArrayOutputStream
import kotlinx.serialization.json.JsonObject
import okhttp3.OkHttpClient
import okhttp3.Request
import riffuna.catalog.StoryboardGrid
import riffuna.catalog.StoryboardInspection

/** Native decoding only. Recording, URL and static-frame checks are shared with Windows. */
internal object AndroidStoryboardCheck {
    fun inspect(info: JsonObject, http: OkHttpClient): String? =
        StoryboardInspection.inspect(info, { url, limit -> fetch(http, url, limit) }, ::decode)

    private fun fetch(http: OkHttpClient, url: String, limit: Int): ByteArray =
        http.newCall(Request.Builder().url(url).build()).execute().use { response ->
            check(response.isSuccessful)
            val body = requireNotNull(response.body)
            require(body.contentLength() <= limit)
            body.byteStream().use { stream ->
                val output = ByteArrayOutputStream()
                val buffer = ByteArray(8192)
                while (output.size() <= limit) {
                    val read = stream.read(buffer)
                    if (read < 0) break
                    output.write(buffer, 0, read)
                }
                require(output.size() <= limit)
                output.toByteArray()
            }
        }

    private fun decode(data: ByteArray, grid: StoryboardGrid): List<IntArray>? {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeByteArray(data, 0, data.size, bounds)
        if (
            bounds.outWidth != grid.width * grid.columns ||
                bounds.outHeight != grid.height * grid.rows
        )
            return null
        val options =
            BitmapFactory.Options().apply {
                inScaled = false
                inPreferredConfig = Bitmap.Config.ARGB_8888
            }
        val image = BitmapFactory.decodeByteArray(data, 0, data.size, options) ?: return null
        val small = Bitmap.createBitmap(32, 24, Bitmap.Config.ARGB_8888)
        try {
            val canvas = Canvas(small)
            val paint = Paint().apply { isFilterBitmap = false }
            val target = Rect(0, 0, 32, 24)
            return (0 until grid.count).map { cell ->
                val x = cell % grid.columns * grid.width
                val y = cell / grid.columns * grid.height
                canvas.drawColor(Color.BLACK)
                canvas.drawBitmap(image, Rect(x, y, x + grid.width, y + grid.height), target, paint)
                val colors = IntArray(32 * 24)
                small.getPixels(colors, 0, 32, 0, 0, 32, 24)
                IntArray(colors.size * 3).also { pixels ->
                    colors.forEachIndexed { index, color ->
                        pixels[index * 3] = Color.red(color)
                        pixels[index * 3 + 1] = Color.green(color)
                        pixels[index * 3 + 2] = Color.blue(color)
                    }
                }
            }
        } finally {
            small.recycle()
            image.recycle()
        }
    }
}
