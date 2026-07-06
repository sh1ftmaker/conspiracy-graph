# The Conspiracy Atlas

An interactive atlas of 1000+ conspiracy theories. Two views, both fed by the same
dataset:

- **[3D flythrough](https://sh1ftmaker.github.io/conspiracy-atlas/)** (`docs/index.html`, front page)
  — fly (WASD + mouse-look) or orbit through the semantic point cloud in 3D;
  remap the X/Y/Z axes (Semantic / Truth / Impact / Notoriety / Year) and watch
  the cloud morph between layouts.
- **[2D semantic map](https://sh1ftmaker.github.io/conspiracy-atlas/2d.html)** (`docs/2d.html`)
  — a WebGL point-cloud laid out by semantic similarity (embedded with
  **gemini-embedding-2**, UMAP-projected): theories with similar claims, actors or
  themes cluster together regardless of genre or truth. Pan/pinch/zoom, click a
  point to trace its nearest neighbors in full embedding space.
  unlisted) — the tabbed Three.js scene: Truth × Impact scatter, load-bearing
  dependency graph, formulation-year Timeline, Semantic space.

## What's here

- `docs/index.html` — 3D Three.js flythrough of the semantic cloud (front page)
- `docs/2d.html` — 2D WebGL semantic map
- `docs/data.json` — built dataset incl. embedding coordinates (generated, do not hand-edit)
- `data/theories.seed.json` — hand-authored anchor theories (evidence-scored)
- `data/enriched/batch_*.json` — subagent-researched theories, same schema
- `data/SCHEMA.md` — field reference + the truth/impact scoring rubric
- `src/taxonomy.json` — genre list + truth/impact scale definitions
- `src/build.py` — merges all sources, validates, resolves cross-links, computes
  load-bearing in-degree → `docs/data.json`
- `src/embed_theories.py` — embeds every theory (name + summary + evidence) with
  **gemini-embedding-2** via Vertex AI (needs a service-account JSON with the
  Vertex AI API enabled; not committed to this repo)
- `src/project_embed.py` — UMAP-projects the embeddings to 2D/3D and writes
  `ex/ey/ex3/ey3/ez3` + nearest-neighbor ids (`nn`) onto each theory in `docs/data.json`

## Methodology

Each theory is scored 0–100 on two independent axes:

- **Truth**: 0 = debunked, 50 = contested/unfalsifiable, 100 = confirmed historical
  fact (proven in court, declassified, or admitted). Many entries here score
  90–100 — MKUltra, COINTELPRO, Watergate, Iran–Contra, NSA mass surveillance,
  Tuskegee — because a real conspiracy IS a conspiracy theory that turned out
  to be true.
- **Impact**: how much the world would change if the theory were true, regardless
  of truth. A civilization-defining but false theory (flat Earth) can outscore a
  true but narrow one (a rigged sports match) on this axis.

**Load-bearing** theories are ones that other theories cite as a prerequisite
(`depends_on`). E.g. QAnon depends on "the deep state" being real; if the deep
state premise collapses, so does everything built on it. In-degree over this
edge set = how foundational a theory is; these are the largest nodes in the
graph view.

Sources: Wikipedia's [List of conspiracy theories](https://en.wikipedia.org/wiki/List_of_conspiracy_theories),
Wikidata (`wd:Q159535`), and targeted research agents. Cataloguing a theory —
including hateful or racist ones (documented as such, with evidence against) —
is not an endorsement.

## Rebuilding

```
python src/build.py      # regenerates docs/data.json from data/*.json
python src/embed_theories.py --sa <path-to-sa.json> --out out/embeddings.npz   # re-embed (only needed if theories changed)
python src/project_embed.py --emb out/embeddings.npz --data docs/data.json    # re-project + write coords into docs/data.json
python -m http.server 8000 --directory docs   # preview locally
```

## Extending the dataset

Add objects matching the schema in `data/SCHEMA.md` to a new file under
`data/enriched/`, or append to `data/theories.seed.json`, then rerun the build.
