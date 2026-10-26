"""Bounded artist-level public tags; they are not exact per-recording genres."""
from __future__ import annotations
import hashlib,json,time,threading
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote,unquote,urlparse
import requests
from .features import normalize

class TagParser(HTMLParser):
    def __init__(self):super().__init__();self.collect=False;self.tags=[]
    def handle_starttag(self,tag,attrs):
        if tag=="a":self.collect=dict(attrs).get("href","").startswith("/tag/")
    def handle_data(self,data):
        if self.collect and data.strip():self.tags.append(data.strip())
    def handle_endtag(self,tag):
        if tag=="a":self.collect=False

class ArtistTags:
    def __init__(self,directory,session_factory=requests.Session,clock=time.time):
        self.directory=Path(directory);self.directory.mkdir(parents=True,exist_ok=True)
        self.session_factory=session_factory;self.clock=clock;self.lock=threading.Lock();self.last=0.
    def fetch(self,artist):
        key=hashlib.sha256(normalize(artist).encode()).hexdigest();path=self.directory/(key+".json")
        try:
            data=json.loads(path.read_text(encoding="utf-8"))
            if data.get("artist")==artist and self.clock()-data["at"]<(2592000 if data.get("tags") else 21600):return data
        except (OSError,ValueError,KeyError,TypeError):pass
        url="https://www.last.fm/music/"+quote(artist,safe="")+"/+tags"
        result=dict(artist=artist,tags=[],source="Last.fm artist tags",source_url=url,at=self.clock())
        try:
            with self.lock:
                wait=1-(time.monotonic()-self.last)
                if wait>0:time.sleep(wait)
                self.last=time.monotonic()
            with self.session_factory() as session:
                with session.get(url,headers={"User-Agent":"Riffuna/0.2.0 (https://github.com/NikiChaZi/Riffuna; music metadata)"},stream=True,timeout=(3,6)) as r:
                    r.raise_for_status();parsed=urlparse(r.url);parts=unquote(parsed.path).strip("/").split("/")
                    if parsed.hostname not in {"www.last.fm","last.fm"} or len(parts)!=3 or parts[0]!="music" or parts[-1]!="+tags" or normalize(parts[1])!=normalize(artist):return result
                    chunks=[];size=0
                    for block in r.iter_content(65536):
                        size+=len(block)
                        if size>1000000:return result
                        chunks.append(block)
                    parser=TagParser();parser.feed(b"".join(chunks).decode("utf-8",errors="replace"))
                    result["tags"]=list(dict.fromkeys(parser.tags))[:40]
        except requests.RequestException:return result
        try:path.write_text(json.dumps(result,ensure_ascii=False),encoding="utf-8")
        except OSError:pass
        return result
