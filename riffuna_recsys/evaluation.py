"""Offline comparison on one fixed cohort; no audio, network or personal data uploads."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import time
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np

from .features import normalize, rank_features
from .portable_ranker import PortableRanker
from .portable_tower import query as user_query


def unpack(data, name):
    values, offsets = data[name], data[name + "_offsets"]
    return [values[offsets[i]:offsets[i + 1]] for i in range(len(offsets) - 1)]


def validate_partitions(histories, rank, targets, items):
    if not (len(histories) == len(rank) == len(targets)):
        raise ValueError("User partitions do not align")
    for history, labels, truth in zip(histories, rank, targets):
        groups = [set(map(int, row)) for row in (history, labels, truth)]
        if not groups[0] or not groups[2]:
            raise ValueError("History and test targets must be nonempty")
        if any(len(group) != len(row) for group, row in zip(groups, (history, labels, truth))):
            raise ValueError("Duplicate interaction inside a partition")
        if groups[0] & groups[1] or groups[0] & groups[2] or groups[1] & groups[2]:
            raise ValueError("Train/ranker/test leakage")
        if any(value < 0 or value >= items for group in groups for value in group):
            raise ValueError("Item outside the shared catalog")


def topk(scores, k=20, excluded=()):
    values = np.asarray(scores, dtype=np.float64).copy()
    values[np.asarray(excluded, dtype=np.int64)] = -np.inf
    valid = np.flatnonzero(np.isfinite(values))
    if k <= 0 or not len(valid):
        return np.empty(0, dtype=np.int64)
    k = min(k, len(valid))
    boundary = np.partition(values[valid], -k)[-k]
    better = valid[values[valid] > boundary]
    ties = valid[values[valid] == boundary][:k - len(better)]
    selected = np.concatenate((better, ties))
    return selected[np.lexsort((selected, -values[selected]))]


def metrics(order, truth, k=20):
    if not len(truth):
        raise ValueError("Empty evaluation target")
    selected = np.asarray(order)[:k]
    if len(np.unique(selected)) != len(selected):
        raise ValueError("Duplicate recommended item")
    hits = np.isin(selected, truth)
    ideal = np.sum(1 / np.log2(np.arange(min(k, len(truth))) + 2))
    return np.array([hits.sum() / len(truth), np.sum(hits / np.log2(np.arange(len(hits)) + 2)) / ideal])


def confidence(values, seed=2026, samples=2000):
    """Hierarchical bootstrap over training seeds and the same sampled users."""
    values = np.asarray(values, dtype=np.float64)
    if samples < 1 or values.ndim != 3 or not values.shape[0] or not values.shape[1] or not np.isfinite(values).all():
        raise ValueError("Expected finite [training seed, user, metric] values")
    rng = np.random.default_rng(seed)
    means = []
    for _ in range(samples):
        seeds = rng.integers(values.shape[0], size=values.shape[0])
        users = rng.integers(values.shape[1], size=values.shape[1])
        means.append(values[seeds][:, users].mean(axis=(0, 1)))
    intervals = np.percentile(means, [2.5, 97.5], axis=0)
    average = values.mean(axis=(0, 1))
    return {name: {"mean": float(average[i]), "ci95": intervals[:, i].tolist()} for i, name in enumerate(("recall_at_20", "ndcg_at_20"))}


def wait_model(directory, timeout=1800):
    deadline = time.monotonic() + timeout
    announced = False
    while True:
        try:
            manifest = json.loads((directory / "manifest.json").read_text(encoding="utf8"))
            if manifest.get("domain") != "music" or manifest.get("schema") != 1:
                raise ValueError("Expected a music model")
            return manifest
        except (FileNotFoundError, json.JSONDecodeError):
            if time.monotonic() >= deadline:
                raise TimeoutError("Evaluation model did not become ready: " + directory.name)
            if not announced:
                print("Waiting for trained model:", directory.name, flush=True)
                announced = True
            time.sleep(5)


def library_coverage(database, catalog):
    exact = {(normalize(row["artist"]), normalize(row["title"])) for row in catalog}
    artists = {}
    for row in catalog:
        artists.setdefault(normalize(row["artist"]), []).append(normalize(row["title"]))
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as db:
        liked = db.execute("SELECT t.artist,t.title FROM likes l JOIN tracks t ON t.video_id=l.video_id").fetchall()
    result = {"likes": len(liked), "track_match": 0, "artist_only": 0, "artist_absent": 0, "network_genre_fallback": "not_requested"}
    for artist, title in liked:
        artist, title = normalize(artist), normalize(title)
        if title.startswith(artist + " "):
            title = title[len(artist) + 1:]
        same = artists.get(artist, [])
        matched = (artist, title) in exact or any(SequenceMatcher(None, title, candidate, autojunk=False).ratio() >= .92 for candidate in same)
        result["track_match" if matched else "artist_only" if same else "artist_absent"] += 1
    return result


def evaluate(root, models, seeds, output, count=1000, library=None):
    from scipy.sparse import csr_matrix
    from implicit.als import AlternatingLeastSquares
    from threadpoolctl import threadpool_limits

    prepared = root / "prepared"
    data = np.load(prepared / "data.npz", allow_pickle=False)
    x, genre_dim = data["features"], int(data["genre_dim"])
    histories, rank, targets = [unpack(data, key) for key in ("train", "rank", "test")]
    validate_partitions(histories, rank, targets, len(x))
    catalog = json.loads((prepared / "catalog.json").read_text(encoding="utf8"))
    users = np.random.default_rng(2026).choice(len(histories), min(count, len(histories)), replace=False)
    train = csr_matrix((np.ones(len(data["train"]), dtype=np.float32), data["train"], data["train_offsets"]), shape=(len(histories), len(x)))
    train.sort_indices()
    profiles = np.stack([x[histories[u]].mean(axis=0) for u in users])
    output.parent.mkdir(parents=True, exist_ok=True)
    results = {name: [] for name in ("popularity", "genre_similarity", "als", "two_tower", "two_stage")}
    run_info = []
    with threadpool_limits(limits=4):
        pop_scores, genre_scores = [], []
        for i, u in enumerate(users):
            pop_scores.append(metrics(topk(data["popularity"], excluded=histories[u]), targets[u]))
            genre_scores.append(metrics(topk(x[:, :genre_dim] @ profiles[i, :genre_dim], excluded=histories[u]), targets[u]))
        for seed in seeds:
            print("Fitting ALS seed", seed, flush=True)
            started = time.monotonic()
            with threadpool_limits(limits=1, user_api="blas"):
                als = AlternatingLeastSquares(factors=64, regularization=.1, alpha=20, iterations=15, random_state=seed, num_threads=4, use_gpu=False)
                als.fit(train, show_progress=False)
            scores = []
            for u in users:
                order = topk(als.item_factors @ als.user_factors[u], excluded=histories[u])
                scores.append(metrics(order, targets[u]))
            results["als"].append(scores)
            run_info.append({"training_seed": seed, "als_seconds": round(time.monotonic() - started, 2)})
            print("ALS finished", seed, "Recall@20", float(np.mean(scores, axis=0)[0]), flush=True)
        for directory in models:
            manifest = wait_model(directory)
            model_catalog = json.loads((directory / "catalog.json").read_text(encoding="utf8"))
            if [row["id"] for row in model_catalog] != [row["id"] for row in catalog]:
                raise ValueError("Model and evaluation catalog ordering differs")
            packed = np.load(directory / "catalog_vectors.npz", allow_pickle=False)
            if not np.array_equal(packed["features"], x):
                raise ValueError("Model features differ from the fixed evaluation split")
            vectors = packed["vectors"]
            tower = dict(np.load(directory / "user_tower.npz", allow_pickle=False))
            ranker = PortableRanker(directory / "ranker.json")
            tower_scores, ranker_scores = [], []
            print("Evaluating neural model", directory.name, flush=True)
            for i, u in enumerate(users):
                query = user_query(profiles[i], tower)
                candidates = topk(vectors @ query, 200, histories[u])
                features = rank_features(profiles[i], candidates, x, vectors, query, data["popularity"], data["artist_codes"], histories[u], genre_dim)
                ranked = candidates[np.lexsort((candidates, -ranker.predict(features)))]
                tower_scores.append(metrics(candidates, targets[u]))
                ranker_scores.append(metrics(ranked, targets[u]))
            results["two_tower"].append(tower_scores)
            results["two_stage"].append(ranker_scores)
            print("Neural finished", directory.name, "Recall@20", float(np.mean(ranker_scores, axis=0)[0]), flush=True)
        if len(models) != len(seeds):
            raise ValueError("Use the same number of neural and ALS training seeds")
        results["popularity"] = [pop_scores] * len(seeds)
        results["genre_similarity"] = [genre_scores] * len(seeds)
        arrays = {name: np.asarray(values) for name, values in results.items()}
        for i, directory in enumerate(models):
            actual = wait_model(directory).get("training_seed", 42)
            if actual != seeds[i]:
                raise ValueError("Training seed/model order mismatch")
        report = {
            "protocol": "Fixed random split and fixed user cohort. Train histories only for ALS/input/exclusion; CatBoost uses the disjoint ranker partition. Test targets are never injected into retrieval. No temporal or online claim.",
            "training_seeds": seeds,
            "cohort_seed": 2026,
            "evaluation_users": len(users),
            "catalog_tracks": len(x),
            "als": {"factors": 64, "regularization": .1, "alpha": 20, "iterations": 15},
            "retrieval_candidates": 200,
            "postprocessing": "Before artist caps and YouTube resolution",
            "data_sha256": hashlib.sha256((prepared / "data.npz").read_bytes()).hexdigest(),
            "metrics": {name: confidence(values) for name, values in arrays.items()},
            "paired_two_stage_minus_als": confidence(arrays["two_stage"] - arrays["als"]),
            "runs": run_info,
            "limitations": ["One fixed random split, not a temporal evaluation", "Three training seeds give limited evidence about between-run variation", "Offline ranking does not measure personal listening satisfaction", "Users have training histories; cold-user evaluation is not included"],
        }
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf8")
        np.savez_compressed(output.with_suffix(".npz"), **arrays)
        if library is not None:
            output.with_name("library-coverage.json").write_text(json.dumps(library_coverage(library, catalog), indent=2) + "\n", encoding="utf8")
        print("Evaluation report:", output, flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(".test-data/music-training"))
    parser.add_argument("--models", type=Path, nargs="+", required=True)
    parser.add_argument("--seeds", type=int, nargs="+", default=[42, 43, 44])
    parser.add_argument("--output", type=Path, default=Path(".test-data/music-evaluation/report.json"))
    parser.add_argument("--users", type=int, default=1000)
    parser.add_argument("--library", type=Path)
    args = parser.parse_args()
    if args.users < 1 or len(args.models) != len(args.seeds):
        parser.error("Positive user count and equal model/seed counts required")
    evaluate(args.root, args.models, args.seeds, args.output, args.users, args.library)


if __name__ == "__main__":
    main()
