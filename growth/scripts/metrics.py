"""Daily growth scoreboard: ad spend (Google Ads + Meta) x new households (hal_turns).

Writes growth/reports/scoreboard-<date>.md and growth/state/metrics-latest.json.
DB URL is pulled at runtime from Railway (never persisted).
"""
import asyncio
import datetime as dt
import json
import os
import pathlib
import re
import ssl
import subprocess
import urllib.parse
import urllib.request

import asyncpg
import certifi
from google.ads.googleads.client import GoogleAdsClient

REPO = pathlib.Path("/Users/adnanakil/Project/agentlist")
CUSTOMER_ID = "4959722800"
DAYS = 14
META_AD_ACCOUNT = "act_40885463"
META_API_VERSION = "v21.0"
META_API_BASE = f"https://graph.facebook.com/{META_API_VERSION}"

# Monitoring/verify probe UAs that produce is_bot=False and must be excluded
# from landing-view counts. Add new probe UAs here; they are SQL literals (not
# user input) so embedding them directly in the query is safe.
_PROBE_UA_EXACT: tuple[str, ...] = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Version/17.0 Mobile Safari",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/120 Mobile",
)
_PROBE_UA_ILIKE: tuple[str, ...] = (
    "%Verify/%",
    "%facebookexternalhit%",
    "%eng-verify-bot%",
)


def _load_growth_env() -> None:
    """Load ~/.growth-env into os.environ when running outside supervisor context.

    No-ops immediately if META_ACCESS_TOKEN is already set (supervisor already
    sourced the file).  Otherwise reads ~/.growth-env line by line, strips an
    optional leading ``export `` prefix, parses ``KEY=VALUE`` pairs (ignoring
    blank lines and comments), and sets each key in os.environ only if it is not
    already present.  Simple quoted values (matching outer ``"…"`` or ``'…'``)
    are unquoted before storing.
    """
    if os.environ.get("META_ACCESS_TOKEN"):
        return  # already available — supervisor sourced ~/.growth-env

    env_path = pathlib.Path.home() / ".growth-env"
    if not env_path.exists():
        return

    with env_path.open() as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            # Strip optional leading "export "
            if line.startswith("export "):
                line = line[len("export "):]
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            # Strip matching outer quotes
            if len(value) >= 2 and value[0] in ('"', "'") and value[-1] == value[0]:
                value = value[1:-1]
            if key and key not in os.environ:
                os.environ[key] = value


def db_url() -> str:
    out = subprocess.run(
        ["railway", "variables", "--service", "hal-orchestrator", "--kv"],
        cwd=REPO, capture_output=True, text=True, check=True,
    ).stdout
    url = next(l.split("=", 1)[1] for l in out.splitlines() if l.startswith("DATABASE_URL="))
    url = re.sub(r"postgres(ql)?(\+asyncpg)?://", "postgresql://", url)
    return url.replace("postgres.railway.internal:5432", "yamanote.proxy.rlwy.net:11694")


async def households() -> tuple[int, dict[str, int], dict[str, int], dict[str, int], int]:
    conn = await asyncpg.connect(db_url(), timeout=20)
    try:
        rows = await conn.fetch(
            """
            WITH first_seen AS (
              SELECT phone, MIN(created_at) AS first_at FROM hal_turns
              WHERE phone NOT LIKE '%1555555%' GROUP BY phone
            )
            SELECT date(first_at) AS day, COUNT(*) AS n FROM first_seen
            WHERE first_at > now() - make_interval(days => $1)
            GROUP BY 1 ORDER BY 1""",
            DAYS,
        )
        total = await conn.fetchval(
            "SELECT COUNT(DISTINCT phone) FROM hal_turns WHERE phone NOT LIKE '%1555555%'"
        )
        # Ground-truth attribution: ?c=<code> -> sms prefill "(code)" -> HAL
        # records acquisition_source on the profile. NULL = organic/unknown.
        src_rows = await conn.fetch(
            """
            WITH first_seen AS (
              SELECT phone, MIN(created_at) AS first_at FROM hal_turns
              WHERE phone NOT LIKE '%1555555%' GROUP BY phone
            )
            SELECT COALESCE(p.extra_data->>'acquisition_source', 'organic/unknown') AS src,
                   COUNT(*) AS n
            FROM first_seen f
            LEFT JOIN hal_user_profiles p ON p.phone = f.phone
            WHERE f.first_at > now() - make_interval(days => $1)
            GROUP BY 1 ORDER BY n DESC""",
            DAYS,
        )
        # Build probe-UA exclusion clause from module-level constants.
        # Exact-match literals joined with OR; ILIKE patterns likewise.
        # Null user_agent rows are always counted (user_agent IS NULL short-circuits).
        _exact_sql = " OR ".join(
            f"user_agent = $${ua}$$" for ua in _PROBE_UA_EXACT
        )
        _ilike_sql = " OR ".join(
            f"user_agent ILIKE $${pat}$$" for pat in _PROBE_UA_ILIKE
        )
        _probe_clause = f"({_exact_sql} OR {_ilike_sql})"
        view_rows = await conn.fetch(
            f"""
            SELECT date(created_at) AS day, COUNT(*) AS n FROM hal_page_hits
            WHERE path = '/' AND NOT is_bot
              AND (utm_source IS NULL OR utm_source != 'verify-test')
              AND (user_agent IS NULL OR NOT {_probe_clause})
              AND created_at > now() - make_interval(days => $1)
            GROUP BY 1 ORDER BY 1""",
            DAYS,
        )
        # SMS tap events — hal_funnel_events may not exist before migration 033.
        try:
            tap_total = await conn.fetchval(
                """
                SELECT COUNT(*) FROM hal_funnel_events
                WHERE event_type = 'sms_tap'
                  AND (utm_source IS NULL OR utm_source != 'verify-test')
                  AND created_at > now() - make_interval(days => $1)""",
                DAYS,
            )
        except asyncpg.exceptions.UndefinedTableError:
            tap_total = None
    finally:
        await conn.close()
    return (
        total,
        {str(r["day"]): r["n"] for r in rows},
        {r["src"]: r["n"] for r in src_rows},
        {str(r["day"]): r["n"] for r in view_rows},
        tap_total,
    )


