#!/usr/bin/env python3
"""Formula-based scoring for Truth, Impact and Notoriety.

Truth  — Bayesian log-odds:  truth = 100 * sigma(prior + evidence - leak)
  prior     ln class base-rate odds of proven precedents (frozen in
            score_constants.json, computed from the pre-formula manual scores),
            clamped to [-4.0, +0.2]. sigma(0.2)=0.55 keeps the standing rule
            that precedent alone cannot lift a claim past 55. Physically
            impossible mechanisms pin the prior at -4.
  evidence  each source contributes w = quality * strength, where quality is
            the source's bias-class weight / 5 (court 1.0 ... fringe 0.0) and
            strength comes from its stance (documents +4, supports +1.5,
            contested 0, debunks -2.5). Per sign: strongest source per domain
            only, harmonic diminishing (1, 1/2, 1/3, ...), capped at +/-6.
            Records with no sources fall back to prose evidence items at
            +/-0.35 each (max 3 per side).
  leak      Grimes (2016, PLOS ONE) conspiracy-viability term: expected leaks
            p*N*t for N knowing conspirators over t years, capped at 2.5,
            skipped once a documents-grade source (bias>=4) exists. Implements
            the recency discount: silence is only evidence given time * heads.

Impact — geometric mean of annotated 0-5 factors (consequences if true):
  impact = 20 * (scale * severity * reach)^(1/3), factors floored at 0.5.

Notoriety — measured attention:
  notoriety = 100 * (log10(annual wikipedia pageviews) - 1.5) / 5.5, clamped;
  falls back to the annotated attention tier ladder when no article exists.

Run `python src/score.py --freeze` after factor annotation changes to
recompute class base rates into src/score_constants.json.
"""
import json, math, os, io, glob, sys
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONST_PATH = os.path.join(ROOT, "src", "score_constants.json")

DEFAULTS = {
    "prior_clamp": [-4.0, 0.2],
    "impossible_prior": -4.0,
    "prior_smoothing": 1.0,
    "stance_strength": {"proves": 4.0, "supports": 1.5, "context": 0.0,
                        "debunks": -2.5, "disproves": -4.0},
    # legacy stances (pre stance-audit) map conservatively: "documents" mostly
    # meant "documents the event/theory", which is not evidence of the claim
    "stance_legacy": {"documents": "context", "supports": "supports",
                      "debunks": "debunks", "contested": "context"},
    # proof-grade assertions carry the weight of the primary record they cite,
    # as long as the venue itself is at least tertiary-reliable (bias >= 2)
    "proof_q_floor": 0.75, "proof_q_floor_min_bias": 2,
    "quality_div": 5.0,
    "ev_cap": 6.0,
    "prose_w": 0.35, "prose_max": 3,
    "leak_p": 4e-6, "leak_t_max": 60, "leak_cap": 2.5, "leak_proof_bias": 4,
    "now_year": 2026,
    "impact_gain": 20.0, "impact_floor": 0.5,
    "noto_log_off": 1.5, "noto_log_div": 5.5, "noto_tier_band": 20,
    "att_ladder": [3, 10, 22, 40, 58, 75],
    "classes": {},          # cls -> [proven, total] frozen base rates
    "bias_weights": {"court": 5, "declassified": 4, "academic": 4, "investigative": 4,
                     "government": 3, "mainstream": 3, "book": 2, "wikipedia": 2,
                     "advocacy": 1, "fringe": 0},
}


def load_constants():
    c = dict(DEFAULTS)
    if os.path.exists(CONST_PATH):
        c.update(json.load(io.open(CONST_PATH, encoding="utf-8")))
    return c


def sigma(x):
    return 1.0 / (1.0 + math.exp(-x))


def _domain(url):
    try:
        h = urlparse(url).netloc.lower()
        return h[4:] if h.startswith("www.") else h
    except Exception:
        return url or ""


