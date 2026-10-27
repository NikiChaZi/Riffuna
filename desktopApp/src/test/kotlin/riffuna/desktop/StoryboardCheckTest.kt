package riffuna.desktop

import java.awt.image.BufferedImage
import java.io.ByteArrayOutputStream
import javax.imageio.ImageIO
import kotlin.test.*
import kotlinx.serialization.json.*

class StoryboardCheckTest {
    private fun sheet(changed: Boolean = false, blank: Boolean = false): ByteArray {
        val image = BufferedImage(480, 180, BufferedImage.TYPE_INT_RGB)
        for (cell in 0 until 6) for (y in 0 until 90) for (x in 0 until 160) {
            val color =
                if (blank) 0
                else if (changed && cell == 4) 0xFF0000
                else if ((x + y) % 32 < 16) 0x245485 else 0xB79562
            image.setRGB(cell % 3 * 160 + x, cell / 3 * 90 + y, color)
        }
        val output = ByteArrayOutputStream()
        ImageIO.write(image, "png", output)
        return output.toByteArray()
    }

    private fun metadata(host: String = "i.ytimg.com") = buildJsonObject {
        put("id", "aaaaaaaaaaa")
        put("category", "Music")
        put(
            "storyboards",
            buildJsonArray {
                add(
                    buildJsonObject {
                        put("thumbnail_width", 160)
                        put("thumbnail_height", 90)
                        put("rows", 2)
                        put("columns", 3)
                        put("thumbnail_count", 6)
                        put("storyboard_count", 1)
                        put("template_url", "https://$host/sb/aaaaaaaaaaa/M\$M.jpg")
                    }
                )
            },
        )
    }

    @Test
    fun staticFramesAreObservedAndChangingOrBlankFramesAreRejected() {
        assertNotNull(StoryboardCheck.inspect(metadata()) { _, _ -> sheet() })
        assertNull(StoryboardCheck.inspect(metadata()) { _, _ -> sheet(changed = true) })
        assertNull(StoryboardCheck.inspect(metadata()) { _, _ -> sheet(blank = true) })
        var fetched = false
        assertNull(
            StoryboardCheck.inspect(metadata("example.org")) { _, _ ->
                fetched = true
                sheet()
            }
        )
        assertFalse(fetched)
    }
}
