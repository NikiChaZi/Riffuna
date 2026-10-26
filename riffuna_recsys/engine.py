"""Inference never imports MovieLens weights or requires a training user ID."""
from __future__ import annotations
import json,os,hashlib
from pathlib import Path
from difflib import SequenceMatcher
from collections import defaultdict
import numpy as np
from .portable_ranker import PortableRanker
from .features import normalize,rank_features,content_features
from .metadata import ArtistTags
from concurrent.futures import ThreadPoolExecutor

class MusicEngine:
    def __init__(self,directory,*,genre_provider=None,cache_directory=None):
        self.directory=Path(directory)
        self.manifest=json.loads((self.directory/"manifest.json").read_text(encoding="utf-8"))
        if self.manifest.get("domain")!="music" or self.manifest.get("schema")!=1:raise ValueError("Not a supported music model")
        self.catalog=json.loads((self.directory/"catalog.json").read_text(encoding="utf-8"))
        d=np.load(self.directory/"catalog_vectors.npz")
        self.x=d["features"];self.vectors=d["vectors"];self.pop=d["popularity"];self.artists=d["artist_codes"];self.gd=int(d["genre_dim"])
        if len(self.catalog)!=len(self.x) or len(self.x)!=len(self.vectors):raise ValueError("Catalog/model IDs do not align")
        self.genre_names=json.loads((self.directory/"genre_names.json").read_text(encoding="utf-8"))
        self.genre_index={normalize(name):i for i,name in enumerate(self.genre_names)}
        self.genre_provider=genre_provider if genre_provider is not None else ArtistTags(cache_directory or self.directory/"metadata-cache")
        self.tower=dict(np.load(self.directory/"user_tower.npz"))
        self.ranker=PortableRanker(self.directory/"ranker.json")
        self.exact={};self.by_artist=defaultdict(list)
        for i,t in enumerate(self.catalog):
            artist=normalize(t["artist"]);self.exact[(artist,normalize(t["title"]))]=i;self.by_artist[artist].append(i)
        self.model_id=hashlib.sha256((self.directory/"catalog_vectors.npz").read_bytes()+(self.directory/"user_tower.npz").read_bytes()).hexdigest()[:16]
        self.collection="riffuna_music_"+self.model_id
        self.qdrant=None
        if os.environ.get("RIFFUNA_QDRANT_URL"):
            from qdrant_client import QdrantClient,models
            self.qdrant=QdrantClient(url=os.environ["RIFFUNA_QDRANT_URL"],timeout=5)
            name=self.collection
            if not self.qdrant.collection_exists(name):
                self.qdrant.create_collection(name,vectors_config=models.VectorParams(size=64,distance=models.Distance.COSINE))
                for start in range(0,len(self.vectors),512):
                    self.qdrant.upsert(name,points=[models.PointStruct(id=i,vector=self.vectors[i].tolist(),payload={"domain":"music","track_id":self.catalog[i]["id"]}) for i in range(start,min(start+512,len(self.vectors)))])
    def _query(self,profile):
        w=self.tower
        value=profile@w["layers.0.weight"].T+w["layers.0.bias"]
        value=(value-value.mean())/np.sqrt(value.var()+1e-5)
        value=value*w["layers.1.weight"]+w["layers.1.bias"]
        value=np.maximum(value,0)@w["layers.3.weight"].T+w["layers.3.bias"]
        return value/max(float(np.linalg.norm(value)),1e-8)
    def match(self,seed):
        artist=normalize(seed.get("artist",""));title=normalize(seed.get("title",""))
        # yt-dlp titles often include an exact artist prefix; strip only that prefix.
        if title.startswith(artist+" "):title=title[len(artist)+1:]
        exact=self.exact.get((artist,title))
        if exact is not None:return [exact],"track"
        same=self.by_artist.get(artist,[])
        close=[i for i in same if SequenceMatcher(None,title,normalize(self.catalog[i]["title"])).ratio()>=.92]
        if close:return close[:1],"track"
        return same,"artist" if same else "missing"
    def recommend(self,seeds,excluded=(),limit=25):
        history=[];coverage={"track":0,"artist":0,"genre":0,"missing":0};profiles=[];evidence=[]
        unknown=list(dict.fromkeys(seed.get("artist","") for seed in seeds[:100] if self.match(seed)[1]=="missing"))[:6]
        tags={}
        if self.genre_provider and unknown:
            with ThreadPoolExecutor(max_workers=3) as pool:
                tags=dict(zip(unknown,pool.map(self.genre_provider.fetch,unknown)))
        for seed in seeds[:100]:
            ids,kind=self.match(seed)
            if ids:
                if kind=="track":history.extend(ids)
                profiles.append(self.x[ids].mean(axis=0))
            else:
                record=tags.get(seed.get("artist"),{});genre=np.zeros(self.gd,dtype=np.float32);names=[]
                for tag in record.get("tags",[]):
                    column=self.genre_index.get(normalize(tag))
                    if column is not None:genre[column]=1.;names.append(self.genre_names[column])
                if names:
                    profiles.append(content_features(seed["artist"],seed["title"],genre));kind="genre"
                    evidence.append(dict(artist=seed["artist"],genres=names,source=record.get("source"),source_url=record.get("source_url"),scope="artist"))
            coverage[kind]+=1
        if not profiles:return dict(status="insufficient_catalog_coverage",items=[],coverage=coverage,model=self.manifest["model"])
        history=np.unique(history);profile=np.stack(profiles).mean(axis=0);query=self._query(profile)
        exclude=set(history.tolist())
        for seed in excluded[:500]:
            ids,kind=self.match(seed)
            if kind=="track":exclude.update(ids)
        if self.qdrant is not None:
            from qdrant_client import models
            hits=self.qdrant.query_points(self.collection,query=query.tolist(),limit=min(len(self.catalog),200+len(exclude)),query_filter=models.Filter(must_not=[models.HasIdCondition(has_id=sorted(exclude))])).points
            indices=np.array([int(h.id) for h in hits[:200]],dtype=np.int64)
        else:
            score=self.vectors@query;score[list(exclude)]=-np.inf
            n=min(200,len(score)-len(exclude))
            if n<=0:return dict(status="empty",items=[],coverage=coverage)
            indices=np.argpartition(score,-n)[-n:];indices=indices[np.argsort(-score[indices])]
        if not len(indices):return dict(status="empty",items=[],coverage=coverage)
        artist_names=[normalize(seed.get("artist","")) for seed in seeds[:100]]
        affinity=np.array([artist_names.count(normalize(self.catalog[int(i)]["artist"]))/max(1,len(artist_names)) for i in indices])
        features=rank_features(profile,indices,self.x,self.vectors,query,self.pop,self.artists,history,self.gd,context_features=profiles,artist_affinity=affinity)
        indices=indices[np.argsort(-self.ranker.predict(features))]
        items=[];artist_count=defaultdict(int)
        for i in indices:
            item=self.catalog[int(i)]
            if artist_count[item["artist"]]>=3:continue
            items.append(item);artist_count[item["artist"]]+=1
            if len(items)>=max(1,min(50,limit)):break
        return dict(status="ok",items=items,coverage=coverage,genre_evidence=evidence,model=self.manifest["model"],retrieval="qdrant" if self.qdrant is not None else "numpy_exact")
