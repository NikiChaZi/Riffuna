"""Train music towers and CatBoostRanker; evaluate genuine retrieved candidates."""
from __future__ import annotations
import argparse,json,random,time
from pathlib import Path
import numpy as np
import torch
from catboost import CatBoostRanker,Pool
from .prepare import prepare
from .model import MusicTwoTower
from .features import rank_features

def rows(data,name):
    values=data[name];offsets=data[name+"_offsets"]
    return [values[offsets[i]:offsets[i+1]] for i in range(len(offsets)-1)]

def metric(order,truth,k=20):
    hits=np.isin(order[:k],truth);n=min(k,len(truth))
    return float(hits.sum()/len(truth)),float(np.sum(hits/np.log2(np.arange(len(hits))+2))/np.sum(1/np.log2(np.arange(n)+2)))

def export_tower(tower):
    return {k:v.detach().cpu().numpy() for k,v in tower.state_dict().items()}

def train(root,epochs=5,*,seed=42,output=None):
    if epochs < 1 or seed < 0: raise ValueError("epochs must be positive and seed nonnegative")
    start=time.monotonic();prepared=prepare(root);artifact=Path(output) if output is not None else root/"model"
    if output is not None and artifact.exists() and any(artifact.iterdir()): raise ValueError("Refusing to overwrite an existing evaluation model")
    artifact.mkdir(parents=True,exist_ok=True)
    data=np.load(prepared/"data.npz");x=data["features"];gd=int(data["genre_dim"])
    histories=rows(data,"train");rank_targets=rows(data,"rank");tests=rows(data,"test")
    device="cuda" if torch.cuda.is_available() else "cpu"
    np.random.seed(seed);random.seed(seed);torch.manual_seed(seed);torch.set_num_threads(8)
    model=MusicTwoTower(x.shape[1]).to(device);features=torch.tensor(x,device=device)
    optim=torch.optim.AdamW(model.parameters(),lr=.001,weight_decay=.0001)
    rng=np.random.default_rng(seed);pairs=[]
    for u,h in enumerate(histories):
        pairs.extend((u,int(t)) for t in rng.choice(h,min(40,len(h)),replace=False))
    pairs=np.asarray(pairs);print("training",device,"pairs per epoch",len(pairs),"features",x.shape,flush=True)
    losses=[]
    for epoch in range(epochs):
        model.train();rng.shuffle(pairs);loss_sum=0.;batches=0
        for offset in range(0,len(pairs),512):
            batch=pairs[offset:offset+512];profiles=[];targets=batch[:,1]
            for u,t in batch:
                h=histories[u];h=h[h!=t]
                context=rng.choice(h,min(20,len(h)),replace=False)
                profiles.append(x[context].mean(axis=0))
            profile=torch.tensor(np.stack(profiles),device=device)
            ids=torch.tensor(targets,device=device)
            q,v=model(profile,features[ids]);logits=q@v.T/.07
            duplicate=ids[:,None]==ids[None,:];duplicate.fill_diagonal_(False)
            logits=logits.masked_fill(duplicate,-1e4)
            labels=torch.arange(len(batch),device=device)
            loss=(torch.nn.functional.cross_entropy(logits,labels)+torch.nn.functional.cross_entropy(logits.T,labels))/2
            optim.zero_grad();loss.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),5);optim.step()
            loss_sum+=float(loss.detach());batches+=1
        losses.append(loss_sum/batches);print("epoch",epoch+1,"loss",round(losses[-1],4),"seconds",round(time.monotonic()-start),flush=True)
    model.eval()
    with torch.no_grad():
        vectors=model.item_tower(features).cpu().numpy()
        profiles=np.stack([x[h].mean(axis=0) for h in histories])
        queries=model.user_tower(torch.tensor(profiles,device=device)).cpu().numpy()
    pop=data["popularity"];artists=data["artist_codes"]
    def candidates(u,n=100):
        score=vectors@queries[u];score[histories[u]]=-np.inf
        idx=np.argpartition(score,-n)[-n:];return idx[np.argsort(-score[idx])]
    # Ranker labels are a separate interaction partition, never tower training/test.
    ids=rng.permutation(len(histories));valid_users=set(ids[:max(1,len(ids)//5)].tolist())
    pools=[([],[],[]),([],[],[])]
    for u in range(len(histories)):
        idx=candidates(u)
        # Training pool includes positive ranker labels even if retrieval missed them.
        # Final test below never injects targets into retrieval.
        idx=np.unique(np.concatenate((idx,rank_targets[u])))
        xx=rank_features(profiles[u],idx,x,vectors,queries[u],pop,artists,histories[u],gd)
        pool=pools[int(u in valid_users)];pool[0].append(xx);pool[1].extend(np.isin(idx,rank_targets[u]).astype(int));pool[2].extend([u]*len(idx))
        if u%1000==0:print("ranker pools",u,"/",len(histories),flush=True)
    def to_pool(p):return Pool(np.concatenate(p[0]),np.array(p[1]),group_id=np.array(p[2]))
    ranker=CatBoostRanker(iterations=350,depth=6,learning_rate=.06,loss_function="YetiRank",eval_metric="NDCG:top=20",random_seed=seed,thread_count=8,verbose=100,allow_writing_files=False)
    ranker.fit(to_pool(pools[0]),eval_set=to_pool(pools[1]),early_stopping_rounds=60)
    totals={k:[] for k in ("popularity","genre_similarity","two_tower","two_stage")};recall100=[]
    eval_users=rng.choice(len(histories),min(1000,len(histories)),replace=False)
    for u in eval_users:
        idx=candidates(u,200);truth=tests[u]
        recall100.append(float(np.isin(idx[:100],truth).sum()/len(truth)))
        xx=rank_features(profiles[u],idx,x,vectors,queries[u],pop,artists,histories[u],gd)
        ranked=idx[np.argsort(-ranker.predict(xx))]
        baseline=pop.copy();baseline[histories[u]]=-1
        base=np.argpartition(baseline,-20)[-20:];base=base[np.argsort(-baseline[base])]
        gs=x[:,:gd]@profiles[u,:gd];gs[histories[u]]=-np.inf
        gi=np.argpartition(gs,-20)[-20:];gi=gi[np.argsort(-gs[gi])]
        for name,order in (("popularity",base),("genre_similarity",gi),("two_tower",idx),("two_stage",ranked)):
            totals[name].append(metric(order,truth))
    metrics={name:dict(recall_at_20=float(np.mean(values,axis=0)[0]),ndcg_at_20=float(np.mean(values,axis=0)[1])) for name,values in totals.items()}
    manifest=json.loads((prepared/"manifest.json").read_text(encoding="utf-8"))
    manifest.update(schema=1,domain="music",model="history-content-two-tower+CatBoostRanker",epochs=epochs,losses=losses,
       device=device,dimensions=64,training_seed=seed,metrics=metrics,retrieval_recall_at_100=float(np.mean(recall100)),evaluation_users=len(eval_users),
       ranker_pool_protocol="Ranker training injects held-out positives; test uses actual top-200 retrieval without injection.",
       seconds=round(time.monotonic()-start,1),limitations=["Aggregate counts split randomly, not chronologically","Missing modern artists require catalog enrichment; offline metrics are not a guarantee of personal taste"])
    (artifact/"genre_names.json").write_text((prepared/"genre_names.json").read_text(encoding="utf-8"),encoding="utf-8")
    torch.save(model.state_dict(),artifact/"two_tower.pt")
    np.savez_compressed(artifact/"user_tower.npz",**export_tower(model.user_tower))
    np.savez_compressed(artifact/"catalog_vectors.npz",features=x,vectors=vectors,popularity=pop,artist_codes=artists,genre_dim=gd)
    ranker.save_model(str(artifact/"ranker.cbm"));ranker.save_model(str(artifact/"ranker.json"),format="json")
    (artifact/"catalog.json").write_text((prepared/"catalog.json").read_text(encoding="utf-8"),encoding="utf-8")
    (artifact/"manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    print(json.dumps(manifest,indent=2),flush=True)

if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--root",type=Path,default=Path(".test-data/music-training"));parser.add_argument("--epochs",type=int,default=5)
    parser.add_argument("--seed",type=int,default=42);parser.add_argument("--output",type=Path)
    args=parser.parse_args();train(args.root,args.epochs,seed=args.seed,output=args.output)
