# Spec: `watch` tool — notify-when-condition + `sports_score` tool

**Status:** ready to build. Design is proven — it was implemented and fully
tested (incl. a live Gemini + live ESPN run) against the older monolith
(`ClaudeUI/hal/hal_agent.py`); this spec re-homes it onto the prod
`hal_orchestrator` package conventions. Nothing here needs re-derivation.

## Why
A user says *"let us know if the Knicks take the lead."* Today HAL has no
event-watch capability, so the model **confabulates** ("I set up a tracker")
and never fires. Separately, when an agent turn blows past the iteration cap it
leaks `"I ran into too many steps processing that…"` to the chat. `watch` gives
HAL a real conditional-notify primitive that stays **silent until the condition
is true**, then fires once and self-terminates.

## Core design principle
The "loop" is **persistent state (a DB row) + one shared background checker**,
NOT a long-lived task. Each poll spins up a *cheap, shallow, throwaway*
Gemini call that does ONE check and returns a structured verdict. This survives
redeploys, is enumerable/cancellable, and is cost-bounded.

The poll is a **direct lightweight `call_gemini`** (flash-lite + MINIMAL
thinking + narrow toolset) — **NOT** a self-POST through `/api/message` like
`services/cron.py` does. A silent high-frequency poll must not run the full
pro-model pipeline (expensive + side effects like memory writes).

## Lifecycle contract (the checker enforces ALL of these)
A watch terminates on the FIRST of:
| Terminator | Action |
|---|---|
| `condition_met` | enqueue notify → deactivate |
| `terminal` (situation permanently resolved, e.g. game FINAL) | deactivate, silent |
| `now > expires_at` | deactivate, silent |
| `polls_done >= max_polls` | deactivate, silent |
| `consecutive_fails >= 3` (circuit breaker) | deactivate, silent |
| user "stop watching" | `watch action=cancel` → delete |

**Silent on every outcome except a real hit.** All non-hit results log only.

---

## File-by-file

### 1. DB model — `packages/ag-db/ag_db/models.py`
Mirror `HalCronJob` (line ~591). Add:

```python
class HalWatch(Base):
    """Notify-when-condition watcher. A background checker re-polls `condition`
    on a cheap model and, the first time it's true, delivers `notify` once and
    deactivates. Silent until then. Distinct from HalCronJob (clock schedule)
    and HalReminder (static text)."""

    __tablename__ = "hal_watches"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    phone: Mapped[str] = mapped_column(String(255), nullable=False)        # silo / delivery target
    condition: Mapped[str] = mapped_column(Text, nullable=False)
    check_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    notify: Mapped[str] = mapped_column(Text, nullable=False)
    is_group: Mapped[bool] = mapped_column(Boolean, default=False)
    chat_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sender_phone: Mapped[str | None] = mapped_column(String(255), nullable=True)
    poll_every_seconds: Mapped[int] = mapped_column(Integer, default=150)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    max_polls: Mapped[int] = mapped_column(Integer, default=60)
    polls_done: Mapped[int] = mapped_column(Integer, default=0)
    consecutive_fails: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_observation: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (Index("ix_hal_watches_due", "active", "next_run_at"),)
```

**Migration (Alembic):** `cd packages/ag-db && alembic revision -m "add hal_watches"`
(or `--autogenerate` against a DB), hand-fill `create_table`/`drop_table`
mirroring an existing migration in `packages/ag-db/migrations/`, then
`alembic upgrade head` against the prod DB before/with deploy.

### 2. Config — `packages/ag-common/ag_common/config.py`
Add to `HalOrchestratorConfig` (NOTE: this file has WIP — merge carefully):
```python
gemini_watch_model: str = "gemini-3.1-flash-lite"   # cheap poll model (verified resolves)
watch_check_interval_seconds: int = 60
watch_max_per_silo: int = 3
```
`gemini-3.1-flash-lite` is confirmed live (raw generateContent returned OK; the
old `-preview` suffix is wrong). `thinkingLevel: "MINIMAL"` confirmed accepted.

