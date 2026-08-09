"""Device-class split of landing-page traffic + tap rates.

Answers ENG-001: what share of paid clicks are desktop (where sms: links are
inert) and does that class convert materially worse?

Tables:
  hal_page_hits   — one row per page view; user_agent, utm_source, visitor_hash
  hal_funnel_events — one row per tap; visitor_hash, event_type

visitor_hash is sha256(ip|user_agent|utc_day), truncated to 16 chars. Joins
only work within the same UTC day — cross-day taps are not counted, but taps
typically happen within seconds of the page view so the loss is negligible.

Usage:
  python3 eng/scripts/device_traffic.py [--days N]  (default: all available)
  DATABASE_URL=postgres://... python3 eng/scripts/device_traffic.py  (skip Railway fetch)
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _db_url() -> str:
    if (url := os.environ.get("DATABASE_URL")):
        url = re.sub(r"postgres(ql)?(\+asyncpg)?://", "postgresql://", url)
        return url.replace("postgres.railway.internal:5432", "yamanote.proxy.rlwy.net:11694")
    out = subprocess.run(
        ["railway", "variables", "--service", "hal-orchestrator", "--kv"],
        cwd=REPO, capture_output=True, text=True, check=True,
    ).stdout
    url = next(l.split("=", 1)[1] for l in out.splitlines() if l.startswith("DATABASE_URL="))
    url = re.sub(r"postgres(ql)?(\+asyncpg)?://", "postgresql://", url)
    return url.replace("postgres.railway.internal:5432", "yamanote.proxy.rlwy.net:11694")


# ---------------------------------------------------------------------------
# Device classification
# ---------------------------------------------------------------------------

def classify_ua(ua: str | None) -> str:
    """Return 'mobile', 'tablet', or 'desktop' from a User-Agent string."""
    if not ua:
        return "desktop"
    ua_lc = ua.lower()
    # Tablets first — iPad/Android tablets often carry "Mobile" as well
    if "ipad" in ua_lc or "tablet" in ua_lc:
        return "tablet"
    # Android without Mobile keyword = Android tablet
    if "android" in ua_lc and "mobile" not in ua_lc:
        return "tablet"
    if "mobile" in ua_lc:
        return "mobile"
    return "desktop"


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------

async def run(days: int | None) -> None:
    try:
        import asyncpg
    except ImportError:
        sys.exit("asyncpg not installed — run: pip install asyncpg")

    db = _db_url()
    conn = await asyncpg.connect(db, timeout=20)
    try:
        window_clause = "AND created_at > now() - make_interval(days => $1)" if days else ""
        params_hits = [days] if days else []

        # Fetch all non-bot / hits with user_agent + utm_source
        hits = await conn.fetch(
            f"""
            SELECT user_agent, utm_source, visitor_hash, DATE(created_at) AS day
            FROM hal_page_hits
            WHERE path = '/' AND NOT is_bot
            {window_clause}
            ORDER BY created_at
            """,
            *params_hits,
        )

        # Fetch all sms_tap events in the same window
        taps = await conn.fetch(
            f"""
            SELECT visitor_hash, DATE(created_at) AS day
            FROM hal_funnel_events
            WHERE event_type = 'sms_tap'
              AND utm_source != 'verify-test'
            {window_clause}
            """,
            *params_hits,
        )
    finally:
        await conn.close()

    # Build tap lookup: (visitor_hash, day) -> True
    tap_set: set[tuple[str, object]] = {(r["visitor_hash"], r["day"]) for r in taps}

    # Counts per device class
    classes = ["mobile", "tablet", "desktop"]
    hits_total: dict[str, int] = {c: 0 for c in classes}
    hits_google: dict[str, int] = {c: 0 for c in classes}
    taps_total: dict[str, int] = {c: 0 for c in classes}
    taps_google: dict[str, int] = {c: 0 for c in classes}

    for row in hits:
        dev = classify_ua(row["user_agent"])
        key = (row["visitor_hash"], row["day"])
        is_google = (row["utm_source"] or "").lower() == "google"
        tapped = key in tap_set

        hits_total[dev] += 1
        if is_google:
            hits_google[dev] += 1
        if tapped:
            taps_total[dev] += 1
            if is_google:
                taps_google[dev] += 1

    grand_total = sum(hits_total.values())
    grand_google = sum(hits_google.values())
    grand_taps = sum(taps_total.values())
    grand_taps_google = sum(taps_google.values())

    # ---------------------------------------------------------------------------
    # Report
    # ---------------------------------------------------------------------------
    window_desc = f"last {days} days" if days else "full available window"
    print(f"\n=== ENG-001 Device Traffic Report ({window_desc}) ===\n")

    print(f"Total non-bot landing hits: {grand_total}")
    print(f"Of which utm_source=google: {grand_google}")
    print(f"Total sms_tap events (excl. verify-test): {grand_taps}")
    print(f"Of which utm_source=google: {grand_taps_google}")
    print()

    print(f"{'Device':<10} {'All hits':>10} {'%':>6}  {'Google hits':>12} {'%':>6}  "
          f"{'All taps':>9} {'tap%':>7}  {'G taps':>7} {'G tap%':>8}")
    print("-" * 85)
    for dev in classes:
        h = hits_total[dev]
        hg = hits_google[dev]
        t = taps_total[dev]
        tg = taps_google[dev]
        pct = h / grand_total * 100 if grand_total else 0
        gpct = hg / grand_google * 100 if grand_google else 0
        tap_rate = t / h * 100 if h else 0
        gtap_rate = tg / hg * 100 if hg else 0
        print(f"{dev:<10} {h:>10,} {pct:>5.1f}%  {hg:>12,} {gpct:>5.1f}%  "
              f"{t:>9,} {tap_rate:>6.1f}%  {tg:>7,} {gtap_rate:>7.1f}%")
    print("-" * 85)
    print(f"{'TOTAL':<10} {grand_total:>10,} {'100%':>6}  {grand_google:>12,} {'100%':>6}  "
          f"{grand_taps:>9,} {grand_taps/grand_total*100 if grand_total else 0:>6.1f}%  "
          f"{grand_taps_google:>7,} "
          f"{grand_taps_google/grand_google*100 if grand_google else 0:>7.1f}%")
    print()

    # Recommendation logic
    desktop_pct = hits_google.get("desktop", 0) / grand_google * 100 if grand_google else 0
    desktop_taps_google = taps_google.get("desktop", 0)
    mobile_tap_rate = taps_total["mobile"] / hits_total["mobile"] * 100 if hits_total["mobile"] else 0
    desktop_tap_rate = taps_total["desktop"] / hits_total["desktop"] * 100 if hits_total["desktop"] else 0

    print("=== Recommendation ===")
    print()
    if grand_google < 10:
        print(f"INCONCLUSIVE — only {grand_google} paid clicks total. Sample too small to derive "
              f"rates. Re-run after the campaign resumes and more data accumulates.")
    elif desktop_pct >= 15 and desktop_tap_rate < mobile_tap_rate * 0.5:
        print(f"BUILD THE DESKTOP PATH — desktop is {desktop_pct:.0f}% of paid clicks "
              f"and taps at {desktop_tap_rate:.1f}% vs {mobile_tap_rate:.1f}% for mobile. "
              f"A QR code encoding the prefilled sms: URI would let desktop visitors "
              f"scan with their phone. No external library needed (server-side SVG or "
              f"a free-tier Google Charts API call).")
    elif desktop_pct < 5:
        print(f"DROP THE THEORY — desktop is only {desktop_pct:.0f}% of paid clicks. "
              f"Not worth building a desktop-specific path. Focus on mobile conversion instead.")
    else:
        print(f"MONITOR — desktop is {desktop_pct:.0f}% of paid clicks. "
              f"Tap rate gap (desktop {desktop_tap_rate:.1f}% vs mobile {mobile_tap_rate:.1f}%) "
              f"{'does' if desktop_tap_rate < mobile_tap_rate else 'does not'} suggest desktop "
              f"is converting worse, but sample size ({hits_google.get('desktop', 0)} desktop "
              f"paid clicks) is not large enough to act on confidently.")

    print()
    print("Notes:")
    print("  - visitor_hash is day-salted (sha256(ip|ua|utc_day)). Taps only join to "
          "same-day page views. Cross-day taps (rare — typically same session) not counted.")
    print("  - Tap rate counts unique tap events, not unique tappers (a visitor who "
          "taps twice is counted twice — consistent with how sms_tap is recorded).")
    print("  - 'desktop' includes macOS where sms: opens Messages, so the rate may "
          "slightly overstate what's truly unreachable.")


def main() -> None:
    days: int | None = None
    if "--days" in sys.argv:
        idx = sys.argv.index("--days")
        days = int(sys.argv[idx + 1])
    asyncio.run(run(days))


if __name__ == "__main__":
    main()