def google_spend() -> dict[str, dict]:
    """Return Google Ads spend by day for the DAYS window."""
    client = GoogleAdsClient.load_from_storage("/Users/adnanakil/google-ads.yaml")
    ga = client.get_service("GoogleAdsService")
    end = dt.date.today()
    start = end - dt.timedelta(days=DAYS - 1)
    by_day: dict[str, dict] = {}
    for r in ga.search(
        customer_id=CUSTOMER_ID,
        query=f"""
        SELECT segments.date, campaign.id, campaign.name, metrics.impressions,
               metrics.clicks, metrics.cost_micros
        FROM campaign
        WHERE segments.date BETWEEN '{start:%Y-%m-%d}' AND '{end:%Y-%m-%d}'""",
    ):
        d = by_day.setdefault(
            r.segments.date, {"impressions": 0, "clicks": 0, "cost_usd": 0.0}
        )
        d["impressions"] += r.metrics.impressions
        d["clicks"] += r.metrics.clicks
        d["cost_usd"] += r.metrics.cost_micros / 1e6
    return by_day


def meta_spend(token: str, days: int) -> dict[str, float]:
    """Return Meta Ads spend by day for the given number of days.

    Returns {date_str: spend_usd}. Degrades gracefully on error (returns {}).
    Token must NOT appear in URLs — sent via Authorization header only.
    """
    if not token:
        print("WARNING: META_ACCESS_TOKEN not set — Meta spend data unavailable")
        return {}

    end = dt.date.today()
    since = end - dt.timedelta(days=days - 1)
    # Use date range via time_range param; time_increment=1 gives one row per day
    time_range = json.dumps({"since": str(since), "until": str(end)})
    params = {
        "fields": "spend,date_start",
        "time_increment": "1",
        "time_range": time_range,
    }
    url = f"{META_API_BASE}/{META_AD_ACCOUNT}/insights?{urllib.parse.urlencode(params)}"
    ctx = ssl.create_default_context(cafile=certifi.where())
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            data = json.loads(resp.read().decode())
    except Exception as exc:
        print(f"WARNING: Meta Graph API request failed — {exc}. Meta spend data unavailable.")
        return {}

    if "error" in data:
        err = data["error"]
        print(
            f"WARNING: Meta Graph API error — {err.get('message', data['error'])} "
            f"(code {err.get('code', '?')}). Token may be expired. Meta spend data unavailable."
        )
        return {}

    result: dict[str, float] = {}
    for row in data.get("data", []):
        date_str = row.get("date_start", "")
        spend = float(row.get("spend", 0))
        if date_str:
            result[date_str] = result.get(date_str, 0.0) + spend
    return result