### 3. `services/gemini.py` — add a per-call thinking override
`call_gemini` currently only reads `settings.gemini_thinking_level` (global).
Add an optional param so the watch poll can force MINIMAL regardless of global:
```python
async def call_gemini(..., thinking_level: str | None = None) -> dict | None:
    ...
    level = (thinking_level or settings.gemini_thinking_level or "").strip().upper()
    if level and level != "NONE":
        generation_config["thinkingConfig"] = {"thinkingLevel": level}
```
(Replaces the existing thinking_level block; default behavior unchanged.)

### 4. `tools/sports_score.py` — NEW (deterministic live scores)
ESPN public scoreboard JSON, no key. **Verified against live data** (returned
the real Knicks 94–90 Spurs final). Async port using `ctx.http_client`:
```python
from __future__ import annotations
import structlog
from hal_orchestrator.tools.registry import ToolContext

log = structlog.get_logger()
ESPN = "https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard"
LEAGUES = {
    "nba": "basketball/nba", "wnba": "basketball/wnba",
    "ncaab": "basketball/mens-college-basketball",
    "mens-college-basketball": "basketball/mens-college-basketball",
    "cbb": "basketball/mens-college-basketball",
    "ncaaw": "basketball/womens-college-basketball",
    "womens-college-basketball": "basketball/womens-college-basketball",
    "nfl": "football/nfl", "ncaaf": "football/college-football",
    "cfb": "football/college-football", "college-football": "football/college-football",
    "mlb": "baseball/mlb", "nhl": "hockey/nhl",
    "epl": "soccer/eng.1", "premier-league": "soccer/eng.1",
    "laliga": "soccer/esp.1", "mls": "soccer/usa.1",
    "ucl": "soccer/uefa.champions", "champions-league": "soccer/uefa.champions",
}

async def tool_sports_score(args: dict, ctx: ToolContext) -> str:
    league = (args.get("league") or "nba").strip().lower()
    team = (args.get("team") or "").strip().lower()
    path = LEAGUES.get(league) or (league if "/" in league else None)
    if not path:
        return f"Unknown league '{league}'. Try: {', '.join(sorted(LEAGUES))}."
    try:
        resp = await ctx.http_client.get(ESPN.format(path=path),
                                         headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        data = resp.json()
    except Exception as exc:
        log.exception("sports_score.error", league=league)
        return f"Score fetch failed: {exc}"

    def nm(c): t = c.get("team", {}); return t.get("displayName") or t.get("shortDisplayName") or "?"
    def ab(c): return (c.get("team", {}).get("abbreviation") or "").lower()

    lines = []
    for ev in data.get("events", []):
        try:
            cs = (ev.get("competitions") or [{}])[0].get("competitors") or []
            home = next((c for c in cs if c.get("homeAway") == "home"), None)
            away = next((c for c in cs if c.get("homeAway") == "away"), None)
            if not home or not away:
                continue
            hn, an = nm(home), nm(away)
            if team and team not in f"{hn} {an} {ab(home)} {ab(away)}".lower():
                continue
            st = (ev.get("status") or {}).get("type", {})
            state, detail = st.get("state", ""), st.get("shortDetail") or st.get("description") or ""
            if state == "pre":
                lines.append(f"{an} @ {hn} — not started yet ({detail}).")
                continue
            try:
                hs, as_ = int(home.get("score") or 0), int(away.get("score") or 0)
            except (TypeError, ValueError):
                lines.append(f"{an} @ {hn} — {detail}.")
                continue
            lead = (f"{hn} lead by {hs - as_}" if hs > as_
                    else f"{an} lead by {as_ - hs}" if as_ > hs else "tied")
            word = "FINAL" if state == "post" else "in progress"
            lines.append(f"{an} {as_}, {hn} {hs} — {detail} ({word}). {lead}.")
        except Exception:
            continue
    if not lines:
        return (f"No {league.upper()} game found today matching '{args.get('team')}'."
                if team else f"No {league.upper()} games today.")
    return "\n".join(lines)
```

