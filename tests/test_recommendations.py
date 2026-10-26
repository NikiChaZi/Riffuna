import json
import pytest
import requests
from musicdesk.models import Track
from musicdesk.recommendations import RecommendationClient,RecommendationError,Suggestion,resolve_suggestion

def test_resolver_preserves_artist_and_recording_edition():
    target=Suggestion("catalog1","A Song","Artist")
    class Source:
        def search(self,*args,**kwargs):return [Track("aaaaaaaaaaa","A Song (Slowed)","Artist"),Track("bbbbbbbbbbb","A Song","Cover Artist"),Track("ccccccccccc","A Song","Artist")]
    assert resolve_suggestion(Source(),target).video_id=="ccccccccccc"
    with pytest.raises(RecommendationError):resolve_suggestion(Source(),Suggestion("id","Other Song","Artist"))

def test_client_refuses_movie_service_and_never_turns_metadata_into_fake_tracks():
    class Response:
        def __init__(self,data):self.data=data
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def raise_for_status(self):pass
        def iter_content(self,*args):yield json.dumps(self.data).encode()
    class Session:
        data={"domain":"movies","schema":1,"items":[]}
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,*args,**kwargs):return Response(self.data)
    client=RecommendationClient(Session)
    with pytest.raises(RecommendationError,match="музыкальной"):client.recommend([])
    Session.data={"domain":"music","schema":1,"status":"ok","items":[{"id":"catalog1","title":"Song","artist":"Artist","genres":["pop"]},{"id":"catalog1","title":"duplicate","artist":"Artist"},{"id":"bad","title":"","artist":"Artist"}]}
    result=client.recommend([])
    assert result["items"]==[Suggestion("catalog1","Song","Artist",("pop",))]

def test_connection_failure_uses_same_trained_embedded_engine(monkeypatch):
    class Session:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,*args,**kwargs):raise requests.ConnectionError()
    client=RecommendationClient(Session);seen=[]
    def embedded(seeds,excluded):
        seen.append((seeds,excluded));return dict(domain="music",schema=1,status="insufficient_catalog_coverage",items=[])
    monkeypatch.setattr(client,"_embedded",embedded)
    client.recommend([Track("aaaaaaaaaaa","Song","Artist")])
    assert seen[0][0]==[{"title":"Song","artist":"Artist"}]
