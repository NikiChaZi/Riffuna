from __future__ import annotations
import hashlib, re, unicodedata
import numpy as np

def normalize(text):
    return " ".join(re.findall(r"[^\W_]+",unicodedata.normalize("NFKC",str(text)).casefold().replace("ё","е")))

def bucket(text,size):
    return int.from_bytes(hashlib.blake2b(text.encode(),digest_size=8).digest(),"little")%size

def content_features(artist,title,genres):
    artist_vector=np.zeros(128,dtype=np.float32)
    artist_vector[bucket(normalize(artist),128)]=.5
    title_vector=np.zeros(128,dtype=np.float32)
    for token in set(normalize(title).split()):title_vector[bucket(token,128)]+=.2
    genre=np.asarray(genres,dtype=np.float32)
    genre=genre/max(float(np.linalg.norm(genre)),1e-8)
    return np.concatenate((genre,artist_vector,title_vector)).astype(np.float32)

def rank_features(profile,indices,features,vectors,query,popularity,artist_codes,history,genre_dim,*,context_features=None,artist_affinity=None):
    indices=np.asarray(indices,dtype=np.int64)
    history=np.asarray(history,dtype=np.int64)
    genre=profile[:genre_dim]; item=features[indices]
    counts=np.bincount(artist_codes[history],minlength=int(artist_codes.max())+1)
    affinity=counts[artist_codes[indices]]/max(1,len(history)) if artist_affinity is None else artist_affinity
    history_genres=features[history,:genre_dim] if context_features is None else np.asarray(context_features)[:,:genre_dim]
    max_genre=(item[:,:genre_dim]@history_genres.T).max(axis=1) if len(history_genres) else np.zeros(len(indices))
    return np.column_stack((vectors[indices]@query,item[:,:genre_dim]@genre,
       affinity,np.log1p(popularity[indices]),np.full(len(indices),np.log1p(len(history) if context_features is None else len(context_features))),
       np.count_nonzero(item[:,:genre_dim],axis=1),max_genre,
       np.sum(item*profile,axis=1))).astype(np.float32)