def truth_terms(t, f, C):
    """Returns (prior_term, ev_terms, leak_term, logit, truth).
    ev_terms: [srcIndex, stance, quality, strength, applied_weight]
    (srcIndex -1 marks a prose-evidence fallback term)."""
    lo, hi = C["prior_clamp"]
    k, n = C["classes"].get(f["cls"], [0, 1])
    s = C["prior_smoothing"]
    prior = math.log((k + s) / max(s, n - k + s))
    prior = max(lo, min(hi, prior))
    if f.get("imp"):
        prior = C["impossible_prior"]

    raw = []
    for i, src in enumerate(t.get("sources") or []):
        stance = (src.get("st") or C["stance_legacy"].get((src.get("stance") or "").lower(), "")).lower()
        if stance not in C["stance_strength"]:
            continue
        strength = C["stance_strength"][stance]
        if strength == 0.0:
            continue
        bw = C["bias_weights"].get(src.get("bias"), 2)
        q = bw / C["quality_div"]
        if stance in ("proves", "disproves") and bw >= C["proof_q_floor_min_bias"]:
            q = max(q, C["proof_q_floor"])
        w = q * strength
        if w != 0.0:
            raw.append([i, stance, round(q, 2), strength, w, _domain(src.get("url", ""))])

    if not raw:  # unsourced record: prose evidence items, weakly
        for x in (t.get("evidence_for") or [])[:C["prose_max"]]:
            raw.append([-1, "claimed", 0.0, C["prose_w"], C["prose_w"], ""])
        for x in (t.get("evidence_against") or [])[:C["prose_max"]]:
            raw.append([-1, "counter", 0.0, -C["prose_w"], -C["prose_w"], ""])

    ev_terms, ev_sum = [], 0.0
    for sign in (1, -1):
        grp = [r for r in raw if (r[4] > 0) == (sign > 0)]
        grp.sort(key=lambda r: -abs(r[4]))
        seen, kept = set(), []
        for r in grp:
            if r[5] and r[5] in seen:
                continue
            seen.add(r[5]); kept.append(r)
        subtotal = 0.0
        for j, r in enumerate(kept):
            w = r[4] / (j + 1)
            subtotal += w
            ev_terms.append([r[0], r[1], r[2], r[3], round(w, 2)])
        ev_sum += max(-C["ev_cap"], min(C["ev_cap"], subtotal))

    leak = None
    proven = any(src.get("st") == "proves" for src in (t.get("sources") or []))
    if not proven:
        tt = max(0, min(C["leak_t_max"], C["now_year"] - t.get("year", C["now_year"])))
        pen = min(C["leak_cap"], C["leak_p"] * (10 ** f["nlog"]) * tt)
        if pen > 0.005:
            leak = [f["nlog"], tt, round(pen, 2)]

    logit = prior + ev_sum - (leak[2] if leak else 0.0)
    return round(prior, 2), ev_terms, leak, round(logit, 2), int(round(100 * sigma(logit)))


def impact_of(f, C):
    fl = C["impact_floor"]
    g = (max(fl, f["scale"]) * max(fl, f["sev"]) * max(fl, f["reach"])) ** (1 / 3)
    return int(round(C["impact_gain"] * g))


def noto_of(f, views, C):
    """Measured pageviews, bounded to the annotated attention tier +/- band.
    The bound handles two known artifacts: articles about the underlying
    event/person (not the theory) inflate views; redirect pages read ~zero."""
    lad = C["att_ladder"][max(0, min(5, f.get("att", 1)))]
    if views is not None and views > 0:
        v = 100 * (math.log10(views) - C["noto_log_off"]) / C["noto_log_div"]
        b = C["noto_tier_band"]
        v = max(lad - b, min(lad + b, v))
        return max(1, min(100, int(round(v))))
    return lad


def score_theory(t, f, views, C):
    """Attach computed scores + transparent breakdown to theory dict t."""
    prior, ev, leak, logit, truth = truth_terms(t, f, C)
    imp = impact_of(f, C)
    noto = noto_of(f, views, C)
    t["truth_manual"], t["impact_manual"], t["notoriety_manual"] = t["truth"], t["impact"], t["notoriety"]
    t["truth"], t["impact"], t["notoriety"] = truth, imp, noto
    t["score"] = {
        "cls": f["cls"], "imp": bool(f.get("imp")),
        "prior": [C["classes"].get(f["cls"], [0, 1])[0], C["classes"].get(f["cls"], [0, 1])[1], prior],
        "ev": ev, "leak": leak, "logit": logit,
        "if": [f["scale"], f["sev"], f["reach"]],
        "pv": views, "att": f.get("att"),
    }


def load_factors():
    F = {}
    for fp in sorted(glob.glob(os.path.join(ROOT, "data", "factors", "fact_*.json"))):
        for r in json.load(io.open(fp, encoding="utf-8")):
            F[r["id"]] = r
    return F


def freeze_base_rates(theories, factors):
    """Class base rates from manual scores: proven = manual truth >= 91."""
    counts = {}
    for t in theories:
        f = factors.get(t["id"])
        if not f:
            continue
        k, n = counts.setdefault(f["cls"], [0, 0])
        tr = t.get("truth_manual", t["truth"])
        counts[f["cls"]][1] += 1
        if tr >= 91:
            counts[f["cls"]][0] += 1
    c = load_constants()
    c["classes"] = counts
    keep = {k: v for k, v in c.items() if k in DEFAULTS}
    io.open(CONST_PATH, "w", encoding="utf-8").write(json.dumps(keep, indent=1))
    return counts


if __name__ == "__main__":
    d = json.load(io.open(os.path.join(ROOT, "docs", "data.json"), encoding="utf-8"))
    factors = load_factors()
    print(f"{len(factors)} factor annotations loaded", file=sys.stderr)
    if "--freeze" in sys.argv:
        counts = freeze_base_rates(d["theories"], factors)
        for cls, (k, n) in sorted(counts.items(), key=lambda x: -x[1][0] / max(1, x[1][1])):
            print(f"  {cls:22s} {k:3d}/{n:4d} proven  prior={max(-4, min(0.2, math.log((k+1)/max(1, n-k+1)))):+.2f}")
