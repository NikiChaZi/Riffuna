package riffuna.catalog

import java.io.ByteArrayOutputStream
import java.io.InputStream
import riffuna.core.CollectionTransfer

fun InputStream.readRiffunaCollection(): String {
    val buffer = ByteArray(8192)
    val output = ByteArrayOutputStream()
    while (true) {
        val count = read(buffer)
        if (count < 0) break
        require(output.size() + count <= CollectionTransfer.maxBytes)
        output.write(buffer, 0, count)
    }
    return output.toByteArray().decodeToString(throwOnInvalidSequence = true)
}
