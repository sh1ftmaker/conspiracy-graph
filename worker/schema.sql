-- Submission queue for crowdsourced theory suggestions.
-- Apply with:
--   npx wrangler d1 execute conspiracy_queue --remote --file=schema.sql
CREATE TABLE IF NOT EXISTS submissions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL CHECK (kind IN ('new', 'edit')),
  theory_id TEXT,                          -- target theory for kind='edit'
  payload TEXT NOT NULL,                   -- validated JSON (see worker/src/index.js)
  ip_hash TEXT NOT NULL,                   -- salted hash, rate limiting only
  created INTEGER NOT NULL,                -- unix seconds
  status TEXT NOT NULL DEFAULT 'pending',  -- pending | accepted | rejected | spam
  note TEXT                                -- reviewer note (why rejected, commit link, ...)
);
CREATE INDEX IF NOT EXISTS idx_status ON submissions(status);
CREATE INDEX IF NOT EXISTS idx_iphash_created ON submissions(ip_hash, created);
