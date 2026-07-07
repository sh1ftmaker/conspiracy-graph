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
    # ---- Means/Motive/Opportunity prior (replaces class base-rate) ----
    # The prior for a factual claim is set by the conjunction of the alleged
    # actors' means, motive and opportunity (0-4 each) -- the investigator's
    # triad -- NOT by how many false theories share its genre. MMO establishes
    # plausibility; it stays below the midline so evidence must do the lifting.
    "mmo_min": -3.7, "mmo_max": -0.6, "mmo_floor": 0.5,
    # a denial by the accused party arguing against the claim is discounted to
    # this fraction of its normal weight (guilty parties deny too).
    "self_denial_discount": 0.25,
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
    # measured pageviews are blended toward the tier anchor (soft, not hard-clamped)
    # so scores spread continuously instead of piling at the band edges.
    "noto_pv_blend": 0.8, "noto_pv_band": 32,
    "att_ladder": [3, 10, 22, 40, 58, 75],
    # ---- metaphysical "frame" plausibility (a DIFFERENT truth axis) ----
    # For entries that are frameworks of reality (idealism, simulation theory,
    # pantheism, invented cosmologies) rather than empirical historical claims.
    # We score probability-among-worldviews, not historical fact: no source can
    # "prove" a metaphysics, so the axis is capped well below certainty.
    "ped_map": [-1.0, -0.5, -0.15, 0.2, 0.45],  # pedigree 0-4: creepypasta -> live academic/major tradition
    "coh_map": [-0.7, -0.35, 0.0, 0.2, 0.4],    # coherence 0-4: self-contradictory -> consistent with known physics/logic
    "par_map": [-0.5, -0.25, 0.0, 0.15, 0.3],   # parsimony 0-4: baroque ontology -> minimal assumptions
    "frame_pro": 1.0, "frame_con": 0.9,         # per-source strength for arguments for / against the framework
    "frame_pro_cap": 0.65, "frame_con_cap": 0.8,
    "frame_ceiling": 85,                         # nothing metaphysical is ever "proven"
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
    fl = C["mmo_floor"]
    m = max(fl, f.get("means", 2)); mo = max(fl, f.get("motive", 2)); o = max(fl, f.get("opp", 2))
    g = ((m * mo * o) ** (1 / 3)) / 4.0          # conjunctive: any weak leg drags it down
    prior = C["mmo_min"] + (C["mmo_max"] - C["mmo_min"]) * g
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
        # a denial by the accused party ("we didn't do it") is expected whether
        # guilty or not, so it carries almost no probative weight; an admission
        # against interest keeps full weight.
        selfd = bool(src.get("self")) and stance in ("debunks", "disproves")
        w = q * strength * (C["self_denial_discount"] if selfd else 1.0)
        if w != 0.0:
            raw.append([i, stance, round(q, 2), strength, w, _domain(src.get("url", "")), selfd])

    if not raw:  # unsourced record: prose evidence items, weakly
        for x in (t.get("evidence_for") or [])[:C["prose_max"]]:
            raw.append([-1, "claimed", 0.0, C["prose_w"], C["prose_w"], "", False])
        for x in (t.get("evidence_against") or [])[:C["prose_max"]]:
            raw.append([-1, "counter", 0.0, -C["prose_w"], -C["prose_w"], "", False])

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
            ev_terms.append([r[0], r[1], r[2], r[3], round(w, 2), bool(r[6])])
        ev_sum += max(-C["ev_cap"], min(C["ev_cap"], subtotal))

    leak = None
    proven = any(src.get("st") == "proves" for src in (t.get("sources") or []))
    if not proven:
        tt = max(0, min(C["leak_t_max"], C["now_year"] - t.get("year", C["now_year"])))
        pen = min(C["leak_cap"], C["leak_p"] * (10 ** f["nlog"]) * tt)
        if pen > 0.005:
            leak = [f["nlog"], tt, round(pen, 2)]

    logit = prior + ev_sum - (leak[2] if leak else 0.0)
    mmo = [f.get("means", 2), f.get("motive", 2), f.get("opp", 2)]
    return round(prior, 2), mmo, ev_terms, leak, round(logit, 2), int(round(100 * sigma(logit)))


