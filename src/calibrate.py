#!/usr/bin/env python3
"""Compare formula scores against pre-formula editorial scores.

Run after build.py has attached formula scores (records carry *_manual).
Prints MAE per metric, the truth band-migration matrix, and biggest movers.
"""
import json, io, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BANDS = [(91, 100, "Confirmed"), (76, 90, "Substantiated"), (56, 75, "Plausible"),
         (31, 55, "Contested"), (11, 30, "Fringe"), (0, 10, "Debunked")]


def band(v):
    for lo, hi, name in BANDS:
        if lo <= v <= hi:
            return name
    return "?"


def main():
    d = json.load(io.open(os.path.join(ROOT, "docs", "data.json"), encoding="utf-8"))
    T = [t for t in d["theories"] if "truth_manual" in t]
    print(f"{len(T)} formula-scored records\n")

    for k in ("truth", "impact", "notoriety"):
        diffs = [t[k] - t[f"{k}_manual"] for t in T]
        mae = sum(abs(x) for x in diffs) / len(diffs)
        up = sum(1 for x in diffs if x > 0)
        print(f"{k:10s} MAE={mae:5.1f}  mean={sum(diffs)/len(diffs):+5.1f}  up={up} down={len(diffs)-up}")

    print("\ntruth band migration (rows=manual, cols=formula):")
    names = [b[2] for b in BANDS]
    M = {a: {b: 0 for b in names} for a in names}
    for t in T:
        M[band(t["truth_manual"])][band(t["truth"])] += 1
    print(" " * 14 + "".join(f"{n[:9]:>10s}" for n in names))
    for a in names:
        print(f"{a:>13s} " + "".join(f"{M[a][b]:>10d}" for b in names))

    for k in ("truth", "impact", "notoriety"):
        movers = sorted(T, key=lambda t: -abs(t[k] - t[f"{k}_manual"]))[:12]
        print(f"\nbiggest {k} movers:")
        for t in movers:
            print(f"  {t[k]-t[f'{k}_manual']:+4d}  {t[f'{k}_manual']:3d}->{t[k]:3d}  {t['id'][:44]:44s} "
                  f"cls={t.get('score',{}).get('cls','?')}")

    # sanity flags
    bad = [t for t in T if band(t["truth_manual"]) == "Confirmed" and t["truth"] < 76]
    if bad:
        print(f"\nWARNING {len(bad)} manually-Confirmed records fell below 76:")
        for t in bad[:15]:
            print("  ", t["id"], t["truth_manual"], "->", t["truth"])
    imposs = [t for t in T if t.get("score", {}).get("imp") and t["truth"] > 20]
    if imposs:
        print(f"\nWARNING {len(imposs)} impossible-flagged records scored >20:")
        for t in imposs[:10]:
            print("  ", t["id"], "->", t["truth"])


if __name__ == "__main__":
    main()
