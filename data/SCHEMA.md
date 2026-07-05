# Theory record schema & scoring rubric

Every theory is one object in `data/theories.json`. Fields:

| field | type | notes |
|---|---|---|
| `id` | string | kebab-case slug, unique, stable. |
| `name` | string | Display name. |
| `aliases` | string[] | Other names / spellings. |
| `genre` | enum | One key from `src/taxonomy.json.genres`. |
| `year` | int | Year the theory was **formulated / first popularized** (not the year of the event it concerns). |
| `truth` | int 0–100 | Plausibility / verification. See rubric below. |
| `impact` | int 0–100 | If it were TRUE, how world-altering. See rubric. |
| `notoriety` | int 0–100 | How widely known (drives point size). |
| `summary` | string | 1–3 sentence neutral description of the claim. |
| `evidence_for` | string[] | Points cited by proponents / genuine anomalies. |
| `evidence_against` | string[] | Debunkings, refutations, mainstream explanation. |
| `related` | string[] | ids of thematically related theories (undirected). |
| `depends_on` | string[] | ids this theory **requires to be true** (load-bearing, directed). |
| `wikidata` | string? | Q-id if known. |
| `wikipedia` | string? | URL if known. |

## Truth rubric (X axis)
- **0–10 Debunked** — flat earth, moon-landing hoax, reptilians.
- **11–30 Fringe** — no credible evidence (chemtrails, Finland doesn't exist).
- **31–55 Contested** — real open questions / unfalsifiable (JFK second gunman, Epstein death).
- **56–75 Plausible** — strong circumstantial record (CIA & crack, Gary Webb).
- **76–90 Substantiated** — largely borne out (Operation Mockingbird scope).
- **91–100 Confirmed** — proven fact: MKUltra, Tuskegee, COINTELPRO, Gulf of Tonkin, Iran-Contra, NSA mass surveillance (PRISM), Big Tobacco, Business Plot, Operation Northwoods (proposed), Watergate.

## Impact rubric (Y axis) — *if the theory were true*
- **0–20 Trivial/local** — a single celebrity is a body double.
- **21–45 Limited** — one industry lied (still serious, bounded).
- **46–70 National/major** — a government murdered a leader; a war was started on a lie.
- **71–90 Global** — mass covert control of populations; shared history is falsified.
- **91–100 Reality-defining** — the planet, species, or nature of reality is a lie.

## Load-bearing / `depends_on`
A theory is *load-bearing* for others when many theories list it in their `depends_on`.
Example chains: `chemtrails → mass-govt-secrecy`; `qanon → deep-state → ...`.
In-degree over `depends_on` edges = how foundational a theory is (rendered larger/central in the graph view).
