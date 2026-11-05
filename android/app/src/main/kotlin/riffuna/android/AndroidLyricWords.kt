package riffuna.android

import javax.xml.parsers.DocumentBuilderFactory
import org.w3c.dom.Element
import riffuna.core.*

/** Provider word timestamps are retained only after recording and lyric matching. */
internal object AndroidLyricWords {
    private fun xml(text: String): Element {
        require(
            text.toByteArray().size <= 1_048_576 &&
                !Regex("<!\\s*(?:DOCTYPE|ENTITY)", RegexOption.IGNORE_CASE).containsMatchIn(text)
        )
        val factory = DocumentBuilderFactory.newInstance()
        factory.isNamespaceAware = true
        factory.isExpandEntityReferences = false
        return factory.newDocumentBuilder().parse(text.byteInputStream()).documentElement
    }

    fun parseTtml(text: String): List<LyricLine> {
        val root = xml(text)
        val nodes = root.getElementsByTagNameNS("*", "p")
        val rows = mutableListOf<LyricLine>()
        for (i in 0 until nodes.length) {
            val p = nodes.item(i) as Element
            if (!p.hasAttribute("begin")) continue
            val start = LyricTiming.timestamp(p.getAttribute("begin"))
            val end = p.getAttribute("end").takeIf { it.isNotBlank() }?.let(LyricTiming::timestamp)
            val words = mutableListOf<LyricWord>()
            fun visit(element: Element) {
                for (a in 0 until element.attributes.length) {
                    val attribute = element.attributes.item(a)
                    if (
                        attribute.localName == "role" &&
                            attribute.nodeValue in setOf("x-bg", "x-translation", "x-roman")
                    )
                        return
                }
                val children =
                    (0 until element.childNodes.length)
                        .map { element.childNodes.item(it) }
                        .filterIsInstance<Element>()
                if (
                    element.localName == "span" &&
                        element.hasAttribute("begin") &&
                        element.hasAttribute("end") &&
                        children.none { it.hasAttribute("begin") }
                ) {
                    val a = LyricTiming.timestamp(element.getAttribute("begin"))
                    val b = LyricTiming.timestamp(element.getAttribute("end"))
                    val tail =
                        element.nextSibling
                            ?.takeIf { it.nodeType == org.w3c.dom.Node.TEXT_NODE }
                            ?.nodeValue
                            ?.takeIf { '\n' !in it && '\r' !in it }
                            .orEmpty()
                    require(a >= start && b > a && (end == null || b <= end + 100))
                    words.add(LyricWord(a, b, element.textContent + tail))
                    return
                }
                children.forEach(::visit)
            }
            visit(p)
            require(words.zipWithNext().all { it.first.startMs <= it.second.startMs })
            val value =
                if (words.isEmpty()) p.textContent.trim()
                else words.joinToString("") { it.text }.trim()
            if (value.isNotEmpty())
                rows.add(LyricLine(start, end ?: words.maxOfOrNull { it.endMs }, value, words))
            require(rows.size <= 10000)
        }
        return rows.sortedBy { it.startMs }
    }

    fun parseQrc(document: String): List<LyricLine> {
        var text = document
        if (text.trimStart().startsWith('<')) {
            val elements = xml(text).getElementsByTagName("*")
            text =
                (0 until elements.length)
                    .mapNotNull {
                        (elements.item(it) as? Element)?.getAttribute("LyricContent")?.takeIf {
                            it.isNotBlank()
                        }
                    }
                    .firstOrNull() ?: ""
        }
        return text
            .lineSequence()
            .mapNotNull { line ->
                val header = Regex("^\\[(\\d+),(\\d+)]").find(line.trim()) ?: return@mapNotNull null
                val raw = line.trim()
                var cursor = header.range.last + 1
                val words = mutableListOf<LyricWord>()
                Regex("\\((\\d+),(\\d+)\\)").findAll(raw, cursor).forEach { stamp ->
                    val value = raw.substring(cursor, stamp.range.first)
                    val start = stamp.groupValues[1].toLong()
                    val duration = stamp.groupValues[2].toLong()
                    if (value.isNotEmpty() && duration > 0)
                        words.add(LyricWord(start, start + duration, value))
                    cursor = stamp.range.last + 1
                }
                if (words.isEmpty()) null
                else
                    LyricLine(
                        header.groupValues[1].toLong(),
                        header.groupValues[1].toLong() + header.groupValues[2].toLong(),
                        words.joinToString("") { it.text }.trim(),
                        words,
                    )
            }
            .take(10000)
            .toList()
    }
}
