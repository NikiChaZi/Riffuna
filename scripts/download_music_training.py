"""Download only public metadata/interactions; no music or lyrics files."""
from pathlib import Path
import concurrent.futures, hashlib, json, time
import requests
ROOT=Path(__file__).resolve().parents[1]/".test-data"/"music-training"/"raw"
RECORD="https://zenodo.org/api/records/15394646"

def save(name,url,checksum=None):
    path=ROOT/name
    if path.exists():
        if checksum and hashlib.md5(path.read_bytes()).hexdigest()!=checksum: raise ValueError("Checksum mismatch: "+name)
        print("cached",name,flush=True); return
    part=path.with_suffix(path.suffix+".part")
    md5=hashlib.md5(); size=0; last=time.monotonic()
    with requests.get(url,stream=True,timeout=(10,90)) as response:
        response.raise_for_status()
        with part.open("wb") as target:
            for block in response.iter_content(1024*1024):
                size+=len(block); md5.update(block);target.write(block)
                if time.monotonic()-last>15:
                    print(name,round(size/1e6,1),"MB",flush=True);last=time.monotonic()
    if checksum and md5.hexdigest()!=checksum: raise ValueError("Checksum mismatch: "+name)
    part.replace(path);print("saved",name,size,flush=True)

def main():
    ROOT.mkdir(parents=True,exist_ok=True)
    response=requests.get(RECORD,timeout=30);response.raise_for_status();record=response.json()
    (ROOT/"zenodo-record.json").write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding="utf-8")
    names={"userid_trackid_count.tsv.bz2","id_genres_tf-idf.tsv.bz2","id_tags_dict.tsv.bz2"}
    jobs=[(f["key"],f["links"]["self"],f["checksum"].split(":")[-1]) for f in record["files"] if f["key"] in names]
    # Metadata mirror of the base Music4All CSV; provenance is kept separately.
    jobs.append(("id_information.csv","https://huggingface.co/datasets/Leon299/music4all/resolve/c409d02/id_information.csv",None))
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        for result in pool.map(lambda args:save(*args),jobs): pass
if __name__=="__main__":main()
