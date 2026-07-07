# The Conspiracy Atlas

An interactive atlas of **1,168 conspiracy theories**, laid out by semantic
similarity and scored — transparently, by formula — on how true, how consequential,
and how well-known each one is.

### → [**Explore the live site**](https://sh1ftmaker.github.io/conspiracy-atlas/)

![The Conspiracy Atlas — 3D semantic flythrough](docs/preview.png)

## The views

All four are static pages fed by one generated `docs/data.json`:

| Page | What it is |
|---|---|
| [3D flythrough](https://sh1ftmaker.github.io/conspiracy-atlas/) (`index.html`) | Fly or orbit through the semantic point cloud; remap the X/Y/Z axes (Semantic / Truth / Impact / Notoriety / Year) and watch it morph. |
| [2D map](https://sh1ftmaker.github.io/conspiracy-atlas/2d.html) (`2d.html`) | WebGL point cloud by semantic similarity; click a point to trace its nearest neighbors. |
| [Iceberg](https://sh1ftmaker.github.io/conspiracy-atlas/iceberg.html) (`iceberg.html`) | Ten tiers from proven-fact at the surface down to deep-lore in the hadal zone. |
| [List](https://sh1ftmaker.github.io/conspiracy-atlas/list.html) (`list.html`) | Sortable, filterable table. |
| [Methodology](https://sh1ftmaker.github.io/conspiracy-atlas/methodology.html) (`methodology.html`) | How every score is computed. |

Theories are embedded with **gemini-embedding-2** (Vertex AI) and UMAP-projected, so
claims with similar actors, mechanisms or themes cluster together regardless of genre.

## Scoring, in brief

Every score comes from an explicit formula over per-theory factors, not a gut feeling —
the full derivation is on the [methodology page](https://sh1ftmaker.github.io/conspiracy-atlas/methodology.html).

- **Truth** (empirical claims) — Bayesian log-odds: `100 · σ(prior + evidence − leak)`.
  The prior is the investigator's triad **Means × Motive × Opportunity** (not genre base
  rates); evidence is each source weighted by credibility class × stance, with denials by
  the accused party heavily discounted; the leak term penalizes secrets too big to keep.
- **Plausibility** (metaphysical frameworks — idealism, simulation theory, pantheism) —
  a separate violet axis scored on pedigree + coherence + parsimony, capped short of
  certainty, because a model of reality can never be *proven*.
- **Impact** — geometric mean of scale × severity × reach (consequence if true).
- **Notoriety** — measured cultural footprint: Wikipedia pageviews where an article exists,
  otherwise a researched web-footprint score (Reddit / YouTube / news / search volume) on a
  calibrated reach scale, since most conspiracy theories will never have a Wikipedia article.

## Repository layout

```
docs/                     static site (GitHub Pages serves this)
  *.html                  the five pages
  data.json               generated dataset — do NOT hand-edit
data/
  theories.seed.json      hand-authored anchor theories
  enriched/batch_*.json   researched theories (same schema)
  research/*.json         overlay files (extra sources, steelman, precedents)
  factors/                per-theory scoring factors (class, impact, conspirators…)
  frames/                 metaphysical frame flags + pedigree/coherence/parsimony
  mmo/                    means/motive/opportunity annotations
  stances/                strict per-source stances + self-denial flags
  pageviews.json          cached Wikipedia pageviews
  SCHEMA.md               field reference
src/
  build.py                merge + validate + score everything → docs/data.json
  score.py                the scoring engine (imported by build.py)
  calibrate.py            diff formula scores vs. editorial, print band migration
  embed_theories.py       embed each theory with gemini-embedding-2 (Vertex AI)
  project_embed.py        UMAP-project embeddings → coords + neighbors in data.json
  fetch_pageviews.py      pull Wikipedia pageviews → data/pageviews.json
  taxonomy.json           genres + truth/frame/impact scale definitions
```

## Build

```bash
python src/build.py                                                  # data/* → docs/data.json (scores included)
python src/project_embed.py --emb out/embeddings.npz --data docs/data.json   # re-inject UMAP coords + neighbors
python -m http.server 8000 --directory docs                         # preview at localhost:8000
```

`src/build.py` **drops** the embedding coordinates, so always re-run `project_embed.py`
after a build. Re-embedding (`src/embed_theories.py --sa <service-account.json> --out
out/embeddings.npz`) is only needed when a theory's name/summary/evidence changed — it
requires a Vertex AI service-account JSON (never committed). Bump the `data.json?v=N`
cache string in the `docs/*.html` files whenever the data changes.

## Extend it

1. **Add theories** — drop objects matching `data/SCHEMA.md` into a new
   `data/enriched/batch_*.json` (or a `data/research/*.json` overlay to amend existing
   ones). IDs are stable slugs; cross-links resolve by ID.
2. **Make them scorable** — add the theory's factors under `data/factors/` (and
   `data/mmo/` for the Means/Motive/Opportunity prior; `data/frames/` if it is a
   metaphysical framework rather than an empirical claim).
3. **Rebuild** — run the build + project commands above, then
   `python src/calibrate.py` to see how the new scores sit against the rest.

## A note

Cataloguing a theory — including hateful or racist ones, documented as such with the
evidence against them — is not an endorsement. A high Impact score reflects what *would*
change if a claim were true, not a claim that it is.
