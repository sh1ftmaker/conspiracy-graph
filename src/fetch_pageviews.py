#!/usr/bin/env python3
"""Fetch 12-month Wikipedia pageview totals for every theory with an
en.wikipedia.org link, for measured Notoriety scoring.

Uses the Wikimedia REST pageviews API (no key; requires a descriptive UA).
Resumable: existing entries in data/pageviews.json are kept unless --refresh.

Usage:  python src/fetch_pageviews.py
"""
import json, os, sys, time, io
import urllib.request, urllib.parse, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "docs", "data.json")
OUT = os.path.join(ROOT, "data", "pageviews.json")
UA = {"User-Agent": "conspiracy-atlas/1.0 (https://sh1ftmaker.github.io/conspiracy-atlas/; shiftmaker@gmail.com)"}
# last 12 complete months as of 2026-07
SPAN = ("2025060100", "2026053100")


def wiki_title(url):
    """en.wikipedia.org/wiki/<Title> -> Title (None for other hosts/shapes)."""
    try:
        u = urllib.parse.urlparse(url)
    except Exception:
        return None
    if u.netloc not in ("en.wikipedia.org", "en.m.wikipedia.org"):
        return None
    if not u.path.startswith("/wiki/"):
        return None
    t = u.path[len("/wiki/"):]
    t = t.split("#")[0].split("?")[0]
    return urllib.parse.unquote(t) if t else None


def fetch_views(title):
    """Total user pageviews across SPAN, or None on API failure/404."""
    q = urllib.parse.quote(title.replace(" ", "_"), safe="")
    url = (f"https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
           f"en.wikipedia/all-access/user/{q}/monthly/{SPAN[0]}/{SPAN[1]}")
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
            items = json.load(r).get("items", [])
        return sum(it.get("views", 0) for it in items)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return 0  # article exists but no view data (or redirect-only title)
        return None
    except Exception:
        return None


def main():
    refresh = "--refresh" in sys.argv
    d = json.load(io.open(DATA, encoding="utf-8"))
    titles = {}
    for t in d["theories"]:
        w = t.get("wikipedia")
        if not w:
            continue
        title = wiki_title(w)
        if title:
            titles.setdefault(title, 0)

    cache = {}
    if os.path.exists(OUT) and not refresh:
        cache = json.load(io.open(OUT, encoding="utf-8"))

    todo = [t for t in titles if t not in cache]
    print(f"{len(titles)} distinct titles, {len(todo)} to fetch", file=sys.stderr)
    fails = 0
    for i, title in enumerate(todo):
        v = fetch_views(title)
        if v is None:
            fails += 1
        else:
            cache[title] = v
        if (i + 1) % 50 == 0:
            print(f"  {i+1}/{len(todo)} (fails={fails})", file=sys.stderr)
            io.open(OUT, "w", encoding="utf-8").write(json.dumps(cache, ensure_ascii=False, indent=0))
        time.sleep(0.12)

    io.open(OUT, "w", encoding="utf-8").write(json.dumps(cache, ensure_ascii=False, indent=0))
    print(f"done: {len(cache)} cached, {fails} failed", file=sys.stderr)


if __name__ == "__main__":
    main()
