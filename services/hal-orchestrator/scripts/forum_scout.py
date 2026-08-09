"""forum_scout — daily DISCOVERY of family-forum threads HAL's founder can help in.

Finds fresh threads across the target subreddits matching the recurring
question patterns from BEACHHEAD.md/MARKETING.md (tracking-app recs, nanny
log syncing, 3am logging misery, Huckleberry complaints, wake-window
confusion, "when did you stop tracking"), scores them, and prints a
shortlist with the matched pattern.

This tool READS ONLY. It exists so a human spends their 30 minutes writing
genuinely helpful answers instead of hunting threads. It will never post,
comment, vote, or DM — and per MARKETING.md every answer is hand-written by
the founder with disclosure ("I built HAL because..."). Uses Reddit's public
RSS search (no credentials), one request/second, honest User-Agent.

Usage:
    uv run python scripts/forum_scout.py            # today's shortlist
    uv run python scripts/forum_scout.py --days 3   # wider window
    uv run python scripts/forum_scout.py --json     # machine-readable
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

UA = "hal-forum-scout/0.1 (read-only thread discovery; contact: hello@texthal.com)"
ATOM = "{http://www.w3.org/2005/Atom}"

# ONE OR-query per sub — Reddit's unauthenticated RSS rate limit is roughly
# 10 requests/minute per IP, so requests are precious. Pattern labels are
# assigned by content (PATTERNS below), not by which query matched.
TARGETS = [
    ("NewParents", 'tracking app OR huckleberry OR "stop tracking"'),
    ("beyondthebump", "tracking app OR baby tracker OR huckleberry"),
    ("daddit", "tracking app OR feeding log OR baby tracker"),
    ("newborns", "wake window OR tracking feeds OR tracker"),
    ("Nanny", "schedule OR daily log OR handoff"),
    ("NannyEmployers", "schedule OR log OR tracking"),
    ("sleeptrain", "wake windows OR tracking app"),
    ("workingmoms", "mental load baby OR baby tracking"),
]

PATTERNS = [
    ("huckleberry", re.compile(r"(?i)huckleberry")),
    ("nanny-sync", re.compile(r"(?i)nanny|caregiver|sitter|handoff|shift")),
    ("tracking-anxiety", re.compile(r"(?i)stop (tracking|logging)|obsess|anxiety")),
    ("wake-windows", re.compile(r"(?i)wake window")),
    ("3am-logging", re.compile(r"(?i)3 ?am|middle of the night|night feed")),
    ("mental-load", re.compile(r"(?i)mental load|default parent")),
    ("app-recs", re.compile(r"(?i)app|tracker|tracking|log")),
]

REQUEST_SPACING_S = 12.0  # well under the unauthenticated ceiling; the run
# is once-daily, so ~2 minutes of wall time is fine

# A thread is worth the founder's time when someone is actually ASKING.
_ASKING_RX = re.compile(
    r"(?i)\?|recommend|suggestion|what (app|do you use)|how do (you|y'all)|"
    r"anyone (use|found|have)|best (app|way)|help|advice|struggl|exhaust|"
    r"losing (my mind|track)|sync"
)
# Skip threads where showing up as a founder would be tone-deaf.
_SKIP_RX = re.compile(
    r"(?i)loss|nicu|emergency|er visit|hospital|grief|passed away|ppd crisis|"
    r"giveaway|promo code|my (app|startup)"
)


def fetch_rss(sub: str, query: str, _retried: bool = False) -> list[dict]:
    url = (
        f"https://www.reddit.com/r/{sub}/search.rss?"
        f"q={urllib.request.quote(query)}&restrict_sr=1&sort=new&t=month"
    )
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            root = ET.fromstring(resp.read())
    except urllib.error.HTTPError as exc:
        if exc.code == 429 and not _retried:
            print(f"  (429 from r/{sub}, backing off 45s…)", file=sys.stderr)
            time.sleep(45)
            return fetch_rss(sub, query, _retried=True)
        print(f"  ({sub} '{query}': HTTP {exc.code})", file=sys.stderr)
        return []
    except Exception as exc:  # noqa: BLE001 — one venue failing shouldn't kill the run
        print(f"  ({sub} '{query}': {exc})", file=sys.stderr)
        return []
    out = []
    for entry in root.iter(f"{ATOM}entry"):
        title = (entry.findtext(f"{ATOM}title") or "").strip()
        link = ""
        link_el = entry.find(f"{ATOM}link")
        if link_el is not None:
            link = link_el.get("href", "")
        updated = entry.findtext(f"{ATOM}updated") or ""
        content = re.sub(r"<[^>]+>", " ", entry.findtext(f"{ATOM}content") or "")
        out.append(
            {"sub": sub, "title": title, "url": link, "updated": updated,
             "snippet": " ".join(content.split())[:280]}
        )
    return out


def parse_when(iso: str) -> datetime | None:
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=7, help="max thread age")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
    seen: set[str] = set()
    hits: list[dict] = []

    for sub, query in TARGETS:
        for row in fetch_rss(sub, query):
            if row["url"] in seen:
                continue
            seen.add(row["url"])
            when = parse_when(row["updated"])
            if when is None or when < cutoff:
                continue
            text = f"{row['title']} {row['snippet']}"
            if _SKIP_RX.search(text) or not _ASKING_RX.search(text):
                continue
            row["pattern"] = next(
                (label for label, rx in PATTERNS if rx.search(text)), "general"
            )
            row["age_hours"] = round(
                (datetime.now(timezone.utc) - when).total_seconds() / 3600
            )
            hits.append(row)
        time.sleep(REQUEST_SPACING_S)

    hits.sort(key=lambda r: r["age_hours"])

    if args.json:
        print(json.dumps(hits, indent=1))
        return 0

    if not hits:
        print(f"No matching threads in the last {args.days} day(s).")
        return 0
    print(f"{len(hits)} thread(s) worth a look (newest first):\n")
    for r in hits:
        print(f"[{r['pattern']}] r/{r['sub']} — {r['age_hours']}h ago")
        print(f"  {r['title']}")
        print(f"  {r['url']}")
        if r["snippet"]:
            print(f"  » {r['snippet'][:160]}")
        print()
    print(
        "Reminder: answer the question first, fully, in your own words. "
        "Mention HAL only when directly relevant, ALWAYS with founder "
        "disclosure. ≤1 mention per 5-6 contributions (MARKETING.md)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
