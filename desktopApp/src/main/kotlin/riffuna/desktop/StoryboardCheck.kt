package riffuna.desktop

import java.awt.image.BufferedImage
import javax.imageio.ImageIO
import kotlinx.serialization.json.JsonObject
import riffuna.catalog.StoryboardGrid
import riffuna.catalog.StoryboardInspection

/** Desktop image decoding for the shared static-artwork checks. */
object StoryboardCheck {
    fun inspect(
        info: JsonObject,
        fetch: (String, Int) -> ByteArray = DesktopNetwork::bytes,
    ): String? = StoryboardInspection.inspect(info, fetch, ::decode)

    private fun decode(data: ByteArray, grid: StoryboardGrid): List<IntArray>? {
        val image =
            ImageIO.createImageInputStream(data.inputStream()).use { input ->
                val readers = ImageIO.getImageReaders(input)
                if (!readers.hasNext()) return null
                val reader = readers.next()
                try {
                    reader.input = input
                    if (
                        reader.getWidth(0) != grid.width * grid.columns ||
                            reader.getHeight(0) != grid.height * grid.rows
                    )
                        return null
                    reader.read(0)
                } finally {
                    reader.dispose()
                }
            }
        return (0 until grid.count).map { cell ->
            val small = BufferedImage(32, 24, BufferedImage.TYPE_INT_RGB)
            val graphics = small.createGraphics()
            try {
                graphics.drawImage(
                    image.getSubimage(
                        cell % grid.columns * grid.width,
                        cell / grid.columns * grid.height,
                        grid.width,
                        grid.height,
                    ),
                    0,
                    0,
                    32,
                    24,
                    null,
                )
            } finally {
                graphics.dispose()
            }
            val pixels = IntArray(32 * 24 * 3)
            for (y in 0 until 24) for (x in 0 until 32) {
                val color = small.getRGB(x, y)
                val at = (y * 32 + x) * 3
                pixels[at] = (color ushr 16) and 255
                pixels[at + 1] = (color ushr 8) and 255
                pixels[at + 2] = color and 255
            }
            pixels
        }
    }
}
