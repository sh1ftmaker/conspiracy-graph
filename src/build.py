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

def ev_text(x):
    """Evidence items are either a plain string or {"text": ..., "source": url}."""
    if isinstance(x, str):
        return x
    if isinstance(x, dict):
        return x.get("text") or ""
    return ""

# ---- apply research overlays (data/research/*.json) ----
# Overlay files are arrays of PARTIAL records keyed by id: scalars overwrite,
# evidence arrays append (deduped), sources append (deduped by url). This is
# the contribution path for source research: drop a new overlay file, rebuild.
for rf in sorted(glob.glob(p("data", "research", "*.json"))):
    try:
        data = load(rf)
    except Exception as e:
        warnings.append(f"could not parse {os.path.basename(rf)}: {e}")
        continue
    for o in data:
        rid = o.get("id")
        r = records.get(rid)
        if not r:
            warnings.append(f"{os.path.basename(rf)}: unknown id '{rid}'")
            continue
        for fld in ("summary", "wikipedia", "wikidata", "year",
                    "truth", "impact", "notoriety", "research_note", "steelman"):
            if fld in o and o[fld] not in (None, ""):
                r[fld] = o[fld]
        # precedents: proven-theory ids that steelman this claim's class (append, dedup)
        if isinstance(o.get("precedents"), list):
            cur = r.get("precedents") if isinstance(r.get("precedents"), list) else []
            for x in o["precedents"]:
                if isinstance(x, str) and x not in cur:
                    cur.append(x)
            r["precedents"] = cur
        for fld in ("evidence_for", "evidence_against"):
            if isinstance(o.get(fld), list):
                base = [x for x in (r.get(fld) or []) if ev_text(x)]
                seen = {ev_text(x).strip().lower() for x in base}
                for x in o[fld]:
                    key = ev_text(x).strip().lower()
                    if key and key not in seen:
                        base.append(x)
                        seen.add(key)
                r[fld] = base[:8]
        if isinstance(o.get("sources"), list):
            cur = r.get("sources") if isinstance(r.get("sources"), list) else []
            urls = {s.get("url") for s in cur if isinstance(s, dict)}
            for s_ in o["sources"]:
                if isinstance(s_, dict) and s_.get("url") and s_["url"] not in urls:
                    cur.append({k: s_[k] for k in ("title", "url", "type", "stance") if k in s_})
                    urls.add(s_["url"])
            r["sources"] = cur

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
    for fld in ("evidence_for", "evidence_against", "related", "depends_on", "sources",
                "precedents"):
        v = r.get(fld)
        r[fld] = v if isinstance(v, list) else []
    for fld in ("evidence_for", "evidence_against"):
        r[fld] = [x for x in r[fld] if ev_text(x).strip()]

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
    before = len(r["related"]) + len(r["depends_on"]) + len(r["precedents"])
    r["related"] = [x for x in resolve(r["related"]) if x != rid]
    r["depends_on"] = [x for x in resolve(r["depends_on"]) if x != rid]
    r["precedents"] = [x for x in resolve(r["precedents"]) if x != rid]
    dangling += before - (len(r["related"]) + len(r["depends_on"]) + len(r["precedents"]))
    # precedents also count as related so they show up as graph edges
    for x in r["precedents"]:
        if x not in r["related"]:
            r["related"].append(x)

# make related symmetric (nice for graph)
for rid in order:
    for o in records[rid]["related"]:
        if rid not in records[o]["related"]:
            records[o]["related"].append(rid)

# ---- source bias classification ----
# Every source gets a `bias` class inferred from its domain + declared type.
# The point: a court record, a declassified file, a government self-report,
# adversarial journalism and Wikipedia are NOT interchangeable kinds of evidence.
# Declassified/state sources only show what the state chose to release
# (survivorship bias); Wikipedia is systematically conservative on ongoing ops.
BIAS_SCALE = [  # key, label, weight (how much independent probative force), color
    {"key": "court",       "label": "Court / legal record",     "weight": 5, "color": "#4ade80"},
    {"key": "declassified","label": "Declassified document",    "weight": 4, "color": "#86efac"},
    {"key": "academic",    "label": "Academic / peer-reviewed", "weight": 4, "color": "#22d3ee"},
    {"key": "investigative","label": "Investigative journalism","weight": 4, "color": "#bef264"},
    {"key": "government",  "label": "Government self-report",   "weight": 3, "color": "#fbbf24"},
    {"key": "mainstream",  "label": "Mainstream press",         "weight": 3, "color": "#60a5fa"},
    {"key": "book",        "label": "Book / archive",           "weight": 2, "color": "#a78bfa"},
    {"key": "wikipedia",   "label": "Wikipedia (tertiary)",     "weight": 2, "color": "#9aa1bb"},
    {"key": "advocacy",    "label": "Advocacy / partisan",      "weight": 1, "color": "#fb923c"},
    {"key": "fringe",      "label": "Fringe / unverified",      "weight": 0, "color": "#f87171"},
]
COURT_HOSTS = ("courtlistener", "supremecourt.gov", "uscourts.gov", "pacer",
               "casetext", "justia", "law.justia")
