"""Project theory embeddings (gemini-embedding-2) into 2D/3D layouts and
write them onto docs/data.json as ex/ey/ez (2D) and ex3/ey3/ez3 (3D).

Run AFTER build.py (this is a post-processing pass over docs/data.json).

Usage:
  python project_embed.py --emb ../out/embeddings.npz --data ../docs/data.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def norm_coords(a, scale=1.0):
    a = np.asarray(a, dtype=np.float32)
    a = a - a.mean(0)
    s = np.abs(a).max() or 1.0
    return a / s * scale


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--emb", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--neighbors", type=int, default=15)
    ap.add_argument("--min-dist", type=float, default=0.15)
    args = ap.parse_args()

    d = np.load(args.emb, allow_pickle=True)
    ids = [str(x) for x in d["ids"]]
    X = d["vectors"].astype(np.float32)
    log(f"embeddings {X.shape}")

    data_path = Path(args.data)
    doc = json.loads(data_path.read_text(encoding="utf-8"))
    theories = doc["theories"]
    by_id = {t["id"]: t for t in theories}

    missing = [t["id"] for t in theories if t["id"] not in set(ids)]
    if missing:
        log(f"warning: {len(missing)} theories have no embedding (left at origin): {missing[:5]}")

    try:
        import umap
        red2 = umap.UMAP(n_components=2, n_neighbors=args.neighbors, min_dist=args.min_dist,
                         metric="cosine", random_state=42)
        xy = red2.fit_transform(X)
        red3 = umap.UMAP(n_components=3, n_neighbors=args.neighbors, min_dist=args.min_dist,
                         metric="cosine", random_state=42)
        xyz = red3.fit_transform(X)
        layout = "umap"
    except Exception as e:  # noqa: BLE001
        log(f"UMAP unavailable ({e}); PCA fallback")
        from sklearn.decomposition import PCA
        xy = PCA(n_components=2, random_state=42).fit_transform(X)
        xyz = PCA(n_components=3, random_state=42).fit_transform(X)
        layout = "pca"

    xy = norm_coords(xy, 60.0)
    xyz = norm_coords(xyz, 60.0)

    # nearest neighbors in full embedding space (for a "semantically related" trace)
    from sklearn.neighbors import NearestNeighbors
    k = min(8, X.shape[0] - 1)
    nn = NearestNeighbors(n_neighbors=k + 1, metric="cosine").fit(X)
    _, nidx = nn.kneighbors(X)

    for i, tid in enumerate(ids):
        t = by_id.get(tid)
        if not t:
            continue
        t["ex"] = round(float(xy[i, 0]), 3)
        t["ey"] = round(float(xy[i, 1]), 3)
        t["ex3"] = round(float(xyz[i, 0]), 3)
        t["ey3"] = round(float(xyz[i, 1]), 3)
        t["ez3"] = round(float(xyz[i, 2]), 3)
        t["nn"] = [ids[j] for j in nidx[i, 1:] if ids[j] != tid][:k]

    for tid in missing:
        t = by_id[tid]
        t.setdefault("ex", 0.0); t.setdefault("ey", 0.0)
        t.setdefault("ex3", 0.0); t.setdefault("ey3", 0.0); t.setdefault("ez3", 0.0)
        t.setdefault("nn", [])

    doc["meta"]["embed_layout"] = layout
    doc["meta"]["embed_model"] = str(d["model"]) if "model" in d else "gemini-embedding-2"
    data_path.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log(f"wrote embedding coords ({layout}) for {len(ids)} theories into {data_path}")


if __name__ == "__main__":
    main()
