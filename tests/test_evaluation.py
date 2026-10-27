import json
import sqlite3

import numpy as np
import pytest

from riffuna_recsys.evaluation import confidence, library_coverage, metrics, topk, validate_partitions
from riffuna_recsys.portable_tower import query


def test_topk_has_stable_ties_and_excludes_seen_and_nonfinite_scores():
    assert topk([3, 3, 3, np.nan, -np.inf], 2, excluded=[0]).tolist() == [1, 2]
    assert topk([1, 2], 10, excluded=[1]).tolist() == [0]
    assert topk([np.nan], 20).size == 0
    np.testing.assert_array_equal(metrics([1, 2], [1, 2]), [1, 1])
    with pytest.raises(ValueError):
        metrics([1, 1], [1])


def test_disjoint_protocol_rejects_leakage_duplicates_and_bad_ids():
    validate_partitions([[0, 1]], [[2]], [[3]], 4)
    for history, rank, test in [([0], [1], [0]), ([0, 0], [1], [2]), ([0], [1], [4])]:
        with pytest.raises(ValueError):
            validate_partitions([history], [rank], [test], 4)


def test_paired_bootstrap_uses_same_users_and_seeds_for_both_models():
    data = np.arange(24, dtype=float).reshape(3, 4, 2) / 100
    assert confidence(data, samples=100) == confidence(data, samples=100)
    zero = confidence(data - data, samples=100)
    assert zero["recall_at_20"] == {"mean": 0.0, "ci95": [0.0, 0.0]}
    assert zero["ndcg_at_20"]["ci95"] == [0.0, 0.0]
    with pytest.raises(ValueError):
        confidence(np.array([np.nan]))


def test_coverage_reads_local_metadata_and_returns_only_aggregate_counts(tmp_path):
    database = tmp_path / "library.sqlite3"
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE tracks(video_id TEXT,title TEXT,artist TEXT)")
        db.execute("CREATE TABLE likes(video_id TEXT)")
        db.executemany("INSERT INTO tracks VALUES(?,?,?)", [("a", "Known - Exact", "Known"), ("b", "Other", "Known"), ("c", "Song", "Missing")])
        db.executemany("INSERT INTO likes VALUES(?)", [("a",), ("b",), ("c",)])
    report = library_coverage(database, [{"title": "Exact", "artist": "Known"}])
    assert report == {"likes": 3, "track_match": 1, "artist_only": 1, "artist_absent": 1, "network_genre_fallback": "not_requested"}
    assert "Known" not in json.dumps(report)


def test_portable_tower_handles_zero_profiles_and_normalizes_nonzero_output():
    weights = {"layers.0.weight": np.eye(2, dtype=np.float32), "layers.0.bias": np.zeros(2), "layers.1.weight": np.ones(2), "layers.1.bias": np.zeros(2), "layers.3.weight": np.eye(2), "layers.3.bias": np.zeros(2)}
    np.testing.assert_allclose(query(np.array([1, -1]), weights), [1, 0])
    np.testing.assert_array_equal(query(np.zeros(2), weights), [0, 0])


def test_actual_als_api_uses_user_rows_and_item_columns():
    from implicit.als import AlternatingLeastSquares
    from scipy.sparse import csr_matrix
    from threadpoolctl import threadpool_limits

    train = csr_matrix(np.array([[1, 1, 0, 0], [0, 1, 1, 0], [0, 0, 1, 1]], dtype=np.float32))
    with threadpool_limits(limits=1, user_api="blas"):
        model = AlternatingLeastSquares(factors=2, iterations=5, random_state=42, use_gpu=False, num_threads=1)
        model.fit(train, show_progress=False)
    assert model.user_factors.shape == (3, 2)
    assert model.item_factors.shape == (4, 2)
    ids = topk(model.item_factors @ model.user_factors[0], excluded=[0, 1])
    assert set(ids.tolist()) == {2, 3}
