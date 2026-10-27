package riffuna.desktop

import java.text.Normalizer
import java.util.Locale

/** Normalization shared by matching, model features and recording identity. */
internal object MusicText {
    private val separators = Regex("[^\\p{L}\\p{N}]+")
    private val legacySeparators = Regex("[^\\p{L}\\p{N}_]+")

    private fun folded(value: String): String =
        Normalizer.normalize(value, Normalizer.Form.NFKC)
            .lowercase(Locale.ROOT)
            .replace("ё", "е")
            .replace("ß", "ss")

    fun normalized(value: String): String =
        separators.replace(folded(value).replace("ς", "σ"), " ").trim()

    fun legacyNormalized(value: String): String =
        legacySeparators.replace(folded(value), " ").trim()
}
