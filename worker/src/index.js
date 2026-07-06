// Anonymous submission intake for The Conspiracy Atlas.
// POST /submit  -> validate + rate-limit + insert into D1, returns {ok, id}
// GET  /status?id=N -> {id, status, note?}  (no submission content exposed)

const LIMITS = {
  name: 120, text: 2000, url: 300, urls: 6, evidence: 6, evidenceItem: 500,
  perIpPerHour: 5, perDayGlobal: 2000, minFillMs: 4000, bodyBytes: 16384,
};

function cors(env, origin) {
  const allowed = (env.ALLOWED_ORIGINS || "").split(",").map(s => s.trim());
  const ok = allowed.includes(origin) ? origin : allowed[0] || "*";
  return {
    "Access-Control-Allow-Origin": ok,
    "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Vary": "Origin",
  };
}

const json = (obj, status, hdrs) =>
  new Response(JSON.stringify(obj), {
    status, headers: { "Content-Type": "application/json", ...hdrs },
  });

async function sha256hex(s) {
  const d = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return [...new Uint8Array(d)].map(b => b.toString(16).padStart(2, "0")).join("");
}

const str = (v, max) => typeof v === "string" ? v.replace(/<[^>]*>/g, "").trim().slice(0, max) : "";
const score = v => Number.isFinite(+v) ? Math.max(0, Math.min(100, Math.round(+v))) : null;

function cleanUrls(v) {
  if (!Array.isArray(v)) return [];
  return v.map(u => str(u, LIMITS.url))
    .filter(u => /^https?:\/\/[^\s]+$/.test(u) && !u.startsWith("data:"))
    .slice(0, LIMITS.urls);
}

function cleanEvidence(v) {
  if (!Array.isArray(v)) return [];
  return v.map(e => str(e, LIMITS.evidenceItem)).filter(Boolean).slice(0, LIMITS.evidence);
}

// Returns {kind, theory_id, payload} or a string error.
function validate(body) {
  const kind = body.kind === "edit" ? "edit" : body.kind === "new" ? "new" : null;
  if (!kind) return "bad kind";
  const p = body.payload || {};
  if (kind === "new") {
    const name = str(p.name, LIMITS.name);
    const claim = str(p.claim, LIMITS.text);
    if (name.length < 3 || claim.length < 20) return "name (3+ chars) and claim (20+ chars) required";
    return {
      kind, theory_id: null,
      payload: {
        name, claim,
        genre: str(p.genre, 40) || null,
        year: Number.isFinite(+p.year) ? Math.round(+p.year) : null,
        sources: cleanUrls(p.sources),
        evidence: cleanEvidence(p.evidence),
        note: str(p.note, LIMITS.text) || null,
      },
    };
  }
  const theory_id = str(body.theory_id, 120);
  if (!/^[a-z0-9-]{2,120}$/.test(theory_id)) return "bad theory_id";
  const changes = str(p.changes, LIMITS.text);
  const scores = { truth: score(p.truth), impact: score(p.impact), notoriety: score(p.notoriety) };
  const hasScores = Object.values(scores).some(v => v !== null);
  if (changes.length < 10 && !hasScores) return "describe the change (10+ chars) or propose scores";
  return {
    kind, theory_id,
    payload: {
      changes: changes || null, ...scores,
      rationale: str(p.rationale, LIMITS.text) || null,
      sources: cleanUrls(p.sources),
    },
  };
}

async function verifyTurnstile(env, token, ip) {
  if (!env.TURNSTILE_SECRET) return true; // not configured yet -> skip (pre-launch)
  if (!token) return false;
  const r = await fetch("https://challenges.cloudflare.com/turnstile/v0/siteverify", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ secret: env.TURNSTILE_SECRET, response: token, remoteip: ip }),
  });
  const d = await r.json().catch(() => ({}));
  return !!d.success;
}

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    const origin = req.headers.get("Origin") || "";
    const c = cors(env, origin);

    if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: c });

    if (req.method === "GET" && url.pathname === "/status") {
      const id = parseInt(url.searchParams.get("id") || "", 10);
      if (!Number.isFinite(id)) return json({ error: "bad id" }, 400, c);
      const row = await env.DB.prepare("SELECT id, status, note FROM submissions WHERE id=?")
        .bind(id).first();
      if (!row) return json({ error: "not found" }, 404, c);
      return json(row, 200, c);
    }

    if (req.method === "POST" && url.pathname === "/submit") {
      if (env.DISABLED === "1") return json({ error: "submissions are paused" }, 503, c);

      const raw = await req.text();
      if (raw.length > LIMITS.bodyBytes) return json({ error: "too large" }, 413, c);
      let body;
      try { body = JSON.parse(raw); } catch { return json({ error: "bad json" }, 400, c); }

      // honeypot + minimum fill time (dumb-bot filters)
      if (body.website) return json({ ok: true, id: 0 }, 200, c); // pretend success
      if (!(+body.elapsedMs >= LIMITS.minFillMs)) return json({ error: "too fast" }, 400, c);

      const ip = req.headers.get("CF-Connecting-IP") || "0.0.0.0";
      if (!(await verifyTurnstile(env, body.turnstile, ip)))
        return json({ error: "bot check failed" }, 403, c);

      const v = validate(body);
      if (typeof v === "string") return json({ error: v }, 400, c);

      const ipHash = (await sha256hex(ip + (env.IP_SALT || "salt"))).slice(0, 32);
      const now = Math.floor(Date.now() / 1000);

      const perIp = await env.DB.prepare(
        "SELECT COUNT(*) n FROM submissions WHERE ip_hash=? AND created>?")
        .bind(ipHash, now - 3600).first();
      if (perIp.n >= LIMITS.perIpPerHour)
        return json({ error: "rate limit: try again in an hour" }, 429, c);

      const perDay = await env.DB.prepare(
        "SELECT COUNT(*) n FROM submissions WHERE created>?")
        .bind(now - 86400).first();
      if (perDay.n >= LIMITS.perDayGlobal)
        return json({ error: "queue is full for today" }, 429, c);

      const res = await env.DB.prepare(
        "INSERT INTO submissions (kind, theory_id, payload, ip_hash, created) VALUES (?,?,?,?,?)")
        .bind(v.kind, v.theory_id, JSON.stringify(v.payload), ipHash, now).run();

      return json({ ok: true, id: res.meta.last_row_id }, 200, c);
    }

    return json({ error: "not found" }, 404, c);
  },
};
