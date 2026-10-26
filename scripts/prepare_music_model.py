"""Stage a strict model-file allowlist; never bundle metadata caches or user data."""
import hashlib,json,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
NAMES=("manifest.json","genre_names.json","catalog.json","catalog_vectors.npz","user_tower.npz","ranker.json")
def main():
    source=ROOT/".test-data"/"music-training"/"model";target=ROOT/"build"/"music-model"
    manifest=json.loads((source/"manifest.json").read_text(encoding="utf-8"))
    if manifest.get("domain")!="music":raise ValueError("Not a music model")
    target.mkdir(parents=True,exist_ok=True)
    # Only allowlisted files are ever added here; reject a polluted staging folder.
    if set(p.name for p in target.iterdir())-set(NAMES)-{"SHA256SUMS.json","ATTRIBUTION.json"}:raise ValueError("Unexpected file in model stage")
    for name in NAMES:shutil.copy2(source/name,target/name)
    hashes={name:hashlib.sha256((target/name).read_bytes()).hexdigest() for name in NAMES}
    (target/"SHA256SUMS.json").write_text(json.dumps(hashes,indent=2),encoding="utf-8")
    record=json.loads((ROOT/".test-data"/"music-training"/"raw"/"zenodo-record.json").read_text(encoding="utf-8"))
    attribution=dict(title=record["metadata"]["title"],creators=record["metadata"]["creators"],doi=manifest["doi"],license=manifest["license"],metadata_mirror=manifest["metadata_mirror"],changes="Subset preparation, model training, and numerical model exports; metadata retained for matching.")
    (target/"ATTRIBUTION.json").write_text(json.dumps(attribution,ensure_ascii=False,indent=2),encoding="utf-8")
    print("Staged",len(NAMES),"music model files")
if __name__=="__main__":main()