### 5. `services/watch.py` — NEW (CRUD + checker + poll)
CRUD mirrors `services/cron.py` (`create_watch`/`list_watch`/`delete_watch`
using `get_session`, plus a per-silo active cap = `settings.watch_max_per_silo`,
and a dedupe: refuse a 2nd active watch with the same `condition` in a silo).

Background checker mirrors `run_cron_checker`:
```python
async def run_watch_checker(settings, http):
    while True:
        try:
            await asyncio.sleep(settings.watch_check_interval_seconds)
            await _check_and_run(settings, http)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("watch_checker.error"); await asyncio.sleep(10)

async def _check_and_run(settings, http):
    now = datetime.now(timezone.utc)
    async for session in get_session():
        due = (await session.execute(
            select(HalWatch).where(HalWatch.active == True, HalWatch.next_run_at <= now).limit(20)
        )).scalars().all()
        for w in due:
            # terminators BEFORE polling
            if now >= w.expires_at or w.polls_done >= w.max_polls or w.consecutive_fails >= 3:
                w.active = False; await session.flush(); continue
            verdict = await _poll(session, settings, http, w)   # {condition_met,terminal,observation}|None
            w.last_run_at = now
            if verdict is None:
                w.consecutive_fails += 1
            elif verdict.get("condition_met"):
                to = w.chat_id if (w.is_group and w.chat_id) else w.phone
                msg = w.notify + (f"\n{verdict.get('observation','')}" if verdict.get("observation") else "")
                import hal_orchestrator.state as state
                await state.outbox.put({"to": to, "text": msg})
                w.active = False
            elif verdict.get("terminal"):
                w.active = False
            else:
                w.consecutive_fails = 0
                w.polls_done += 1
                w.last_observation = (verdict.get("observation") or "")[:500]
                w.next_run_at = now + timedelta(seconds=w.poll_every_seconds)
            await session.flush()
        await session.commit()
```

The poll — cheap, shallow, narrow tools, structured JSON:
```python
WATCH_POLL_SYSTEM = """You are HAL's watch-poll worker. Run ONE quick check, then stop.
- For sports/score conditions call sports_score ONCE; do NOT web_search for scores.
- Otherwise use web_search/web_fetch at most twice. You CANNOT message anyone.
- Reply with ONLY a JSON object: {"condition_met": bool, "terminal": bool, "observation": "<one line>"}
- condition_met: true only if clearly true right now. terminal: true if permanently resolved (e.g. game FINAL).
- If unsure, condition_met=false."""

async def _poll(session, settings, http, w):
    from hal_orchestrator.prompts.tool_defs import get_agent_tools
    from hal_orchestrator.tools.registry import ToolContext, execute_tool
    from hal_orchestrator.services.gemini import call_gemini

    tools = get_agent_tools(["sports_score", "web_search", "web_fetch"])
    ctx = ToolContext(phone=w.phone, session=session, settings=settings, http_client=http,
                      chat_id=w.chat_id, sender_phone=w.sender_phone, is_group=w.is_group)
    history = [{"role": "user", "parts": [{"text":
        f"Condition: {w.condition}\nCheck: {w.check_prompt}\nReturn the JSON object only."}]}]
    for _ in range(3):  # depth cap — a single check can't loop
        resp = await call_gemini(http, settings, history, tools=tools, system=WATCH_POLL_SYSTEM,
                                 model=settings.gemini_watch_model, thinking_level="MINIMAL")
        if not resp:
            return None
        parts = (resp.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
        calls = [p["functionCall"] for p in parts if "functionCall" in p]
        if calls:
            history.append({"role": "model", "parts": parts})
            responses = []
            for fc in calls:
                out = await execute_tool(fc["name"], fc.get("args", {}), ctx)  # only narrow tools are declared
                responses.append({"functionResponse": {"name": fc["name"], "response": {"result": out}}})
            history.append({"role": "user", "parts": responses})
            continue
        text = "".join(p.get("text", "") for p in parts if "text" in p)
        return _extract_json(text)   # strip ``` fences, first { .. last }
    return None
