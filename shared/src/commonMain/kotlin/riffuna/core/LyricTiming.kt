package riffuna.core

object LyricTiming {
    private const val MAX=21_600_000L
    fun timestamp(value:String):Long {
        val text=value.trim()
        val time=when {
            text.endsWith("ms")->text.dropLast(2).toDouble().toLong()
            text.endsWith("s")->(text.dropLast(1).toDouble()*1000).toLong()
            else->{val parts=text.split(':');require(parts.size in 2..3);val numbers=parts.map{it.toDouble()};require(numbers.last()<60&&(numbers.size<3||numbers[1]<60));var seconds=0.0;numbers.forEach{seconds=seconds*60+it};(seconds*1000).toLong()}
        }
        require(time in 0..MAX);return time
    }
    fun parseLrc(text:String):List<LyricLine> {
        require(text.encodeToByteArray().size<=1_048_576)
        val offset=Regex("\\[offset:\\s*([+-]?\\d+)\\s*]",RegexOption.IGNORE_CASE).find(text)?.groupValues?.get(1)?.toLongOrNull()?:0L
        val stamp=Regex("\\[(\\d{1,3}):(\\d{2})(?:[.:](\\d{1,3}))?]")
        val inline=Regex("<(\\d{1,3}:\\d{2}(?:\\.\\d{1,3})?)>")
        val rows=mutableListOf<LyricLine>()
        text.removePrefix("\uFEFF").lineSequence().forEach {raw->
            val stamps=stamp.findAll(raw).toList();if(stamps.isEmpty())return@forEach
            val value=stamp.replace(raw,"").trim();val words=mutableListOf<LyricWord>();val tags=inline.findAll(value).toList()
            if(tags.isNotEmpty()&&value.take(tags.first().range.first).isBlank())tags.forEachIndexed {i,tag->
                val next=tags.getOrNull(i+1);val chunk=value.substring(tag.range.last+1,next?.range?.first?:value.length)
                val begin=(timestamp(tag.groupValues[1])-offset).coerceAtLeast(0);val end=next?.let{(timestamp(it.groupValues[1])-offset).coerceAtLeast(0)}?:begin+1500
                if(chunk.isNotEmpty()&&end>begin)words.add(LyricWord(begin,end,chunk))
            }
            val plain=inline.replace(value,"").trim()
            stamps.forEach {s->val fraction=s.groupValues[3].padEnd(3,'0').toLongOrNull()?:0;val start=((s.groupValues[1].toLong()*60+s.groupValues[2].toLong())*1000+fraction-offset).coerceAtLeast(0)
                if(start<=MAX){val cues=if(stamps.size==1)words else emptyList();rows.add(LyricLine(start,cues.maxOfOrNull{it.endMs},plain,cues))}}
            require(rows.size<=10000)
        }
        return rows.distinct().sortedBy{it.startMs}
    }
    fun estimatedWords(text:String,start:Long,end:Long):List<LyricWord> {
        val chunks=Regex("\\S+\\s*").findAll(text).map{it.value}.toList();if(chunks.isEmpty()||end<=start)return emptyList()
        val finish=minOf(end,start+maxOf(1400,minOf(10000,chunks.size*650)))
        val weights=chunks.map{it.count(Char::isLetterOrDigit).coerceIn(1,12)};val total=weights.sum();var elapsed=0
        return chunks.mapIndexedNotNull{i,chunk->val left=start+(finish-start)*elapsed/total;elapsed+=weights[i];val right=start+(finish-start)*elapsed/total;if(right>left)LyricWord(left,right,chunk)else null}
    }
}
