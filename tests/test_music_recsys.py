import json
import numpy as np
import pytest
from riffuna_recsys.portable_ranker import PortableRanker
from riffuna_recsys.features import rank_features,normalize
from riffuna_recsys.metadata import TagParser,ArtistTags

def test_exported_symmetric_tree_bit_order_thresholds_scale_bias(tmp_path):
    path=tmp_path/"ranker.json"
    path.write_text(json.dumps({"scale_and_bias":[2,[.5]],"features_info":{"float_features":[{},{}]},"oblivious_trees":[{"splits":[{"split_type":"FloatFeature","float_feature_index":0,"border":1},{"split_type":"FloatFeature","float_feature_index":1,"border":2}],"leaf_values":[1,2,3,4]}]}))
    model=PortableRanker(path)
    np.testing.assert_array_equal(model.predict([[1,2],[2,2],[1,3],[2,3]]),[2.5,4.5,6.5,8.5])
    with pytest.raises(ValueError):model.predict([[float("nan"),0]])

def test_genre_tags_are_observed_links_and_cache_does_not_invent_missing_data(tmp_path):
    parser=TagParser();parser.feed('<a href="/tag/pop">pop</a><a href="/music/Someone">Someone</a><a href="/tag/indie+pop">indie pop</a>')
    assert parser.tags==["pop","indie pop"]
    import hashlib
    key=hashlib.sha256(normalize("Artist").encode()).hexdigest()
    (tmp_path/(key+".json")).write_text(json.dumps({"artist":"Artist","tags":["pop"],"at":100}))
    provider=ArtistTags(tmp_path,session_factory=lambda:pytest.fail("cache must not use network"),clock=lambda:101)
    assert provider.fetch("Artist")["tags"]==["pop"]

def test_ranker_cold_start_uses_real_profile_without_fabricated_history_ids():
    x=np.array([[1,0,0],[0,1,0]],dtype=np.float32);vectors=np.eye(2,dtype=np.float32)
    xx=rank_features(np.array([1,0,0]),[0,1],x,vectors,np.array([1,0]),np.array([1,2]),np.array([0,1]),[],2,context_features=[x[0]],artist_affinity=np.array([0,0]))
    assert np.isfinite(xx).all()
    np.testing.assert_array_equal(xx[:,6],[1,0])
