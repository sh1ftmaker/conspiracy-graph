"""Apply Haiku-agent dedup verdicts to the source data files.

Reads dedup_out_*.json verdict files (arrays of [a_id, b_id, "MERGE"|"DISTINCT"]),
union-finds the MERGE pairs into groups, picks a canonical entry per group, then
edits data/theories.seed.json + data/enriched/batch_*.json in place:
  - dup entries are removed; their name/aliases fold into the canonical's aliases
  - dup evidence_for items are unioned into the canonical (capped)
  - depends_on/related references to removed ids are remapped to the canonical

Run build.py afterwards, then re-embed changed ids and re-project.

Usage:
  python src/apply_dedup.py --verdicts "<dir-with-dedup_out_*.json>" [--dry-run]
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# build.py merge order: first-seen wins, so earlier file = higher authority
SOURCE_FILES = [ROOT / "data" / "theories.seed.json"] + sorted(
    (ROOT / "data" / "enriched").glob("batch_*.json"),
    key=lambda p: int(p.stem.split("_")[1]),
)


def log(*a):
    print(*a, file=sys.stderr, flush=True)


class UF:
    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verdicts", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    merges = []
    for f in sorted(glob.glob(str(Path(args.verdicts) / "dedup_out_*.json"))):
        rows = json.loads(Path(f).read_text(encoding="utf-8"))
        for r in rows:
            if len(r) >= 3 and str(r[2]).upper() == "MERGE":
                merges.append((r[0], r[1]))
    log(f"{len(merges)} MERGE verdicts")

    # load all source files; first occurrence of an id wins (mirrors build.py)
    files = {}
    entry = {}   # id -> (file, index in file)  first-seen only
    rank = {}    # id -> priority (lower = more authoritative)
    for pri, path in enumerate(SOURCE_FILES):
        arr = json.loads(path.read_text(encoding="utf-8"))
        files[path] = arr
        for i, t in enumerate(arr):
            if t["id"] not in entry:
                entry[t["id"]] = (path, i)
                rank[t["id"]] = pri

    uf = UF()
    known = 0
    for a, b in merges:
        if a in entry and b in entry:
            uf.union(a, b)
            known += 1
    groups = {}
    for tid in list(uf.p):
        groups.setdefault(uf.find(tid), []).append(tid)
    groups = [g for g in groups.values() if len(g) > 1]
    log(f"{known} usable pairs -> {len(groups)} merge groups "
        f"covering {sum(len(g) for g in groups)} entries")

    def get(tid):
        path, i = entry[tid]
        return files[path][i]

    def canonical_of(group):
        # sourced beats unsourced; then notoriety; then build-order authority
        def key(tid):
            t = get(tid)
            return (
                0 if (t.get("wikipedia") or t.get("sources")) else 1,
                -t.get("notoriety", 0),
                rank[tid],
                tid,
            )
        return sorted(group, key=key)[0]

    removed = {}          # dup id -> canonical id
    changed_evidence = set()
    for g in groups:
        canon_id = canonical_of(g)
        canon = get(canon_id)
        aliases = {a.lower(): a for a in canon.get("aliases", [])}
        ev = list(canon.get("evidence_for", []))
        ev_seen = {e.strip().lower() for e in ev}
        for tid in g:
            if tid == canon_id:
                continue
            dup = get(tid)
            removed[tid] = canon_id
            for name in [dup["name"]] + dup.get("aliases", []):
                if name.lower() != canon["name"].lower():
                    aliases.setdefault(name.lower(), name)
            for e in dup.get("evidence_for", []):
                k = e.strip().lower()
                if k and k not in ev_seen and len(ev) < 6:
                    ev.append(e)
                    ev_seen.add(k)
        if aliases:
            canon["aliases"] = sorted(aliases.values())
        if ev != canon.get("evidence_for", []):
            canon["evidence_for"] = ev
            changed_evidence.add(canon_id)

    log(f"removing {len(removed)} duplicate entries; "
        f"{len(changed_evidence)} canonicals gained evidence")
    for dup, canon in sorted(removed.items()):
        log(f"  {dup} -> {canon}")

    # rewrite files: drop removed ids everywhere (incl. shadowed later copies),
    # remap cross-references
    for path, arr in files.items():
        out = []
        for t in arr:
            if t["id"] in removed:
                continue
            for field in ("depends_on", "related"):
                if field in t and t[field]:
                    seen, remapped = set(), []
                    for ref in t[field]:
                        ref = removed.get(ref, ref)
                        if ref != t["id"] and ref not in seen:
                            seen.add(ref)
                            remapped.append(ref)
                    t[field] = remapped
            out.append(t)
        if args.dry_run:
            if len(out) != len(arr):
                log(f"  {path.name}: {len(arr)} -> {len(out)}")
            continue
        if out != arr or True:
            path.write_text(
                json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    # ids whose embedding is now stale (removed or text changed)
    stale = sorted(set(removed) | changed_evidence)
    (ROOT / "out" / "stale_embed_ids.json").write_text(json.dumps(stale))
    log(f"wrote out/stale_embed_ids.json ({len(stale)} ids)")
    if args.dry_run:
        log("DRY RUN - no files written")


if __name__ == "__main__":
    main()
