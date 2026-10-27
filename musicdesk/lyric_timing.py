"""Bounded, audio-position-driven word timing; no independent playback clock."""
from __future__ import annotations

from dataclasses import dataclass
import re
import xml.etree.ElementTree as ET

MAX_TIME = 6 * 3600 * 1000


@dataclass(frozen=True)
class WordCue:
    start_ms: int
    end_ms: int
    text: str

    def __post_init__(self):
        if type(self.start_ms) is not int or type(self.end_ms) is not int or not 0 <= self.start_ms < self.end_ms <= MAX_TIME:
            raise ValueError('Invalid word timing')
        if not isinstance(self.text, str) or len(self.text) > 10000:
            raise ValueError('Invalid word text')

    def progress(self, position):
        return max(0.0, min(1.0, (position - self.start_ms) / (self.end_ms - self.start_ms)))


@dataclass(frozen=True)
class TimedLine:
    start_ms: int
    text: str
    words: tuple[WordCue, ...] = ()
    end_ms: int | None = None


def timestamp(value):
    value = value.strip()
    if re.fullmatch(r'\d+(?:\.\d+)?ms', value):
        result = round(float(value[:-2]))
    elif re.fullmatch(r'\d+(?:\.\d+)?s', value):
        result = round(float(value[:-1]) * 1000)
    else:
        pieces = value.split(':')
        if len(pieces) not in (2, 3) or not re.fullmatch(r'\d+(?::\d{1,2})?:\d{1,2}(?:\.\d{1,3})?', value):
            raise ValueError('Unsupported lyric timestamp')
        numbers = [float(part) for part in pieces]
        if numbers[-1] >= 60 or (len(numbers) == 3 and numbers[-2] >= 60):
            raise ValueError('Invalid lyric timestamp')
        result = round(sum(number * 60 ** index for index, number in enumerate(reversed(numbers))) * 1000)
    if not 0 <= result <= MAX_TIME:
        raise ValueError('Lyric timestamp outside bound')
    return result


def parse_ttml(text):
    if not isinstance(text, str) or len(text.encode('utf-8')) > 1024 * 1024 or re.search(r'<!\s*(?:DOCTYPE|ENTITY)', text, re.I):
        raise ValueError('Unsupported TTML document')
    root = ET.fromstring(text)
    rows = []
    word_count = 0
    def tag(element):
        return element.tag.rsplit('}',1)[-1]
    def ignored(element):
        return any(key.rsplit('}',1)[-1] == 'role' and value in ('x-bg','x-translation','x-roman') for key,value in element.attrib.items())
    body = next((el for el in root.iter() if tag(el) == 'body'), None)
    if body is None:
        raise ValueError('TTML body missing')
    for p in body.iter():
        if tag(p) != 'p' or ignored(p) or 'begin' not in p.attrib:
            continue
        start = timestamp(p.attrib['begin'])
        end = timestamp(p.attrib['end']) if 'end' in p.attrib else None
        words = []
        def visit(element):
            if ignored(element):
                return
            children = list(element)
            if tag(element) == 'span' and 'begin' in element.attrib and 'end' in element.attrib and not any('begin' in child.attrib for child in children):
                value = ''.join(element.itertext())
                if element.tail and '\n' not in element.tail and '\r' not in element.tail:
                    value += element.tail
                if value:
                    words.append(WordCue(timestamp(element.attrib['begin']), timestamp(element.attrib['end']), value))
                return
            for child in children:
                visit(child)
        visit(p)
        if words:
            if any(a.start_ms > b.start_ms for a,b in zip(words,words[1:])):
                raise ValueError('Unordered TTML words')
            if any(word.start_ms < start or (end is not None and word.end_ms > end+100) for word in words):
                raise ValueError('Words outside lyric line')
            value = ''.join(word.text for word in words).strip()
            end = end or max(word.end_ms for word in words)
        else:
            value = ''.join(p.itertext()).strip()
        if value:
            rows.append(TimedLine(start, value, tuple(words), end))
            word_count += len(words)
        if len(rows) > 10000 or word_count > 50000:
            raise ValueError('Too many lyric segments')
    return tuple(sorted(rows,key=lambda row:row.start_ms))


INLINE = re.compile(r'<(\d{1,3}:\d{2}(?:\.\d{1,3})?)>')


def inline_words(value, offset=0):
    tags = list(INLINE.finditer(value))
    if not tags:
        return value, ()
    plain = INLINE.sub('', value).strip()
    if value[:tags[0].start()].strip():
        return plain, ()
    words = []
    for index, tag in enumerate(tags):
        following = tags[index+1] if index+1 < len(tags) else None
        chunk = value[tag.end():following.start() if following else len(value)]
        if not chunk:
            continue
        start = max(0,timestamp(tag[1])-offset)
        end = max(0,timestamp(following[1])-offset) if following else start + 1500
        if end <= start:
            return plain, ()
        words.append(WordCue(start,end,chunk))
    return plain, tuple(words)


def estimated_words(text, start, end):
    """Presentation estimate bounded by the known line, never acoustic alignment."""
    chunks = re.findall(r'\S+\s*', text)
    if not chunks or end <= start:
        return ()
    # Do not spread one sung phrase over a long instrumental break/outro.
    end = min(end, start + max(1400, min(10000, len(chunks)*650)))
    weights = [max(1,min(12,sum(c.isalnum() for c in chunk))) for chunk in chunks]
    total = sum(weights)
    result=[]
    elapsed=0
    for index,(chunk,weight) in enumerate(zip(chunks,weights)):
        left = start + round((end-start)*elapsed/total)
        elapsed += weight
        right = start + round((end-start)*elapsed/total)
        if right > left:
            result.append(WordCue(left,right,chunk))
    return tuple(result)
