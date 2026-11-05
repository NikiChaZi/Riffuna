package riffuna.catalog

import java.util.regex.Pattern

private val unicodeClassFlag =
    try {
        Pattern.compile("", Pattern.UNICODE_CHARACTER_CLASS)
        Pattern.UNICODE_CHARACTER_CLASS
    } catch (_: IllegalArgumentException) {
        // Android already uses Unicode classes and rejects both the flag and inline (?U).
        0
    }

/** The same Unicode matching policy on the JDK and Android's ICU regex engine. */
internal fun unicodeRegex(pattern: String): Regex =
    Pattern.compile(pattern, Pattern.CASE_INSENSITIVE or Pattern.UNICODE_CASE or unicodeClassFlag)
        .toRegex()
