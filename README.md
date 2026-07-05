# The Conspiracy Atlas

An interactive atlas of conspiracy theories plotted by **how true they are** (x-axis)
against **how impactful they'd be if true** (y-axis) — plus a genre breakdown, a
formulation-year timeline, and a **load-bearing dependency graph** showing which
theories require other theories to be true.

**[Live site →](https://SolomonsBlade.github.io/conspiracy-graph/)** *(update URL after first push)*

## What's here

- `docs/index.html` — single-file canvas/WebGL-free 2D renderer (3 views: scatter, graph, timeline)
- `docs/data.json` — built dataset (generated, do not hand-edit)
- `data/theories.seed.json` — hand-authored anchor theories (evidence-scored)
- `data/enriched/batch_*.json` — subagent-researched theories, same schema
- `data/queue.json` — remaining theories queued for enrichment
- `data/SCHEMA.md` — field reference + the truth/impact scoring rubric
- `src/taxonomy.json` — genre list + truth/impact scale definitions
- `src/build.py` — merges all sources, validates, resolves cross-links, computes
  load-bearing in-degree → `docs/data.json`

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
python -m http.server 8000 --directory docs   # preview locally
```

## Extending the dataset

Add objects matching the schema in `data/SCHEMA.md` to a new file under
`data/enriched/`, or append to `data/theories.seed.json`, then rerun the build.
