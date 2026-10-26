"""Loopback-only serving. External hosting requires separate authentication."""
import argparse,hashlib,json,os
from pathlib import Path
from fastapi import FastAPI
from pydantic import BaseModel,Field
from .engine import MusicEngine

def create_app(directory):
    engine=MusicEngine(directory);app=FastAPI(title="Riffuna Music Recsys")
    cache=None
    if os.environ.get("RIFFUNA_REDIS_URL"):
        import redis
        cache=redis.Redis.from_url(os.environ["RIFFUNA_REDIS_URL"],socket_timeout=.5,socket_connect_timeout=.5)
    class Seed(BaseModel):
        artist:str=Field(max_length=300)
        title:str=Field(max_length=500)
    class Request(BaseModel):
        seeds:list[Seed]=Field(max_length=100)
        excluded:list[Seed]=Field(default_factory=list,max_length=500)
        limit:int=Field(default=25,ge=1,le=50)
    @app.get("/health")
    def health():
        return dict(status="ok",domain="music",schema=1,model=engine.manifest["model"],tracks=len(engine.catalog),metrics=engine.manifest["metrics"])
    @app.post("/recommend")
    def recommend(request:Request):
        body=request.model_dump();key="riffuna:music:"+engine.model_id+":"+hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest()
        if cache:
            try:
                found=cache.get(key)
                if found:return json.loads(found)
            except Exception:pass
        result=engine.recommend(body["seeds"],body["excluded"],body["limit"])
        result.update(domain="music",schema=1)
        if cache:
            try:cache.setex(key,300,json.dumps(result))
            except Exception:pass
        return result
    return app

def main():
    parser=argparse.ArgumentParser();parser.add_argument("--model-dir",type=Path,default=Path(".test-data/music-training/model"));parser.add_argument("--port",type=int,default=8766)
    args=parser.parse_args();import uvicorn
    uvicorn.run(create_app(args.model_dir),host="127.0.0.1",port=args.port,log_level="warning")
if __name__=="__main__":main()