DECLASS_HOSTS = ("nsarchive", "nsarchive2", "cia.gov/readingroom", "governmentattic",
                 "archives.gov", "foia.", "theblackvault", "documentcloud",
                 "intelligence.senate.gov", "aarclibrary", "maryferrell")
INVESTIGATIVE_HOSTS = ("propublica", "theintercept", "icij.org", "bellingcat",
                       "occrp.org", "revealnews", "consortiumnews", "muckrock")
ACADEMIC_HOSTS = (".edu", "jstor", "doi.org", "nature.com", "sciencedirect", "springer",
                  "ncbi.nlm.nih.gov", "pubmed", "nejm.org", "thelancet", "bmj.com",
                  "jamanetwork", "academic.oup", "tandfonline", "sagepub", "cambridge.org",
                  "wiley.com", "plos.org", "arxiv.org", "ssrn.com", "researchgate")
MAINSTREAM_HOSTS = ("nytimes", "washingtonpost", "theguardian", "bbc.", "reuters",
                    "apnews", "npr.org", "wsj.com", "latimes", "cnn.com", "cbsnews",
                    "nbcnews", "abcnews", "aljazeera", "economist", "ft.com", "time.com",
                    "theatlantic", "newyorker", "politico", "axios", "bloomberg",
                    "usatoday", "pbs.org", "cbc.ca", "dw.com", "france24", "spiegel",
                    "lemonde", "haaretz", "timesofisrael", "smh.com.au", "independent.co.uk",
                    "telegraph.co.uk", "vice.com", "wired.com", "arstechnica", "vox.com")
DEBUNKER_HOSTS = ("snopes", "politifact", "factcheck.org", "fullfact", "skeptic",
                  "rationalwiki", "metabunk", "quackwatch", "sciencebasedmedicine")
def classify_bias(src):
    url = (src.get("url") or "").lower()
    typ = (src.get("type") or "").lower()
    host = url.split("//")[-1].split("/")[0]
    def hit(hosts): return any(h in url for h in hosts)
    if hit(COURT_HOSTS) or "justice.gov" in url and ("case" in url or "opa" in url or "usao" in url):
        return "court"
    if hit(DECLASS_HOSTS):
        return "declassified"
    if hit(INVESTIGATIVE_HOSTS):
        return "investigative"
    if hit(ACADEMIC_HOSTS) or typ == "academic":
        return "academic"
    if "wikipedia.org" in host or typ == "wikipedia":
        return "wikipedia"
    if host.endswith(".gov") or ".gov/" in url or ".mil" in host or typ == "government":
        return "government"
    if hit(DEBUNKER_HOSTS) or typ == "debunker":
        return "academic" if typ == "academic" else "investigative"
    if hit(MAINSTREAM_HOSTS) or typ == "news":
        return "mainstream"
    if typ in ("book", "archive"):
        return "book"
    return "fringe" if typ in ("forum", "blog", "social") else "book"

for rid in order:
    for s_ in records[rid]["sources"]:
        if isinstance(s_, dict):
            s_["bias"] = classify_bias(s_)

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
sourced = 0
for r in theories:
    by_genre[r["genre"]] = by_genre.get(r["genre"], 0) + 1
    by_status[status_of(r["truth"])] = by_status.get(status_of(r["truth"]), 0) + 1
    if r["sources"] or r.get("wikipedia"):
        sourced += 1

out = {
    "meta": {
        "count": len(theories),
        "genres": genres,
        "truth_scale": tax["truth_scale"],
        "impact_scale": tax["impact_scale"],
        "by_genre": by_genre,
        "by_status": by_status,
        "sourced": sourced,
        "bias_scale": BIAS_SCALE,
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