def ad_spend() -> dict[str, dict]:
    """Return combined Google + Meta spend by day.

    Returns {date: {"impressions": N, "clicks": N, "cost_usd": X, "meta_cost_usd": Y}}
    where cost_usd is Google spend and meta_cost_usd is Meta spend (0.0 if unavailable).
    """
    g_spend = google_spend()

    _load_growth_env()  # no-op if already set; guards direct callers that bypass main()
    meta_token = os.environ.get("META_ACCESS_TOKEN")
    m_spend = meta_spend(meta_token, DAYS) if meta_token else {}

    # Collect all dates from either source
    all_dates = set(g_spend.keys()) | set(m_spend.keys())
    by_day: dict[str, dict] = {}
    for date_str in all_dates:
        g = g_spend.get(date_str, {"impressions": 0, "clicks": 0, "cost_usd": 0.0})
        by_day[date_str] = {
            "impressions": g["impressions"],
            "clicks": g["clicks"],
            "cost_usd": g["cost_usd"],
            "meta_cost_usd": m_spend.get(date_str, 0.0),
        }
    return by_day


def main():
    _load_growth_env()
    total_households, new_by_day, new_by_source, views_by_day, tap_total = asyncio.run(households())
    spend_by_day = ad_spend()
    today = dt.date.today()
    days = [str(today - dt.timedelta(days=i)) for i in range(DAYS - 1, -1, -1)]

    window_google_spend = sum(d["cost_usd"] for d in spend_by_day.values())
    window_meta_spend = sum(d.get("meta_cost_usd", 0.0) for d in spend_by_day.values())
    window_spend = window_google_spend + window_meta_spend
    window_clicks = sum(d["clicks"] for d in spend_by_day.values())
    window_new = sum(new_by_day.get(d, 0) for d in days)
    window_views = sum(views_by_day.get(d, 0) for d in days)
    naive_cpa = window_spend / window_new if window_new else None
    by_source = ", ".join(f"{src}: {n}" for src, n in new_by_source.items()) or "none"
    tap_rate = (f"**{tap_total / window_views:.2%}** ({tap_total} taps)" if tap_total and window_views else
                "n/a (EXP-001 not yet live)" if tap_total is None else "0 taps recorded")

    lines = [
        f"# Growth scoreboard — {today}",
        "",
        f"- Total households ever: **{total_households}**",
        f"- Last {DAYS}d: **{window_new} new households**, ${window_google_spend:.2f} Google ad spend, "
        f"${window_meta_spend:.2f} Meta ad spend, "
        f"{window_clicks} paid clicks",
        f"- New households by acquisition source (last {DAYS}d): {by_source}",
        f"- Landing views (human, path=/) last {DAYS}d: **{window_views}** → "
        "view→household rate "
        + (f"**{window_new / window_views:.2%}**" if window_views else "n/a"),
        f"- SMS-link tap rate (last {DAYS}d): {tap_rate}",
        f"- Naive CPA (spend/new, organic mixed in): "
        + (f"**${naive_cpa:.2f}**" if naive_cpa is not None else "n/a (0 new)"),
        "",
        "| day | ad spend | meta spend | impr | clicks | landing views | new households |",
        "|-----|----------|------------|------|--------|---------------|----------------|",
    ]
    for d in days:
        s = spend_by_day.get(d, {"impressions": 0, "clicks": 0, "cost_usd": 0.0, "meta_cost_usd": 0.0})
        lines.append(
            f"| {d} | ${s['cost_usd']:.2f} | ${s.get('meta_cost_usd', 0.0):.2f} "
            f"| {s['impressions']} | {s['clicks']} "
            f"| {views_by_day.get(d, 0)} | {new_by_day.get(d, 0)} |"
        )
    md = "\n".join(lines) + "\n"

    (REPO / "growth/reports" / f"scoreboard-{today}.md").write_text(md)
    (REPO / "growth/state/metrics-latest.json").write_text(
        json.dumps(
            {
                "date": str(today),
                "total_households": total_households,
                "window_days": DAYS,
                "window_new_households": window_new,
                "window_google_spend_usd": round(window_google_spend, 2),
                "window_meta_spend_usd": round(window_meta_spend, 2),
                "window_spend_usd": round(window_spend, 2),
                "window_clicks": window_clicks,
                "window_landing_views": window_views,
                "window_sms_taps": tap_total,
                "new_by_source": new_by_source,
                "views_by_day": views_by_day,
                "naive_cpa_usd": round(naive_cpa, 2) if naive_cpa is not None else None,
                "new_by_day": new_by_day,
                "spend_by_day": {
                    k: {
                        **{kk: vv for kk, vv in v.items() if kk not in ("cost_usd", "meta_cost_usd")},
                        "cost_usd": round(v["cost_usd"], 2),
                        "meta_cost_usd": round(v.get("meta_cost_usd", 0.0), 2),
                    }
                    for k, v in spend_by_day.items()
                },
            },
            indent=2,
        )
    )
    print(md)


if __name__ == "__main__":
    main()