```
`_extract_json`: strip markdown fences, take first `{` … last `}`, `json.loads`,
return dict or None. (Proven helper — see monolith `_extract_watch_json`.)

### 6. `tools/watch.py` — NEW (the tool the agent calls)
`async def tool_watch(args, ctx) -> str` with actions create/list/cancel,
calling `services/watch.py` CRUD. On create: validate `condition`; default
`check_prompt=condition`, `notify=f"Heads up — {condition}"`; clamp
`poll_every_seconds` (min 90), `expires_in_min` (default 360, derive ISO
`expires_at`), `max_polls` (default 60). Set `phone=ctx.phone` (silo),
`chat_id=ctx.chat_id`, `is_group=ctx.is_group`, `sender_phone=ctx.sender_phone`
so notify routes to the group/1:1 correctly.

### 7. `tools/registry.py` — register
Add imports + handlers:
```python
"watch": lambda: tool_watch(args, ctx),
"sports_score": lambda: tool_sports_score(args, ctx),
```

### 8. `prompts/tool_defs.py` — add to `MAIN_TOOLS`
Add two function declarations (this file has WIP — merge carefully):
- `sports_score(league, team?)` — "live/today's scores from ESPN; use for
  'what's the score' and score watch conditions; more reliable than web_search."
- `watch(action, condition, check_prompt?, notify?, poll_every_sec?,
  expires_in_min?, max_polls?, job_id?)` — "Notify once when a condition
  becomes true, then stop. For 'let me know if/when X happens'. If you promise
  to alert them you MUST create a watch. Distinct from schedule (clock) and
  set_reminder (static text)."

### 9. `prompts/system.py` — guidance
Add a short section: use `watch` for "let me know if/when X"; set
`expires_in_min` to the realistic window (a game ~180); **never claim to watch
without creating one**; "stop watching" → `watch action=cancel`.

### 10. `main.py` — start the checker
In `lifespan`, alongside the others:
```python
from hal_orchestrator.services.watch import run_watch_checker
watch_task = asyncio.create_task(run_watch_checker(settings, state.http_client))
```
and add `watch_task` to the shutdown cancel tuple.

---

## Cost / safety rails (Gemini bill is sensitive)
- Poll model = `gemini-3.1-flash-lite` @ `thinkingLevel=MINIMAL`.
- Depth cap **3 iterations** per poll; narrow 3-tool allow-list → a single check
  can't become a runaway loop (the original "too many steps" failure mode).
- Poll floor ≥90s; `max_polls` (default 60) and `expires_at` bound total cost
  absolutely; breaker reaps after 3 consecutive failed polls.
- Per-silo active cap (`watch_max_per_silo=3`) + same-condition dedupe.

## Test checklist
- Unit: `sports_score` parsing (leader flip, team filter, pre/in/post, unknown
  league) against a mocked ESPN payload.
- Unit: `_poll` verdict branches → met=notify+deactivate, terminal=silent
  deactivate, miss=reschedule+polls_done++, None=fails++; terminators
  (expiry/max_polls/breaker) deactivate before polling.
- Live: one real watch on a current game; confirm it stays silent until the
  condition flips, fires once, and `active` goes False.

## Reference
Proven monolith implementation (logic identical, structure differs):
`ClaudeUI/hal/hal_agent.py` (`_watch_poll_check`, `_run_watch_poll`,
`tool_sports_score`) and `ClaudeUI/hal/cron_jobs.py` (watch store + handler).
It passed unit tests + a live Gemini (`gemini-3.1-flash-lite` + MINIMAL) + live
ESPN run.
