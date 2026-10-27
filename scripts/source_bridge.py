"""Bounded local extraction protocol. No UI, HTTP listener, user DB or audio engine."""
import json,sys
sys.stdout.reconfigure(encoding="utf-8",newline="\n")
from dataclasses import asdict
from pathlib import Path

from musicdesk.models import Track
from musicdesk.youtube import YouTubeSource


source=YouTubeSource()
from musicdesk.stream_cache import StreamCache
from musicdesk.disk_cache import DiskAudioCache
from musicdesk.audio_buffer import AudioBuffers
streams=StreamCache(source.resolve)
buffers={}


def main(raw):
    if len(raw)>65536:raise ValueError("Request too large")
    request=json.loads(raw)
    kind=request.get("action")
    if kind=="capabilities":
        result={"qt_loaded":any(name.startswith("PySide") for name in sys.modules),"protocol":1,"actions":["search","resolve","lyrics","recommend"]}
    elif kind=="search":
        query=request.get("query","")
        if not isinstance(query,str) or not 0<len(query.strip())<=500:raise ValueError("Invalid query")
        result={"tracks":[asdict(track) for track in source.search(query,limit=min(120,max(1,int(request.get("limit",40)))))]}
    elif kind=="resolve":
        record=request["track"]
        track=Track(record["id"],record["title"],record.get("artist","YouTube"),record.get("duration",0),record.get("thumbnail",""))
        directory=request.get("cache_directory")
        cached=None
        cache=None
        if directory:
            cache=DiskAudioCache(Path(directory))
            cached=cache.get(track.video_id)
        if cached is not None:
            result={"uri":cached.as_uri(),"headers":{}}
        else:
            stream=streams.resolve(track)
            if cache is not None:
                buffer=buffers.get(directory)
                if buffer is None:
                    buffer=buffers[directory]=AudioBuffers(disk_cache=cache)
                buffer.prepare(stream)
            from urllib.request import getproxies
            proxy=getproxies().get("https","")
            result={"uri":stream.url,"headers":stream.headers,"proxy":proxy}
    elif kind=="lyrics":
        from musicdesk.lyrics import LyricsStore
        record=request["track"]
        track=Track(record["id"],record["title"],record.get("artist","YouTube"),record.get("duration",0),record.get("thumbnail",""))
        directory=Path(request["cache_directory"])
        result=LyricsStore(directory).load(track)
    elif kind=="resolve_suggestion":
        from musicdesk.recommendations import Suggestion,resolve_suggestion
        row=request["suggestion"]
        result={"track":asdict(resolve_suggestion(source,Suggestion(row["catalogId"],row["title"],row["artist"])))}
    elif kind=="recommend":
        from musicdesk.recommendations import RecommendationClient
        def tracks(values):
            return [Track(row["id"],row["title"],row.get("artist","YouTube"),row.get("duration",0),row.get("thumbnail","")) for row in values[:100]]
        value=RecommendationClient().recommend(tracks(request.get("seeds",[])),tracks(request.get("excluded",[])))
        result={**value,"items":[asdict(item) for item in value["items"]]}
    else:raise ValueError("Unknown action")
    sys.stdout.write(json.dumps({"ok":True,"result":result},ensure_ascii=False)+"\n");sys.stdout.flush()

if __name__=="__main__":
    while True:
        raw=sys.stdin.buffer.readline(65537)
        if not raw:break
        if len(raw)>65536:break
        try:main(raw)
        except Exception as error:
            sys.stdout.write(json.dumps({"ok":False,"error":type(error).__name__})+"\n");sys.stdout.flush()
