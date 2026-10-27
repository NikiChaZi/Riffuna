"""Optional, bounded word-timing enrichment. A line lyric remains usable on failure."""
from __future__ import annotations

from difflib import SequenceMatcher
import json
import re
import time
import xml.etree.ElementTree as ET

import requests

from .lyric_timing import TimedLine, WordCue, parse_ttml
from .lyrics import MAX_BYTES, _editions, _song_title, _key, packet


def parse_qrc(text):
    if len(text.encode('utf-8')) > MAX_BYTES or re.search(r'<!\s*(?:DOCTYPE|ENTITY)',text,re.I):
        raise ValueError('Unsupported QRC document')
    if text.lstrip().startswith('<'):
        root=ET.fromstring(text)
        text=next((node.attrib['LyricContent'] for node in root.iter() if 'LyricContent' in node.attrib),'')
    result=[]
    for raw in text.splitlines():
        header=re.match(r'^\[(\d+),(\d+)\]',raw.strip())
        if not header:
            continue
        raw=raw.strip()
        start,duration=map(int,header.groups())
        words=[]
        cursor=header.end()
        for stamp in re.finditer(r'\((\d+),(\d+)\)',raw[header.end():]):
            a,b=stamp.start()+header.end(),stamp.end()+header.end()
            value=raw[cursor:a]
            word_start,word_duration=map(int,stamp.groups())
            if value and word_duration>0:
                words.append(WordCue(word_start,word_start+word_duration,value))
            cursor=b
        if words:
            result.append(TimedLine(start,''.join(word.text for word in words).strip(),tuple(words),start+duration))
        if len(result)>10000:
            raise ValueError('Too many QRC lines')
    return tuple(result)


def compatible_words(track, base, rows):
    if not rows or not any(row.words for row in rows) or track.duration<=0:
        return False
    reference=_key(base.get('plain_text') or ' '.join(row['text'] for row in base.get('lines',())))
    candidate=_key(' '.join(row.text for row in rows))
    if not reference or SequenceMatcher(None,reference.split()[:4000],candidate.split()[:4000],autojunk=False).ratio()<.94:
        return False
    if max(word.end_ms for row in rows for word in row.words)>track.duration*1000+2000:
        return False
    # A different intro/master is not accepted just because its words match.
    reference_rows={_key(row['text']): row['start_ms'] for row in base.get('lines',()) if row.get('text','').strip()}
    comparisons=[abs(row.start_ms-reference_rows[_key(row.text)]) for row in rows if _key(row.text) in reference_rows]
    return bool(len(comparisons)>=min(2,len(rows)) and sum(value<=2200 for value in comparisons)/len(comparisons)>=.85)


class BetterWords:
    endpoint='https://api.betterlyrics.org'

    def __init__(self,session_factory=requests.Session):
        self.session_factory=session_factory

    def enrich(self,track,base):
        if base.get('state')!='synced' or _editions(track.title) or track.duration<=0:
            return base
        params={'s':_song_title(track.title,track.artist),'a':track.artist,'al':'','d':track.duration}
        deadline=time.monotonic()+10
        with self.session_factory() as session:
            for path,parser,key in (('/getLyrics',parse_ttml,'ttml'),('/qq/getLyrics',parse_qrc,'lyrics')):
                if time.monotonic()>=deadline:
                    break
                try:
                    with session.get(self.endpoint+path,params=params,headers={'User-Agent':'Riffuna/0.2 (+https://github.com/NikiChaZi/Riffuna)'},
                                     timeout=(2,min(4,max(.25,deadline-time.monotonic()))),stream=True,allow_redirects=False) as response:
                        if response.status_code!=200:
                            continue
                        if 'json' not in response.headers.get('Content-Type',''):
                            continue
                        body=bytearray()
                        for chunk in response.iter_content(16384):
                            body.extend(chunk)
                            if len(body)>MAX_BYTES or time.monotonic()>deadline:
                                raise ValueError('Word lyric response bound')
                        value=json.loads(body)
                    if not isinstance(value,dict) or (isinstance(value.get('score'),(float,int)) and value['score']<.9):
                        continue
                    raw=value.get(key)
                    if not isinstance(raw,str):
                        continue
                    rows=parser(raw)
                    if compatible_words(track,base,rows):
                        return packet(track,'synced',lines=rows,plain_text='\n'.join(row.text for row in rows),
                                      source='Better Lyrics',source_url='https://betterlyrics.org',
                                      timing_source='provider_words',match_quality='metadata_duration')
                except (requests.RequestException,ValueError,KeyError,TypeError,ET.ParseError):
                    continue
        return base
