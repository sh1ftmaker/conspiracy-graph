# Intake worker (anonymous submission queue)

A Cloudflare Worker + D1 database that receives anonymous theory suggestions
and edit proposals from the site and holds them in a private queue. Nothing
becomes public until a processing pass reviews it and commits overlay/batch
files to the repo.

## One-time setup

```sh
cd worker
npx wrangler login                                   # browser OAuth
npx wrangler d1 create conspiracy_queue              # paste database_id into wrangler.toml
npx wrangler d1 execute conspiracy_queue --remote --file=schema.sql
npx wrangler secret put IP_SALT                      # any long random string
npx wrangler secret put TURNSTILE_SECRET             # dash.cloudflare.com -> Turnstile (optional but recommended)
npx wrangler deploy                                  # note the *.workers.dev URL
```

Then set `INTAKE_URL` (the workers.dev URL) and `TURNSTILE_KEY` (site key) in
the three `docs/*.html` pages.

## Safety model

- Nothing user-submitted ever goes live automatically; this queue is a private
  moderation buffer. The site only changes via reviewed commits.
- Turnstile (invisible bot check) + honeypot field + minimum-fill-time.
- Per-IP rate limit (5/hour) and global cap (2000/day). IPs are stored only as
  salted truncated hashes, used for rate limiting, never published.
- Hard field length caps; HTML stripped; only http(s) URLs accepted.
- Kill switch: `npx wrangler deploy --var DISABLED:1` (or edit wrangler.toml).

## Processing the queue

```sh
# list pending
npx wrangler d1 execute conspiracy_queue --remote --json \
  --command "SELECT * FROM submissions WHERE status='pending' ORDER BY id"

# after review, mark each row
npx wrangler d1 execute conspiracy_queue --remote \
  --command "UPDATE submissions SET status='accepted', note='<commit sha>' WHERE id=42"
```

Review flow: verify cited sources actually support the claim, dedupe new
suggestions against the atlas via embedding similarity (same machinery as
`src/apply_dedup.py`'s candidate generation), then write accepted items as
`data/research/*.json` overlays (edits) or `data/enriched/community_*.json`
entries (new theories) and rebuild.

Submitters get an id back ("suggestion #N"); `GET /status?id=N` returns only
`pending / accepted / rejected` so anonymous contributors can track outcomes
without anything being exposed.
