"""Embed every theory in docs/data.json with Google's gemini-embedding-2.

Same pattern as tvtropes-embed/src/embed_gemini.py: one input per request,
fanned out across a thread pool, resumable per-id cache, unit-normalized
output vectors (cosine == dot, ideal for UMAP).

Usage:
  python embed_theories.py --sa <path-to-sa.json> --out ../out/embeddings.npz
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def load_rows(data_json: Path):
    d = json.loads(data_json.read_text(encoding="utf-8"))
    ids, texts = [], []
    for t in d["theories"]:
        parts = [t["name"], t.get("summary", "")]
        parts += t.get("evidence_for", [])[:3]
        text = " ".join(p.strip() for p in parts if p and p.strip())
        if len(text) > 6000:
            text = text[:6000]
        ids.append(t["id"])
        texts.append(text)
    return ids, texts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(Path(__file__).resolve().parent.parent / "docs" / "data.json"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default="gemini-embedding-2")
    ap.add_argument("--dim", type=int, default=768)
    ap.add_argument("--workers", type=int, default=24)
    ap.add_argument("--task-type", default="SEMANTIC_SIMILARITY")
    ap.add_argument("--sa", required=True, help="service-account JSON path")
    ap.add_argument("--project", default="selstech")
    ap.add_argument("--location", default="global")
    args = ap.parse_args()

    from google import genai
    from google.genai import types
    from google.oauth2 import service_account

    creds = service_account.Credentials.from_service_account_file(
        args.sa, scopes=["https://www.googleapis.com/auth/cloud-platform"])
    client = genai.Client(vertexai=True, project=args.project, location=args.location, credentials=creds)
    log(f"auth: Vertex AI project={args.project} loc={args.location} model={args.model}")

    ids, texts = load_rows(Path(args.data))
    log(f"loaded {len(ids)} theories")

    out = Path(args.out)
    cache_dir = Path(out.with_suffix("").as_posix() + "_cache")
    cache_dir.mkdir(parents=True, exist_ok=True)

    vecs: dict[str, np.ndarray] = {}
    for f in cache_dir.glob("*.npy"):
        vecs[f.stem] = np.load(f)
    if vecs:
        log(f"resumed {len(vecs)} cached vectors")

    todo = [(i, t) for i, t in zip(ids, texts) if i not in vecs]
    log(f"{len(todo)} to embed")

    cfg = types.EmbedContentConfig(task_type=args.task_type, output_dimensionality=args.dim)
    lock = threading.Lock()
    state = {"done": 0, "fail": 0}

    def embed_one(item):
        tid, text = item
        delay = 2.0
        for attempt in range(8):
            try:
                resp = client.models.embed_content(model=args.model, contents=text, config=cfg)
                emb = np.asarray(resp.embeddings[0].values, dtype=np.float32)
                n = np.linalg.norm(emb)
                if n > 0:
                    emb = emb / n
                vecs[tid] = emb
                np.save(cache_dir / f"{tid}.npy", emb)
                with lock:
                    state["done"] += 1
                    if state["done"] % 100 == 0:
                        log(f"  embedded {state['done']}/{len(todo)} (fail {state['fail']})")
                return
            except Exception as e:  # noqa: BLE001
                msg = str(e)
                transient = any(c in msg for c in ("429", "500", "503", "deadline",
                                                    "RESOURCE_EXHAUSTED", "UNAVAILABLE"))
                if attempt == 7 or not transient:
                    with lock:
                        state["fail"] += 1
                    log(f"  FAIL {tid}: {msg[:120]}")
                    return
                time.sleep(delay)
                delay = min(delay * 1.8, 45)

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        list(ex.map(embed_one, todo))
    log(f"done: {state['done']} embedded, {state['fail']} failed, {len(vecs)} total cached")

    keep_ids = [i for i in ids if i in vecs]
    mat = np.vstack([vecs[i] for i in keep_ids]).astype(np.float32)
    np.savez_compressed(out, ids=np.array(keep_ids), vectors=mat, model=args.model, dim=args.dim)
    log(f"wrote {out} -> {mat.shape}")


if __name__ == "__main__":
    main()
