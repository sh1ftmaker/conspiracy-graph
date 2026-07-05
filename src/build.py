#!/usr/bin/env python3
"""Merge + validate all theory records -> docs/data.json for the website.

Sources merged (dedup by id, first-seen wins, seed has priority):
  data/theories.seed.json        (hand-authored anchors)
  data/enriched/batch_*.json     (subagent-enriched records)

Derived fields added per theory:
  gi           genre index into meta.genres
  load_bearing in-degree over depends_on edges (how many theories require this)
Edges in related/depends_on are filtered to existing ids (dangling dropped).
"""
import json, glob, os, sys, io, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def p(*a): return os.path.join(ROOT, *a)

def load(path):
    with io.open(path, encoding="utf-8") as f:
        return json.load(f)

tax = load(p("src", "taxonomy.json"))
genres = tax["genres"]
gkey_to_idx = {g["key"]: i for i, g in enumerate(genres)}

def slug(s):
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s

# ---- gather sources ----
records = {}
order = []
warnings = []

def add(rec, source):
    rid = rec.get("id") or slug(rec.get("name", ""))
    rec["id"] = rid
    if rid in records:
        return  # first-seen wins (seed loaded first)
    records[rid] = rec
    order.append(rid)

seed_path = p("data", "theories.seed.json")
if os.path.exists(seed_path):
    for r in load(seed_path):
        add(r, "seed")

for bf in sorted(glob.glob(p("data", "enriched", "batch_*.json"))):
    try:
        data = load(bf)
    except Exception as e:
        warnings.append(f"could not parse {os.path.basename(bf)}: {e}")
        continue
    if isinstance(data, dict):  # tolerate {"theories":[...]}
        data = data.get("theories") or data.get("records") or []
    for r in data:
        add(r, os.path.basename(bf))

# ---- validate / normalize ----
def clampi(v, lo, hi, default):
    try:
        v = int(round(float(v)))
    except Exception:
        return default
    return max(lo, min(hi, v))

for rid in order:
    r = records[rid]
    r.setdefault("name", rid)
    r.setdefault("aliases", [])
    g = r.get("genre")
    if g not in gkey_to_idx:
        # try to coerce common variants
        g2 = slug(g or "")
        g = g2 if g2 in gkey_to_idx else "government"
        if r.get("genre") != g:
            warnings.append(f"{rid}: genre '{r.get('genre')}' -> '{g}'")
    r["genre"] = g
    r["gi"] = gkey_to_idx[g]
    r["truth"] = clampi(r.get("truth"), 0, 100, 30)
    r["impact"] = clampi(r.get("impact"), 0, 100, 40)
    r["notoriety"] = clampi(r.get("notoriety"), 0, 100, 40)
    r["year"] = clampi(r.get("year"), -3000, 2100, 2000)
    for fld in ("summary",):
        r.setdefault(fld, "")
    for fld in ("evidence_for", "evidence_against", "related", "depends_on"):
        v = r.get(fld)
        r[fld] = v if isinstance(v, list) else []

ids = set(records)

# ---- resolve edges (map names/slugs to ids; drop dangling) ----
def resolve(lst):
    out = []
    for x in lst:
        if not isinstance(x, str):
            continue
        cand = x if x in ids else slug(x)
        if cand in ids and cand not in out:
            out.append(cand)
    return out

dangling = 0
for rid in order:
    r = records[rid]
    before = len(r["related"]) + len(r["depends_on"])
    r["related"] = [x for x in resolve(r["related"]) if x != rid]
    r["depends_on"] = [x for x in resolve(r["depends_on"]) if x != rid]
    dangling += before - (len(r["related"]) + len(r["depends_on"]))

# make related symmetric (nice for graph)
for rid in order:
    for o in records[rid]["related"]:
        if rid not in records[o]["related"]:
            records[o]["related"].append(rid)

# ---- load-bearing: in-degree over depends_on ----
for rid in order:
    records[rid]["load_bearing"] = 0
for rid in order:
    for dep in records[rid]["depends_on"]:
        records[dep]["load_bearing"] += 1

theories = [records[rid] for rid in order]

# ---- stats ----
by_genre = {}
by_status = {"Debunked":0,"Fringe":0,"Contested":0,"Plausible":0,"Substantiated":0,"Confirmed":0}
def status_of(t):
    for s in tax["truth_scale"]:
        if s["min"] <= t <= s["max"]:
            return s["label"]
    return "?"
for r in theories:
    by_genre[r["genre"]] = by_genre.get(r["genre"], 0) + 1
    by_status[status_of(r["truth"])] = by_status.get(status_of(r["truth"]), 0) + 1

out = {
    "meta": {
        "count": len(theories),
        "genres": genres,
        "truth_scale": tax["truth_scale"],
        "impact_scale": tax["impact_scale"],
        "by_genre": by_genre,
        "by_status": by_status,
    },
    "theories": theories,
}

os.makedirs(p("docs"), exist_ok=True)
with io.open(p("docs", "data.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, separators=(",", ":"))

# also drop a .nojekyll for Pages
open(p("docs", ".nojekyll"), "w").close()

msg = [f"built docs/data.json  theories={len(theories)}  dangling_edges_dropped={dangling}"]
msg.append("by_status: " + ", ".join(f"{k}={v}" for k,v in by_status.items() if v))
top = sorted(theories, key=lambda r: r["load_bearing"], reverse=True)[:6]
msg.append("top load-bearing: " + ", ".join(f"{r['id']}({r['load_bearing']})" for r in top))
if warnings:
    msg.append(f"warnings ({len(warnings)}): " + " | ".join(warnings[:8]))
sys.stdout.write("\n".join(msg).encode("ascii","replace").decode("ascii") + "\n")
