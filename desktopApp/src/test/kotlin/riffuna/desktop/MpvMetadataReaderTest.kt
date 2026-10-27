package riffuna.desktop

import java.nio.file.*
import javax.sound.sampled.*
import kotlin.test.*

class MpvMetadataReaderTest {
    @Test
    fun realWaveMetadataCanBeReadWithBothOutputsDisabled() {
        val root = Path.of(System.getProperty("user.dir")).parent
        val library = root.resolve("vendor/libmpv/libmpv-2.dll")
        org.junit.Assume.assumeTrue(Files.isRegularFile(library))
        val folder = Files.createTempDirectory("riffuna-local-native")
        val file = folder.resolve("Artist - Song.wav")
        val format = AudioFormat(48000f, 16, 1, true, false)
        AudioInputStream(java.io.ByteArrayInputStream(ByteArray(96000)), format, 48000).use {
            AudioSystem.write(it, AudioFileFormat.Type.WAVE, file.toFile())
        }
        val metadata = MpvMetadataReader(library).read(file)
        assertEquals("Artist", metadata.artist)
        assertEquals("Song", metadata.title)
        assertEquals(1, metadata.duration)
    }
}
