"""Reproducible whole-user cohort; all catalog eligibility uses tower training only."""
from pathlib import Path
import ast, bz2, csv, json, time
from collections import Counter,defaultdict
import numpy as np
from .features import content_features

def prepare(root,modulo=23,seed=42):
    raw=root/"raw"; output=root/"prepared";output.mkdir(parents=True,exist_ok=True)
    if (output/"data.npz").exists():return output
    metadata={}
    with (raw/"id_information.csv").open(encoding="utf-8") as f:
        for row in csv.DictReader(f,delimiter="\t"):metadata[row["id"]]=row
    users=defaultdict(dict);rows=0;start=time.monotonic()
    with bz2.open(raw/"userid_trackid_count.tsv.bz2","rt",encoding="utf-8") as f:
        next(f)
        for line in f:
            uid,tid,count=line.rstrip().split("\t");rows+=1
            if int(uid)%modulo==0 and tid in metadata and int(count)>0:users[int(uid)][tid]=int(count)
            if rows%5000000==0:print("scan",rows,"cohort users",len(users),"seconds",round(time.monotonic()-start),flush=True)
    rng=np.random.default_rng(seed);splits={};support=Counter()
    for uid,records in sorted(users.items()):
        items=sorted(records)
        if len(items)<12:continue
        rng.shuffle(items);n=max(1,min(5,len(items)//10))
        test=items[:n];rank=items[n:2*n];train=items[2*n:]
        splits[uid]=(train,rank,test)
        support.update(train)
    # Supported track catalog is learned only from tower training interactions.
    ids=sorted(tid for tid,n in support.items() if n>=3);mapping={tid:i for i,tid in enumerate(ids)}
    with bz2.open(raw/"id_genres_tf-idf.tsv.bz2","rt",encoding="utf-8") as f:
        reader=csv.reader(f,delimiter="\t");header=next(reader)[1:]
        genres={row[0]:np.asarray(row[1:],dtype=np.float32) for row in reader if row[0] in mapping}
    (output/"genre_names.json").write_text(json.dumps(header),encoding="utf-8")
    artists={name:i for i,name in enumerate(sorted({metadata[t]["artist"] for t in ids}))}
    catalog=[dict(id=t,artist=metadata[t]["artist"],title=metadata[t]["song"],album=metadata[t]["album_name"],
                 genres=[header[j] for j,x in enumerate(genres.get(t,[])) if x>0]) for t in ids]
    x=np.stack([content_features(c["artist"],c["title"],genres.get(c["id"],np.zeros(len(header)))) for c in catalog])
    trains=[];ranks=[];tests=[];u_ids=[]
    for uid,(train,rank,test) in splits.items():
        tr=[mapping[t] for t in train if t in mapping];va=[mapping[t] for t in rank if t in mapping];te=[mapping[t] for t in test if t in mapping]
        if len(tr)>=8 and va and te:
            u_ids.append(uid);trains.append(tr);ranks.append(va);tests.append(te)
    def packed(rows):
        offsets=np.cumsum([0]+[len(row) for row in rows]);return np.concatenate(rows).astype(np.int32),offsets
    tr,tri=packed(trains);va,vai=packed(ranks);te,tei=packed(tests)
    pop=np.bincount(tr,minlength=len(ids)).astype(np.float32)
    np.savez_compressed(output/"data.npz",features=x,artist_codes=np.array([artists[c["artist"]] for c in catalog]),
       train=tr,train_offsets=tri,rank=va,rank_offsets=vai,test=te,test_offsets=tei,popularity=pop,user_ids=np.array(u_ids),genre_dim=len(header))
    (output/"catalog.json").write_text(json.dumps(catalog,ensure_ascii=False),encoding="utf-8")
    manifest=dict(dataset="Music4All-Onion",doi="10.5281/zenodo.15394646",license="CC-BY-4.0",
       metadata_mirror="https://huggingface.co/datasets/Leon299/music4all/tree/c409d02",seed=seed,
       protocol="Deterministic whole users uid % modulo == 0; random disjoint per-user train/ranker/test. Aggregate counts have no chronology; this is not a temporal evaluation.",
       modulo=modulo,scanned_rows=rows,users=len(u_ids),tracks=len(ids),train_pairs=len(tr),rank_pairs=len(va),test_pairs=len(te),genre_dim=len(header))
    (output/"manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    print(json.dumps(manifest),flush=True);return output
