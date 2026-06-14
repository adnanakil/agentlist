"""sports_score tool — deterministic live scores from ESPN's public scoreboard.

No API key. More reliable than web_search for "what's the score" and for watch
conditions about games. Async port using ctx.http_client (verified against live
ESPN data — returned a real Knicks 94-90 Spurs final)."""

from __future__ import annotations

import structlog

from hal_orchestrator.tools.registry import ToolContext

log = structlog.get_logger()

ESPN = "https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard"
LEAGUES = {
    "nba": "basketball/nba",
    "wnba": "basketball/wnba",
    "ncaab": "basketball/mens-college-basketball",
    "mens-college-basketball": "basketball/mens-college-basketball",
    "cbb": "basketball/mens-college-basketball",
    "ncaaw": "basketball/womens-college-basketball",
    "womens-college-basketball": "basketball/womens-college-basketball",
    "nfl": "football/nfl",
    "ncaaf": "football/college-football",
    "cfb": "football/college-football",
    "college-football": "football/college-football",
    "mlb": "baseball/mlb",
    "nhl": "hockey/nhl",
    "epl": "soccer/eng.1",
    "premier-league": "soccer/eng.1",
    "laliga": "soccer/esp.1",
    "mls": "soccer/usa.1",
    "ucl": "soccer/uefa.champions",
    "champions-league": "soccer/uefa.champions",
}


def _name(c: dict) -> str:
    t = c.get("team", {})
    return t.get("displayName") or t.get("shortDisplayName") or "?"


def _abbr(c: dict) -> str:
    return (c.get("team", {}).get("abbreviation") or "").lower()


async def tool_sports_score(args: dict, ctx: ToolContext) -> str:
    league = (args.get("league") or "nba").strip().lower()
    team = (args.get("team") or "").strip().lower()
    path = LEAGUES.get(league) or (league if "/" in league else None)
    if not path:
        return f"Unknown league '{league}'. Try: {', '.join(sorted(LEAGUES))}."

    try:
        resp = await ctx.http_client.get(
            ESPN.format(path=path),
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        data = resp.json()
    except Exception as exc:
        log.exception("sports_score.error", league=league)
        return f"Score fetch failed: {exc}"

    lines: list[str] = []
    for ev in data.get("events", []):
        try:
            cs = (ev.get("competitions") or [{}])[0].get("competitors") or []
            home = next((c for c in cs if c.get("homeAway") == "home"), None)
            away = next((c for c in cs if c.get("homeAway") == "away"), None)
            if not home or not away:
                continue
            hn, an = _name(home), _name(away)
            if team and team not in f"{hn} {an} {_abbr(home)} {_abbr(away)}".lower():
                continue
            st = (ev.get("status") or {}).get("type", {})
            state = st.get("state", "")
            detail = st.get("shortDetail") or st.get("description") or ""
            if state == "pre":
                lines.append(f"{an} @ {hn} — not started yet ({detail}).")
                continue
            try:
                hs, as_ = int(home.get("score") or 0), int(away.get("score") or 0)
            except (TypeError, ValueError):
                lines.append(f"{an} @ {hn} — {detail}.")
                continue
            lead = (
                f"{hn} lead by {hs - as_}"
                if hs > as_
                else f"{an} lead by {as_ - hs}"
                if as_ > hs
                else "tied"
            )
            word = "FINAL" if state == "post" else "in progress"
            lines.append(f"{an} {as_}, {hn} {hs} — {detail} ({word}). {lead}.")
        except Exception:
            continue

    if not lines:
        return (
            f"No {league.upper()} game found today matching '{args.get('team')}'."
            if team
            else f"No {league.upper()} games today."
        )
    return "\n".join(lines)