def frame_terms(t, f, C):
    """Metaphysical plausibility: 100*sigma(pedigree + coherence + parsimony
    + argued support), capped below certainty. Returns
    (ped_term, coh_term, par_term, src_terms, logit, plausibility)."""
    ped = C["ped_map"][max(0, min(4, f.get("ped", 2)))]
    coh = C["coh_map"][max(0, min(4, f.get("coh", 2)))]
    par = C["par_map"][max(0, min(4, f.get("par", 2)))]

    raw = []
    for i, src in enumerate(t.get("sources") or []):
        st = (src.get("st") or C["stance_legacy"].get((src.get("stance") or "").lower(), "")).lower()
        if st in ("proves", "supports"):
            sign = 1
        elif st in ("debunks", "disproves"):
            sign = -1
        else:
            continue
        q = C["bias_weights"].get(src.get("bias"), 2) / C["quality_div"]
        strength = C["frame_pro"] if sign > 0 else -C["frame_con"]
        raw.append([i, st, round(q, 2), sign, q * strength, _domain(src.get("url", ""))])

    src_terms, src_sum = [], 0.0
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
            src_terms.append([r[0], r[1], r[2], round(w, 2)])
        cap = C["frame_pro_cap"] if sign > 0 else C["frame_con_cap"]
        src_sum += max(-cap, min(cap, subtotal)) if sign > 0 else max(-cap, min(cap, subtotal))

    logit = ped + coh + par + src_sum
    plaus = min(C["frame_ceiling"], max(1, int(round(100 * sigma(logit)))))
    return round(ped, 2), round(coh, 2), round(par, 2), src_terms, round(logit, 2), plaus


def impact_of(f, C):
    fl = C["impact_floor"]
    g = (max(fl, f["scale"]) * max(fl, f["sev"]) * max(fl, f["reach"])) ** (1 / 3)
    return int(round(C["impact_gain"] * g))


def noto_of(f, views, reach, C):
    """Notoriety = measured attention. Three signals, in priority order:
      1. Wikipedia pageviews (best) -> log-scaled, then softly blended toward the
         tier anchor and bounded by a wide band. The blend (not a hard clamp)
         keeps scores spread continuously instead of piling at the band edges,
         while the tier still corrects two artifacts: articles about the
         underlying event/person inflate views; redirect pages read ~zero.
      2. Researched web-footprint 'reach' (for theories with no article, which is
         most of them) -> used directly; it is already a calibrated 3-92 estimate.
      3. The bare tier anchor, only if neither signal exists."""
    lad = C["att_ladder"][max(0, min(5, f.get("att", 1)))]
    if views is not None and views > 0:
        v = 100 * (math.log10(views) - C["noto_log_off"]) / C["noto_log_div"]
        bl = C["noto_pv_blend"]
        v = bl * v + (1 - bl) * lad
        # Asymmetric: NO upper ceiling (trust genuinely high pageviews, so scores
        # spread continuously instead of piling at a band edge), but keep a lower
        # floor so a famous theory whose article link is a broken redirect reading
        # ~0 views can't be tanked below its tier.
        v = max(lad - C["noto_pv_band"], v)
        return max(1, min(100, int(round(v))))
    if reach is not None:
        return max(1, min(100, int(round(reach))))
    return lad


def score_theory(t, f, views, reach, C):
    """Attach computed scores + transparent breakdown to theory dict t.
    Frame records (metaphysical frameworks) use the plausibility axis; all
    others use the historical Bayesian truth axis."""
    imp = impact_of(f, C)
    noto = noto_of(f, views, reach, C)
    t["truth_manual"], t["impact_manual"], t["notoriety_manual"] = t["truth"], t["impact"], t["notoriety"]
    t["impact"], t["notoriety"] = imp, noto
    if f.get("frame"):
        ped, coh, par, srcs, logit, plaus = frame_terms(t, f, C)
        t["truth"] = plaus
        t["truth_kind"] = "frame"
        t["score"] = {
            "kind": "frame", "cls": f["cls"],
            "ped": [f.get("ped", 2), ped], "coh": [f.get("coh", 2), coh], "par": [f.get("par", 2), par],
            "src": srcs, "logit": logit, "ceiling": C["frame_ceiling"],
            "if": [f["scale"], f["sev"], f["reach"]], "pv": views, "reach": reach, "att": f.get("att"),
        }
        return
    prior, mmo, ev, leak, logit, truth = truth_terms(t, f, C)
    t["truth"] = truth
    t["truth_kind"] = "fact"
    t["score"] = {
        "kind": "fact", "cls": f["cls"], "imp": bool(f.get("imp")),
        "prior": prior, "mmo": mmo,
        "ev": ev, "leak": leak, "logit": logit,
        "if": [f["scale"], f["sev"], f["reach"]],
        "pv": views, "reach": reach, "att": f.get("att"),
    }


def load_factors():
    F = {}
    for fp in sorted(glob.glob(os.path.join(ROOT, "data", "factors", "fact_*.json"))):
        for r in json.load(io.open(fp, encoding="utf-8")):
            F[r["id"]] = r
    # frame overlays add frame/ped/coh/par onto the matching factor record
    for fp in sorted(glob.glob(os.path.join(ROOT, "data", "frames", "frame_*.json"))):
        for r in json.load(io.open(fp, encoding="utf-8")):
            if r["id"] in F:
                F[r["id"]].update({k: v for k, v in r.items() if k != "id"})
    # MMO overlays add means/motive/opp onto the matching factor record
    for fp in sorted(glob.glob(os.path.join(ROOT, "data", "mmo", "mmo_*.json"))):
        for r in json.load(io.open(fp, encoding="utf-8")):
            if r["id"] in F:
                F[r["id"]].update({k: v for k, v in r.items() if k != "id"})
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
