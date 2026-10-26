"""Local music-model client. Candidates remain metadata until a real upload matches."""
from __future__ import annotations
from dataclasses import dataclass
from difflib import SequenceMatcher
import re,unicodedata
import requests
from .recording_versions import _profile

class RecommendationError(RuntimeError):pass
@dataclass(frozen=True)
class Suggestion:
    catalog_id:str
    title:str
    artist:str
    genres:tuple[str,...]=()

def normal(text):
    return " ".join(re.findall(r"[^\W_]+",unicodedata.normalize("NFKC",text).casefold().replace("ё","е")))

class RecommendationClient:
    def __init__(self,session_factory=requests.Session):
        self.session_factory=session_factory;self._engine=None
    def _embedded(self,seeds,excluded):
        from pathlib import Path
        from .storage import data_directory
        base=Path(__file__).resolve().parents[1]
        directory=base/"music-model"
        if not (directory/"manifest.json").is_file():directory=base/".test-data"/"music-training"/"model"
        if not (directory/"manifest.json").is_file():raise RecommendationError("Музыкальная модель ещё не установлена")
        if self._engine is None:
            from riffuna_recsys.engine import MusicEngine
            self._engine=MusicEngine(directory,cache_directory=data_directory()/"artist-tags")
        data=self._engine.recommend(seeds,excluded,25);data.update(domain="music",schema=1)
        return data
    def recommend(self,seeds,excluded=()):
        payload=dict(seeds=[dict(title=t.title,artist=t.artist) for t in seeds[:100]],
                     excluded=[dict(title=t.title,artist=t.artist) for t in excluded[:500]],limit=25)
        try:
            with self.session_factory() as session:
                with session.post("http://127.0.0.1:8766/recommend",json=payload,timeout=(.3,25),stream=True) as response:
                    response.raise_for_status();chunks=[];size=0
                    for chunk in response.iter_content(65536):
                        size+=len(chunk)
                        if size>1000000:raise RecommendationError("Сервис вернул слишком большой ответ")
                        chunks.append(chunk)
                    import json
                    data=json.loads(b"".join(chunks))
        except requests.ConnectionError:
            data=self._embedded(payload["seeds"],payload["excluded"])
        except (requests.RequestException,ValueError) as error:
            raise RecommendationError("Музыкальный сервис недоступен. Проверь, запущена ли обученная модель Riffuna.") from error
        if not isinstance(data,dict) or data.get("domain")!="music" or data.get("schema")!=1:
            raise RecommendationError("Подключённый сервис не является музыкальной моделью Riffuna")
        result=[];seen=set()
        for row in data.get("items",[])[:50]:
            if not isinstance(row,dict):continue
            key=row.get("id");title=row.get("title");artist=row.get("artist")
            if not all(isinstance(t,str) and 0<len(t)<=500 for t in (key,title,artist)) or key in seen:continue
            seen.add(key);genres=tuple(g for g in row.get("genres",[])[:20] if isinstance(g,str) and len(g)<100)
            result.append(Suggestion(key,title,artist,genres))
        return dict(status=data.get("status","error"),items=result,coverage=data.get("coverage",{}),model=data.get("model",""))

def resolve_suggestion(source,suggestion):
    found=source.search(suggestion.artist+" "+suggestion.title,limit=12,order="relevance")
    target=normal(suggestion.title);artist=normal(suggestion.artist);accepted=[]
    for track in found:
        name=normal(track.title);author=normal(re.sub(r"\s*[-–—]\s*Topic$","",track.artist,flags=re.I))
        if name.startswith(artist+" "):name=name[len(artist)+1:]
        score=SequenceMatcher(None,name,target).ratio()
        if score>=.9 and author==artist and _profile(track.title)==_profile(suggestion.title):accepted.append((score,track))
    if not accepted:raise RecommendationError("Подходящая музыкальная запись не найдена. Можно поискать её вручную.")
    return max(accepted,key=lambda item:item[0])[1]
