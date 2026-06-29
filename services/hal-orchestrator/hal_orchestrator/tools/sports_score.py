"""sports_score tool — deterministic live scores from ESPN's public scoreboard.

No API key. More reliable than web_search for "what's the score" and for watch
conditions about games. Async port using ctx.http_client (verified against live
ESPN data — returned a real Knicks 94-90 Spurs final)."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import structlog

from hal_orchestrator.tools.registry import ToolContext

log = structlog.get_logger()

ET = ZoneInfo("America/New_York")


def _event_date(ev: dict) -> date | None:
    """Local (ET) date the game was played, from ESPN's UTC ISO `date`."""
    raw = ev.get("date") or ""
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.astimezone(ET).date()
    except (ValueError, AttributeError):
        return None

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
    # International tournaments — ESPN keys them separately from club leagues, so
    # a World Cup match (e.g. the 2026 tournament) won't show up under epl/etc.
    "worldcup": "soccer/fifa.world",
    "world-cup": "soccer/fifa.world",
    "fifa-world-cup": "soccer/fifa.world",
    "wc": "soccer/fifa.world",
    "fifa": "soccer/fifa.world",
}


def _name(c: dict) -> str:
    t = c.get("team", {})
    return t.get("displayName") or t.get("shortDisplayName") or "?"


def _abbr(c: dict) -> str:
    return (c.get("team", {}).get("abbreviation") or "").lower()


async def tool_sports_score(args: dict, ctx: ToolContext) -> str:
    # Normalize "world cup" -> "world-cup" etc. so multi-word leagues resolve.
    league = (args.get("league") or "nba").strip().lower().replace(" ", "-")
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

    # ESPN's scoreboard falls back to the most recent slate when nothing is on
    # today (e.g. offseason), so it can return a multi-day-old Final. Without a
    # date that reads as "tonight". Anchor every game to its real local date and
    # separate today's games (the live answer) from stale past ones.
    today = datetime.now(ET).date()
    today_lines: list[str] = []
    past_lines: list[str] = []

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

            game_day = _event_date(ev)
            is_today = game_day == today

            st = (ev.get("status") or {}).get("type", {})
            state = st.get("state", "")
            detail = st.get("shortDetail") or st.get("description") or ""

            if state == "pre":
                if is_today:
                    today_lines.append(f"{an} @ {hn} — not started yet ({detail}).")
                continue
            try:
                hs, as_ = int(home.get("score") or 0), int(away.get("score") or 0)
            except (TypeError, ValueError):
                continue
            margin = (
                f"{hn} lead by {hs - as_}" if hs > as_
                else f"{an} lead by {as_ - hs}" if as_ > hs
                else "tied"
            )
            if is_today:
                word = "FINAL" if state == "post" else "in progress"
                today_lines.append(f"{an} {as_}, {hn} {hs} — {detail} ({word}). {margin}.")
            elif state == "post":
                # A finished game from another day — date it explicitly so it's
                # never reported as happening now.
                when = game_day.strftime("%a %b %-d") if game_day else "previously"
                winner = hn if hs > as_ else an
                loser = an if hs > as_ else hn
                ws, ls = (hs, as_) if hs > as_ else (as_, hs)
                past_lines.append(f"{winner} beat {loser} {ws}-{ls} on {when} (final).")
        except Exception:
            continue

    if today_lines:
        return "\n".join(today_lines)
    # No games today — say so plainly, then offer the most recent result clearly
    # dated, so HAL never presents an old game as live.
    none_msg = (
        f"No {league.upper()} game today for '{args.get('team')}'."
        if team
        else f"No {league.upper()} games today."
    )
    if past_lines:
        return none_msg + " Most recent: " + past_lines[0]
    return none_msg
