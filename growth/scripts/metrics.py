"""Daily growth scoreboard: ad spend (Google Ads) x new households (hal_turns).

Writes growth/reports/scoreboard-<date>.md and growth/state/metrics-latest.json.
DB URL is pulled at runtime from Railway (never persisted).
"""
import asyncio
import datetime as dt
import json
import pathlib
import re
import subprocess

import asyncpg
from google.ads.googleads.client import GoogleAdsClient

REPO = pathlib.Path("/Users/adnanakil/Project/agentlist")
CUSTOMER_ID = "4959722800"
DAYS = 14


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
        view_rows = await conn.fetch(
            """
            SELECT date(created_at) AS day, COUNT(*) AS n FROM hal_page_hits
            WHERE path = '/' AND NOT is_bot
              AND (utm_source IS NULL OR utm_source != 'verify-test')
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


def ad_spend() -> dict[str, dict]:
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


def main():
    total_households, new_by_day, new_by_source, views_by_day, tap_total = asyncio.run(households())
    spend_by_day = ad_spend()
    today = dt.date.today()
    days = [str(today - dt.timedelta(days=i)) for i in range(DAYS - 1, -1, -1)]

    window_spend = sum(d["cost_usd"] for d in spend_by_day.values())
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
        f"- Last {DAYS}d: **{window_new} new households**, ${window_spend:.2f} ad spend, "
        f"{window_clicks} paid clicks",
        f"- New households by acquisition source (last {DAYS}d): {by_source}",
        f"- Landing views (human, path=/) last {DAYS}d: **{window_views}** → "
        "view→household rate "
        + (f"**{window_new / window_views:.2%}**" if window_views else "n/a"),
        f"- SMS-link tap rate (last {DAYS}d): {tap_rate}",
        f"- Naive CPA (spend/new, organic mixed in): "
        + (f"**${naive_cpa:.2f}**" if naive_cpa is not None else "n/a (0 new)"),
        "",
        "| day | ad spend | impr | clicks | landing views | new households |",
        "|-----|----------|------|--------|---------------|----------------|",
    ]
    for d in days:
        s = spend_by_day.get(d, {"impressions": 0, "clicks": 0, "cost_usd": 0.0})
        lines.append(
            f"| {d} | ${s['cost_usd']:.2f} | {s['impressions']} | {s['clicks']} "
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
                "window_spend_usd": round(window_spend, 2),
                "window_clicks": window_clicks,
                "window_landing_views": window_views,
                "window_sms_taps": tap_total,
                "new_by_source": new_by_source,
                "views_by_day": views_by_day,
                "naive_cpa_usd": round(naive_cpa, 2) if naive_cpa is not None else None,
                "new_by_day": new_by_day,
                "spend_by_day": {k: {**v, "cost_usd": round(v["cost_usd"], 2)} for k, v in spend_by_day.items()},
            },
            indent=2,
        )
    )
    print(md)


if __name__ == "__main__":
    main()
